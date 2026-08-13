with employees as (
    select * from {{ ref('stg_employees') }}
),

-- Classify each record's relationship to its predecessor
classified as (
    select
        e.employee_id,
        e.person_id,
        e.full_name,
        e.department_id,
        e.job_level,
        e.employment_type,
        e.location,
        e.hire_date,
        e.termination_date,
        e.employment_status,
        e.prior_employee_id,
        e.is_missing_termination_date,

        -- Determine if this record starts a new stint or continues one
        case
            when e.prior_employee_id is null then 'new_stint'
            when pred.employment_status = 'transferred' then 'transfer_continuation'
            when pred.employment_status = 'terminated' then 'rehire_new_stint'
            else 'new_stint'
        end as record_type

    from employees e
    left join employees pred
        on e.prior_employee_id = pred.employee_id
),

-- Assign stint IDs by walking backwards through transfer chains
-- A stint starts when record_type is 'new_stint' or 'rehire_new_stint'
stint_starts as (
    select
        employee_id,
        person_id,
        case
            when record_type in ('new_stint', 'rehire_new_stint') then employee_id
            else null
        end as stint_start_employee_id
    from classified
),

-- Recursive CTE to propagate stint_start_employee_id through transfer chains
stint_chains as (
    -- Base: records that start a stint
    select
        employee_id,
        person_id,
        employee_id as stint_id,
        0 as depth
    from classified
    where record_type in ('new_stint', 'rehire_new_stint')

    union all

    -- Recursive: transfers that continue a stint
    select
        c.employee_id,
        c.person_id,
        sc.stint_id,
        sc.depth + 1
    from classified c
    inner join stint_chains sc
        on c.prior_employee_id = sc.employee_id
    where c.record_type = 'transfer_continuation'
),

-- Join back to get full record detail with stint_id
with_stints as (
    select
        c.*,
        sc.stint_id,
        -- Number stints per person chronologically
        dense_rank() over (
            partition by c.person_id
            order by c.hire_date, c.employee_id
        ) as stint_number_raw
    from classified c
    inner join stint_chains sc
        on c.employee_id = sc.employee_id
),

-- Calculate stint-level attributes
stint_summary as (
    select
        stint_id,
        person_id,
        min(hire_date) as stint_start_date,
        -- Stint end = termination_date of the final record in the stint
        -- (NULL if the stint is still active)
        max(case
            when employment_status = 'active' then null
            when employment_status = 'transferred' then null  -- mid-stint, not the end
            else termination_date
        end) as stint_end_date_raw,
        max(case when employment_status = 'active' then 1 else 0 end) as is_active_stint,
        count(*) as records_in_stint,
        count(case when employment_status = 'transferred' then 1 end) as transfers_in_stint
    from with_stints
    group by stint_id, person_id
)

select
    ws.employee_id,
    ws.person_id,
    ws.full_name,
    ws.department_id,
    ws.job_level,
    ws.employment_type,
    ws.location,
    ws.hire_date,
    ws.termination_date,
    ws.employment_status,
    ws.prior_employee_id,
    ws.is_missing_termination_date,
    ws.record_type,
    ws.stint_id,

    -- Stint-level fields
    ss.stint_start_date,
    case
        when ss.is_active_stint = 1 then null
        else ss.stint_end_date_raw
    end as stint_end_date,
    ss.is_active_stint,
    ss.records_in_stint,
    ss.transfers_in_stint,

    -- Stint number per person (1 = first employment, 2 = rehire, etc.)
    dense_rank() over (
        partition by ws.person_id
        order by ss.stint_start_date, ws.stint_id
    ) as stint_number

from with_stints ws
inner join stint_summary ss
    on ws.stint_id = ss.stint_id