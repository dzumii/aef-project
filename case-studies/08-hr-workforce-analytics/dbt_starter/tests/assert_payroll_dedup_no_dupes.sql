-- After dedup, no employee should have two payroll rows for the same period
select
    employee_id,
    pay_period,
    count(*) as cnt
from {{ ref('stg_payroll') }}
group by 1, 2
having count(*) > 1