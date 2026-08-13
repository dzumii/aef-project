with stints as (
    select * from {{ ref('int_employment_stints') }}
),

persons as (
    select * from {{ ref('int_person_employment_history') }}
),

-- Measurement: trailing 12 months from most recent data
date_bounds as (
    select
        dateadd('month', -12, max(termination_date))::date as period_start,
        max(termination_date)::date as period_end
    from stints
    where termination_date is not null
),

-- Finance's view: any record with a termination_date in period = an exit
finance_exits as (
    select
        count(*) as finance_exit_count,
        count(case when employment_status = 'terminated' then 1 end) as finance_true_terminations,
        count(case when employment_status = 'transferred' then 1 end) as finance_transfer_exits
    from stints, date_bounds db
    where termination_date between db.period_start and db.period_end
      and employment_status in ('terminated', 'transferred')
),

-- Talent's view: persons who left and never came back
talent_exits as (
    select
        count(distinct person_id) as talent_exit_count
    from (
        select
            s.person_id,
            s.stint_end_date
        from stints s, date_bounds db
        where s.employment_status = 'terminated'
          and s.termination_date between db.period_start and db.period_end
        qualify row_number() over (
            partition by s.person_id, s.stint_id
            order by s.employee_id desc
        ) = 1
    ) exits
    where not exists (
        select 1 from persons p
        where p.person_id = exits.person_id
          and p.is_currently_active = 1
    )
),

-- Reconciled view: true person-level exits in period
reconciled_exits as (
    select
        count(distinct person_id) as reconciled_exit_count
    from (
        select
            s.person_id,
            s.termination_date
        from stints s, date_bounds db
        where s.employment_status = 'terminated'
          and s.termination_date between db.period_start and db.period_end
        qualify row_number() over (
            partition by s.person_id, s.stint_id
            order by s.employee_id desc
        ) = 1
    )
),

-- Denominator: average headcount over period
headcount as (
    select
        count(case when is_currently_active = 1 then 1 end) as current_active
    from persons
),

-- Components of the spread
spread_components as (
    select
        f.finance_exit_count,
        f.finance_true_terminations,
        f.finance_transfer_exits,
        t.talent_exit_count,
        r.reconciled_exit_count,
        h.current_active as avg_headcount_approx,

        -- Rates
        round(f.finance_exit_count::float / h.current_active * 100, 1) as finance_attrition_pct,
        round(t.talent_exit_count::float / h.current_active * 100, 1) as talent_attrition_pct,
        round(r.reconciled_exit_count::float / h.current_active * 100, 1) as reconciled_attrition_pct,

        -- Bridge components
        f.finance_transfer_exits as bridge_transfers_removed,
        r.reconciled_exit_count - t.talent_exit_count as bridge_rehire_exits_added_back
    from finance_exits f, talent_exits t, reconciled_exits r, headcount h
)

select
    'Finance record-based exits' as line_item,
    finance_exit_count as value,
    finance_attrition_pct as rate_pct,
    null as adjustment
from spread_components

union all
select
    'Less: Transfers miscounted as exits',
    finance_transfer_exits * -1,
    null,
    'Transfers are internal moves, not departures'
from spread_components

union all
select
    'Reconciled exits (person-level)',
    reconciled_exit_count,
    reconciled_attrition_pct,
    null
from spread_components

union all
select
    'Talent net exits (excludes rehired persons)',
    talent_exit_count,
    talent_attrition_pct,
    null
from spread_components

union all
select
    'Difference: rehires whose departure still counts',
    reconciled_exit_count - talent_exit_count,
    null,
    'Person left in-period; returned later. Exit still counts in the period it occurred.'
from spread_components