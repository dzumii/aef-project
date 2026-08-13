with source as (
    select * from {{ source('raw', 'raw_payroll') }}
),

-- Deduplicate cancelled/reissued runs: keep latest paid_at per employee-period
ranked as (
    select
        *,
        row_number() over (
            partition by employee_id, pay_period
            order by paid_at desc
        ) as _row_num
    from source
),

cleaned as (
    select
        payroll_id,
        employee_id,
        person_id,
        pay_period::date as pay_period,
        gross_pay,
        currency,
        is_partial_period,
        paid_at,
        case when _row_num > 1 then true else false end as is_cancelled_run,

        -- USD conversion (fixed rates for sprint)
        gross_pay * case currency
            when 'USD' then 1.00
            when 'GBP' then 1.27
            when 'EUR' then 1.09
            when 'SGD' then 0.74
        end as gross_pay_usd

    from ranked
)

select * from cleaned
where not is_cancelled_run