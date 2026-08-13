with source as (
    select * from {{ source('raw', 'raw_trips') }}
),

staged as (
    select
        trip_id,
        rider_id,
        driver_id,
        city,
        product,
        trip_status,
        cancel_reason,
        gross_fare,
        surge_multiplier,
        currency,
        is_fraud_flagged,

        -- Cancellation classification (Assumption 6)
        case
            when trip_status = 'completed' and is_fraud_flagged = false then 'completed'
            when trip_status = 'completed' and is_fraud_flagged = true then 'completed_fraud'
            when trip_status = 'cancelled' and cancel_reason = 'no_driver_found' then 'cancelled_no_match'
            when trip_status = 'cancelled' then 'cancelled_billed'
        end as trip_classification,

        -- Revenue eligibility flags
        case
            when trip_status = 'completed' then true
            else false
        end as is_completed,

        case
            when trip_status = 'completed' and is_fraud_flagged = false then true
            else false
        end as is_revenue_eligible,

        case
            when trip_status = 'cancelled' and cancel_reason != 'no_driver_found' then true
            else false
        end as has_cancellation_fee,

        -- Coordinates
        pickup_lat,
        pickup_lon,
        dropoff_lat,
        dropoff_lon,

        -- Timestamps
        requested_at,
        accepted_at,
        started_at,
        ended_at
    from source
)

select * from staged