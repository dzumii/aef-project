with rider_activity as (
    select * from {{ ref('int_rider_activity') }}
),

final as (
    select
        rider_id,
        home_city,
        account_status,
        signup_at,
        is_referred,

        -- Trip metrics
        total_trips_requested,
        completed_trips,
        completed_nonfraud_trips,
        cancelled_trips,
        fraud_trips,

        -- Spend
        total_gross_fare_usd,
        total_captured_usd,

        -- Activity timestamps
        first_trip_at,
        last_trip_at,

        -- Multi-definition active rider flags
        is_active_account,
        is_active_30d,
        is_active_90d,
        is_active_any_trip_30d,

        -- Derived
        case
            when total_trips_requested > 0
            then round(completed_nonfraud_trips::float / total_trips_requested, 4)
            else 0
        end as completion_rate,

        case
            when completed_trips > 0
            then round(total_gross_fare_usd / completed_trips, 2)
            else 0
        end as avg_fare_per_trip_usd,

        case
            when total_trips_requested = 0 then 'never_rode'
            when is_active_30d then 'active'
            when is_active_90d then 'lapsing'
            else 'churned'
        end as lifecycle_stage

    from rider_activity
)

select * from final