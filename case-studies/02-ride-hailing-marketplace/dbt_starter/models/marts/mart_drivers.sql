with driver_metrics as (
    select * from {{ ref('int_driver_metrics') }}
),

-- Fraud incentive breakdown per driver
fraud_incentives as (
    select
        i.driver_id,
        sum(i.bonus_amount) as incentive_on_fraud_trips
    from {{ ref('stg_driver_incentives') }} i
    inner join {{ ref('stg_trips') }} t on i.trip_id = t.trip_id
    where t.is_fraud_flagged = true
    group by i.driver_id
),

final as (
    select
        dm.driver_id,
        dm.home_city,
        dm.driver_status,
        dm.vehicle_class,
        dm.rating,
        dm.first_onboarded_at,
        dm.last_onboarded_at,
        dm.is_reonboarded,

        -- Trip performance
        dm.total_trips_assigned,
        dm.completed_trips,
        dm.cancelled_trips,
        dm.fraud_flagged_trips,
        dm.revenue_eligible_trips,
        dm.completion_rate,
        dm.fraud_rate,

        -- Earnings (USD)
        dm.gross_earnings_usd,
        dm.net_captured_usd,

        -- Incentives (sacred — reconciles to raw ledger)
        dm.total_incentive_paid,
        dm.total_incentive_lines,
        dm.incentivized_trips,
        dm.campaigns_participated,
        coalesce(fi.incentive_on_fraud_trips, 0) as incentive_on_fraud_trips,

        -- Activity
        dm.first_trip_at,
        dm.last_trip_at,
        dm.cities_operated,
        dm.products_served,

        -- Derived
        case
            when dm.completed_trips > 0
            then round(dm.gross_earnings_usd / dm.completed_trips, 2)
            else 0
        end as avg_fare_per_trip_usd,

        case
            when dm.completed_trips > 0
            then round(dm.total_incentive_paid / dm.completed_trips, 2)
            else 0
        end as avg_incentive_per_trip

    from driver_metrics dm
    left join fraud_incentives fi on dm.driver_id = fi.driver_id
)

select * from final