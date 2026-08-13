-- Every payroll record should reference a valid employee
select
    p.employee_id
from {{ ref('int_payroll_monthly') }}  p
left join {{ ref('stg_employees') }} e
    on p.employee_id = e.employee_id
where e.employee_id is null
limit 1