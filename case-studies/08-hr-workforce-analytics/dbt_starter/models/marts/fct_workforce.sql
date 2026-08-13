with person as (
    select * from {{ ref('int_person_employment_history') }}
),

departments as (
    select * from {{ ref('stg_departments') }}
),

-- Latest payroll for cost-per-head
latest_pay as (
    select
        person_id,
        gross_pay_usd as latest_monthly_pay_usd,
        gross_pay as latest_monthly_pay_local,
        currency as pay_currency
    from {{ ref('int_payroll_monthly') }}
    qualify row_number() over (
        partition by person_id
        order by pay_period desc
    ) = 1
),

-- Latest performance rating
latest_review as (
    select
        person_id,
        rating as latest_rating,
        review_score as latest_review_score,
        review_period as latest_review_period
    from {{ ref('stg_performance_reviews') }}
    qualify row_number() over (
        partition by person_id
        order by review_period desc, review_date desc nulls last
    ) = 1
)

select
    p.person_id,
    p.full_name,
    p.is_currently_active,

    -- Current assignment
    p.current_employee_id,
    p.current_department_id,
    d.department_name as current_department_name,
    d.division as current_division,
    d.cost_center as current_cost_center,
    p.current_job_level,
    p.current_employment_type,
    p.current_location,

    -- Employment history
    p.first_hire_date,
    p.current_stint_start_date,
    p.last_termination_date,
    p.total_stints,
    p.total_transfers,
    p.is_rehire,
    p.has_transferred,

    -- Tenure (three definitions)
    p.tenure_current_stint_days,
    p.tenure_current_stint_years,
    p.tenure_total_service_days,
    p.tenure_total_service_years,
    p.tenure_continuous_days,
    round(p.tenure_continuous_days / 365.25, 1) as tenure_continuous_years,

    -- Compensation
    lp.latest_monthly_pay_usd,
    lp.latest_monthly_pay_local,
    lp.pay_currency,
    lp.latest_monthly_pay_usd * 12 as annualized_pay_usd,

    -- Performance
    lr.latest_rating,
    lr.latest_review_score,
    lr.latest_review_period

from person p
left join departments d
    on p.current_department_id = d.department_id
left join latest_pay lp
    on p.person_id = lp.person_id
left join latest_review lr
    on p.person_id = lr.person_id