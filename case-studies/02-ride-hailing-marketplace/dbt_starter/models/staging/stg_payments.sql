with source as (
    select * from {{ source('raw', 'raw_payments') }}
),

captured_only as (
    select
        *,
        row_number() over (
            partition by trip_id
            order by captured_at asc
        ) as capture_rank,
        count(*) over (partition by trip_id) as captures_per_trip
    from source
    where payment_status = 'captured'
),

staged as (
    select
        payment_id,
        trip_id,
        rider_id,
        payment_status,
        amount,
        currency,
        payment_method,
        processor_fee,
        attempted_at,
        captured_at,
        case when captures_per_trip > 1 then true else false end as has_duplicate_captures,
        capture_rank
    from captured_only
    where capture_rank = 1
)

select * from staged