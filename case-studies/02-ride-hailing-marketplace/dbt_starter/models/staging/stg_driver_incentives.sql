with source as (
    select * from {{ source('raw', 'raw_driver_incentives') }}
),

staged as (
    select
        incentive_id,
        driver_id,
        trip_id,
        campaign,
        bonus_amount,
        currency,
        earned_at,
        paid_at,
        count(*) over (partition by trip_id) as incentives_per_trip,
        case
            when count(*) over (partition by trip_id) > 1 then true
            else false
        end as is_multi_campaign_trip
    from source
)

select * from staged