with source as (
    select * from {{ source('raw', 'raw_employees') }}
),

-- Remove 26 duplicate active records (same person, dept, hire_date, both active, no linkage)
deduplicated as (
    select
        *,
        row_number() over (
            partition by person_id, department_id, hire_date, employment_status
            order by employee_id asc
        ) as _row_num
    from source
),

cleaned as (
    select
        employee_id,
        person_id,
        full_name,
        department_id,
        job_level,
        employment_type,
        location,
        hire_date::date as hire_date,
        termination_date::date as termination_date,
        employment_status,
        prior_employee_id,

        -- Flag: status says terminated but no date
        case
            when employment_status = 'terminated' and termination_date is null
            then true else false
        end as is_missing_termination_date,

        -- Flag: this is a duplicate that will be removed
        case when _row_num > 1 then true else false end as is_duplicate_record

    from deduplicated
)

select * from cleaned
where not is_duplicate_record