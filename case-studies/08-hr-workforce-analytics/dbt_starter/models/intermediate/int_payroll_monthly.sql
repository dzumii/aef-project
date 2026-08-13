with payroll as (
    select * from {{ ref('stg_payroll') }}
),

employees as (
    select
        employee_id,
        person_id,
        department_id
    from {{ ref('stg_employees') }}
)

select
    p.payroll_id,
    p.employee_id,
    p.person_id,
    e.department_id,
    p.pay_period,
    date_trunc('month', p.pay_period) as pay_month,
    p.gross_pay,
    p.currency,
    p.gross_pay_usd,
    p.is_partial_period,
    p.paid_at

from payroll p
inner join employees e
    on p.employee_id = e.employee_id