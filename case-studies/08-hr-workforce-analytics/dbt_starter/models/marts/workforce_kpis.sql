with persons as (
    select * from {{ ref('int_person_employment_history') }}
),

stints as (
    select * from {{ ref('int_employment_stints') }}
),

date_bounds as (
    select
        dateadd('month', -12, max(termination_date))::date as period_start,
        max(termination_date)::date as period_end
    from stints
    where termination_date is not null
),

headcount as (
    select count(*) as active_headcount
    from persons
    where is_currently_active = 1
),

exits as (
    select count(distinct person_id) as true_exits
    from (
        select
            s.person_id,
            row_number() over (
                partition by s.person_id, s.stint_id
                order by s.employee_id desc
            ) as rn
        from stints s, date_bounds db
        where s.employment_status = 'terminated'
          and s.termination_date between db.period_start and db.period_end
    )
    where rn = 1
),

transfers as (
    select count(*) as transfer_count
    from stints s, date_bounds db
    where s.employment_status = 'transferred'
      and s.termination_date between db.period_start and db.period_end
),

rehires as (
    select count(distinct s.person_id) as rehire_count
    from stints s, date_bounds db
    where s.record_type = 'rehire_new_stint'
      and s.hire_date between db.period_start and db.period_end
),

tenure_stats as (
    select
        round(avg(tenure_total_service_years), 2) as avg_tenure_total_service_yrs,
        round(avg(tenure_current_stint_years), 2) as avg_tenure_current_stint_yrs,
        round(avg(tenure_continuous_days / 365.25), 2) as avg_tenure_continuous_yrs,
        round(median(tenure_total_service_years), 2) as median_tenure_total_service_yrs
    from persons
    where is_currently_active = 1
)

select
    h.active_headcount,
    e.true_exits,
    round(e.true_exits::float / h.active_headcount * 100, 2) as attrition_rate_pct,
    t.transfer_count as internal_transfers_12m,
    round(t.transfer_count::float / h.active_headcount * 100, 2) as internal_mobility_rate_pct,
    r.rehire_count as rehires_12m,
    round(r.rehire_count::float / h.active_headcount * 100, 2) as rehire_rate_pct,
    ts.avg_tenure_total_service_yrs,
    ts.avg_tenure_current_stint_yrs,
    ts.avg_tenure_continuous_yrs,
    ts.median_tenure_total_service_yrs,
    round(ts.avg_tenure_continuous_yrs - ts.avg_tenure_current_stint_yrs, 2) as tenure_spread_yrs,
    db.period_start,
    db.period_end

from headcount h, exits e, transfers t, rehires r, tenure_stats ts, date_bounds db