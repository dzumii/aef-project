-- Every transferred record should have a successor (except known exceptions)
select
    e.employee_id,
    e.person_id
from {{ ref('stg_employees') }} e
where e.employment_status = 'transferred'
  and not exists (
    select 1
    from {{ ref('stg_employees') }} s
    where s.prior_employee_id = e.employee_id
  )