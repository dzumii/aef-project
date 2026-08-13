with source as (
    select * from {{ source('raw', 'raw_drivers') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by driver_id
            order by onboarded_at desc
        ) as rn,
        min(onboarded_at) over (partition by driver_id) as first_onboarded_at,
        max(onboarded_at) over (partition by driver_id) as last_onboarded_at,
        count(*) over (partition by driver_id) as row_count
    from source
),

staged as (
    select
        driver_id,
        home_city,
        driver_status,
        vehicle_class,
        rating,
        first_onboarded_at,
        last_onboarded_at,
        case when row_count > 1 then true else false end as is_reonboarded
    from ranked
    where rn = 1
)

select * from staged