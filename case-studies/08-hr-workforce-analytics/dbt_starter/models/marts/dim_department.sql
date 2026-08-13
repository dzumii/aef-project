with departments as (
    select * from {{ ref('stg_departments') }}
),

headcounts as (
    select
        current_department_id as department_id,
        count(*) as active_headcount
    from {{ ref('int_person_employment_history') }}
    where is_currently_active = 1
    group by 1
)

select
    d.department_id,
    d.department_code,
    d.department_name,
    d.division,
    d.cost_center,
    coalesce(h.active_headcount, 0) as active_headcount

from departments d
left join headcounts h
    on d.department_id = h.department_id