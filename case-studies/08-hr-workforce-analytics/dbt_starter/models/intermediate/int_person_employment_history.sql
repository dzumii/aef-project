with stints as (
    select * from {{ ref('int_employment_stints') }}
),

-- One row per person per stint (deduplicated to stint level)
person_stints as (
    select
        person_id,
        full_name,
        stint_id,
        stint_number,
        stint_start_date,
        stint_end_date,
        is_active_stint,
        records_in_stint,
        transfers_in_stint,
        -- Days in this stint
        datediff('day', stint_start_date,
            coalesce(stint_end_date, current_date)
        ) as stint_days
    from stints
    -- Take one row per stint (the latest record in the stint = current state)
    qualify row_number() over (
        partition by stint_id
        order by hire_date desc, employee_id desc
    ) = 1
),

-- Person-level aggregation
person_agg as (
    select
        person_id,
        max(full_name) as full_name,
        count(distinct stint_id) as total_stints,
        max(case when is_active_stint = 1 then 1 else 0 end) as is_currently_active,
        min(stint_start_date) as first_hire_date,
        max(stint_end_date) as last_termination_date,
        max(case when is_active_stint = 1 then stint_start_date end) as current_stint_start_date,
        sum(stint_days) as total_service_days,
        sum(transfers_in_stint) as total_transfers
    from person_stints
    group by person_id
),

-- Get current record details for active persons
current_record as (
    select
        person_id,
        employee_id as current_employee_id,
        department_id as current_department_id,
        job_level as current_job_level,
        employment_type as current_employment_type,
        location as current_location
    from stints
    where employment_status = 'active'
    qualify row_number() over (
        partition by person_id
        order by hire_date desc, employee_id desc
    ) = 1
)

select
    pa.person_id,
    pa.full_name,
    pa.is_currently_active,
    pa.total_stints,
    pa.first_hire_date,
    pa.last_termination_date,
    pa.current_stint_start_date,
    pa.total_transfers,

    -- Current assignment (NULL for inactive persons)
    cr.current_employee_id,
    cr.current_department_id,
    cr.current_job_level,
    cr.current_employment_type,
    cr.current_location,

    -- Tenure: current stint (days in current continuous employment)
    case
        when pa.is_currently_active = 1
        then datediff('day', pa.current_stint_start_date, current_date)
        else null
    end as tenure_current_stint_days,

    -- Tenure: total service (sum of all days actually employed, excludes gaps)
    pa.total_service_days as tenure_total_service_days,

    -- Tenure: continuous (first hire to now/last term, includes gaps)
    datediff('day', pa.first_hire_date,
        case
            when pa.is_currently_active = 1 then current_date
            else pa.last_termination_date
        end
    ) as tenure_continuous_days,

    -- Classification flags
    case when pa.total_stints > 1 then true else false end as is_rehire,
    case when pa.total_transfers > 0 then true else false end as has_transferred,

    -- Years for readability
    round(pa.total_service_days / 365.25, 1) as tenure_total_service_years,
    case
        when pa.is_currently_active = 1
        then round(datediff('day', pa.current_stint_start_date, current_date) / 365.25, 1)
        else null
    end as tenure_current_stint_years

from person_agg pa
left join current_record cr
    on pa.person_id = cr.person_id