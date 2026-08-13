with drivers as (
    select * from {{ ref('stg_drivers') }}
),

trips as (
    select * from {{ ref('int_trips_enriched') }}
),

incentives_raw as (
    -- Use staged incentives directly for driver-level totals (Assumption 5: paid is paid)
    select
        driver_id,
        sum(bonus_amount) as total_incentive_paid,
        count(*) as total_incentive_lines,
        count(distinct trip_id) as incentivized_trips,
        count(distinct campaign) as campaigns_participated
    from {{ ref('stg_driver_incentives') }}
    group by driver_id
),

trip_metrics as (
    select
        driver_id,
        count(*) as total_trips_assigned,
        count(case when is_completed then trip_id end) as completed_trips,
        count(case when trip_status = 'cancelled' then trip_id end) as cancelled_trips,
        count(case when is_fraud_flagged then trip_id end) as fraud_flagged_trips,
        count(case when is_revenue_eligible then trip_id end) as revenue_eligible_trips,

        -- Earnings (USD)
        sum(case when is_completed then gross_fare_usd else 0 end) as gross_earnings_usd,
        sum(case when is_revenue_eligible then captured_amount_usd else 0 end) as net_captured_usd,

        -- Activity timestamps
        min(requested_at) as first_trip_at,
        max(requested_at) as last_trip_at,

        -- City and product mix
        count(distinct city) as cities_operated,
        count(distinct product) as products_served
    from trips
    where driver_id is not null
    group by driver_id
),

final as (
    select
        d.driver_id,
        d.home_city,
        d.driver_status,
        d.vehicle_class,
        d.rating,
        d.first_onboarded_at,
        d.last_onboarded_at,
        d.is_reonboarded,

        -- Trip metrics
        coalesce(tm.total_trips_assigned, 0) as total_trips_assigned,
        coalesce(tm.completed_trips, 0) as completed_trips,
        coalesce(tm.cancelled_trips, 0) as cancelled_trips,
        coalesce(tm.fraud_flagged_trips, 0) as fraud_flagged_trips,
        coalesce(tm.revenue_eligible_trips, 0) as revenue_eligible_trips,

        -- Rates
        case
            when coalesce(tm.total_trips_assigned, 0) > 0
            then round(tm.completed_trips::float / tm.total_trips_assigned, 4)
            else 0
        end as completion_rate,

        case
            when coalesce(tm.completed_trips, 0) > 0
            then round(tm.fraud_flagged_trips::float / tm.completed_trips, 4)
            else 0
        end as fraud_rate,

        -- Earnings
        coalesce(tm.gross_earnings_usd, 0) as gross_earnings_usd,
        coalesce(tm.net_captured_usd, 0) as net_captured_usd,

        -- Incentives (from raw ledger — sacred per Driver Ops)
        coalesce(ir.total_incentive_paid, 0) as total_incentive_paid,
        coalesce(ir.total_incentive_lines, 0) as total_incentive_lines,
        coalesce(ir.incentivized_trips, 0) as incentivized_trips,
        coalesce(ir.campaigns_participated, 0) as campaigns_participated,

        -- Activity
        tm.first_trip_at,
        tm.last_trip_at,
        tm.cities_operated,
        tm.products_served

    from drivers d
    left join trip_metrics tm on d.driver_id = tm.driver_id
    left join incentives_raw ir on d.driver_id = ir.driver_id
)

select * from final