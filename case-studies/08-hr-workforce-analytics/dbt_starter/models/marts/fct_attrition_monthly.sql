with months as (
    -- Generate a month spine from data range
    select dateadd('month', seq4(), '2016-01-01')::date as month_start
    from table(generator(rowcount => 120))
    where dateadd('month', seq4(), '2016-01-01') <= current_date
),

stints as (
    select * from {{ ref('int_employment_stints') }}
),

-- Person-level exits: a person exits when their LAST stint ends (not transfers)
person_exits as (
    select
        person_id,
        stint_end_date as exit_date,
        stint_number
    from (
        select
            person_id,
            stint_start_date,
            case
                when is_active_stint = 1 then null
                else stint_end_date
            end as stint_end_date,
            stint_number,
            max(stint_number) over (partition by person_id) as max_stint_number
        from stints
        qualify row_number() over (
            partition by person_id, stint_id
            order by employee_id desc
        ) = 1
    )
    where stint_end_date is not null
),

-- Person-level hires (including rehires)
person_hires as (
    select
        person_id,
        stint_start_date as hire_date,
        stint_number,
        case when stint_number > 1 then true else false end as is_rehire
    from stints
    qualify row_number() over (
        partition by person_id, stint_id
        order by employee_id asc
    ) = 1
),

-- Monthly events
monthly_events as (
    select
        m.month_start,
        coalesce(h.hires, 0) as hires,
        coalesce(h.rehires, 0) as rehires,
        coalesce(e.exits, 0) as exits
    from months m
    left join (
        select
            date_trunc('month', hire_date)::date as month_start,
            count(*) as hires,
            sum(case when is_rehire then 1 else 0 end) as rehires
        from person_hires
        group by 1
    ) h on m.month_start = h.month_start
    left join (
        select
            date_trunc('month', exit_date)::date as month_start,
            count(*) as exits
        from person_exits
        group by 1
    ) e on m.month_start = e.month_start
),

-- Active headcount at end of each month
monthly_headcount as (
    select
        m.month_start,
        count(distinct ps.person_id) as active_headcount_eom
    from months m
    cross join (
        select person_id, stint_start_date, stint_end_date
        from stints
        qualify row_number() over (
            partition by person_id, stint_id
            order by employee_id desc
        ) = 1
    ) ps
    where ps.stint_start_date <= dateadd('month', 1, m.month_start)
      and (ps.stint_end_date is null or ps.stint_end_date > m.month_start)
    group by 1
)

select
    me.month_start,
    mh.active_headcount_eom,
    me.hires,
    me.rehires,
    me.exits,

    -- Trailing 12-month attrition
    sum(me.exits) over (
        order by me.month_start
        rows between 11 preceding and current row
    ) as exits_trailing_12m,

    round(
        sum(me.exits) over (
            order by me.month_start
            rows between 11 preceding and current row
        )::float
        / nullif(avg(mh.active_headcount_eom) over (
            order by me.month_start
            rows between 11 preceding and current row
        ), 0)
        * 100, 2
    ) as attrition_rate_trailing_12m,

    -- Monthly attrition (annualized)
    round(
        me.exits::float / nullif(mh.active_headcount_eom, 0) * 12 * 100, 2
    ) as attrition_rate_annualized

from monthly_events me
inner join monthly_headcount mh
    on me.month_start = mh.month_start
order by me.month_start