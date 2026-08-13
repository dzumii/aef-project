with trips as (
    select * from {{ ref('stg_trips') }}
),

payments as (
    select * from {{ ref('stg_payments') }}
),

incentives as (
    select
        trip_id,
        sum(bonus_amount) as total_incentive_amount,
        count(*) as incentive_line_count,
        max(is_multi_campaign_trip) as is_multi_campaign_trip
    from {{ ref('stg_driver_incentives') }}
    group by trip_id
),

-- Assumption 4: fixed GBP→USD rate of 1.27
currency_rates as (
    select
        'GBP' as from_currency,
        'USD' as to_currency,
        1.27 as exchange_rate
),

joined as (
    select
        t.trip_id,
        t.rider_id,
        t.driver_id,
        t.city,
        t.product,
        t.trip_status,
        t.cancel_reason,
        t.trip_classification,
        t.is_completed,
        t.is_revenue_eligible,
        t.has_cancellation_fee,
        t.is_fraud_flagged,
        t.surge_multiplier,
        t.currency,

        -- Fares (local currency)
        t.gross_fare,
        coalesce(p.amount, 0) as captured_amount,
        coalesce(p.processor_fee, 0) as processor_fee,
        coalesce(i.total_incentive_amount, 0) as incentive_amount,

        -- Net revenue per trip (local currency)
        case
            when t.is_revenue_eligible then coalesce(p.amount, 0) - coalesce(p.processor_fee, 0)
            when t.has_cancellation_fee then coalesce(p.amount, 0) - coalesce(p.processor_fee, 0)
            else 0
        end as net_revenue_local,

        -- USD conversion
        coalesce(cr.exchange_rate, 1.0) as exchange_rate,
        t.gross_fare * coalesce(cr.exchange_rate, 1.0) as gross_fare_usd,
        coalesce(p.amount, 0) * coalesce(cr.exchange_rate, 1.0) as captured_amount_usd,
        coalesce(p.processor_fee, 0) * coalesce(cr.exchange_rate, 1.0) as processor_fee_usd,
        coalesce(i.total_incentive_amount, 0) * coalesce(cr.exchange_rate, 1.0) as incentive_amount_usd,

        -- Flags
        case when p.payment_id is not null then true else false end as has_captured_payment,
        coalesce(p.has_duplicate_captures, false) as has_duplicate_captures,
        coalesce(i.is_multi_campaign_trip, false) as is_multi_campaign_trip,
        coalesce(i.incentive_line_count, 0) as incentive_line_count,
        p.payment_method,

        -- Timestamps
        t.requested_at,
        t.accepted_at,
        t.started_at,
        t.ended_at,
        p.captured_at

    from trips t
    left join payments p on t.trip_id = p.trip_id
    left join incentives i on t.trip_id = i.trip_id
    left join currency_rates cr on t.currency = cr.from_currency
)

select * from joined