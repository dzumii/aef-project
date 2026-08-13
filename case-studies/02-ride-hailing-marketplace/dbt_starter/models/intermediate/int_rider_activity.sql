with riders as (
    select * from {{ ref('stg_riders') }}
),

trips as (
    select * from {{ ref('int_trips_enriched') }}
),

-- Reference date: latest trip in dataset (for reproducibility)
ref_date as (
    select max(requested_at)::date as reference_date
    from trips
),

rider_trip_metrics as (
    select
        t.rider_id,
        count(*) as total_trips_requested,
        count(case when t.is_completed then t.trip_id end) as completed_trips,
        count(case when t.is_revenue_eligible then t.trip_id end) as completed_nonfraud_trips,
        count(case when t.trip_status = 'cancelled' then t.trip_id end) as cancelled_trips,
        count(case when t.is_fraud_flagged then t.trip_id end) as fraud_trips,

        sum(t.gross_fare_usd) as total_gross_fare_usd,
        sum(case when t.is_revenue_eligible then t.captured_amount_usd else 0 end) as total_captured_usd,

        min(t.requested_at) as first_trip_at,
        max(t.requested_at) as last_trip_at,

        -- Trailing window flags (against reference date)
        count(case
            when t.is_revenue_eligible
                and t.requested_at >= dateadd('day', -30, (select reference_date from ref_date))
            then t.trip_id
        end) as completed_nonfraud_30d,

        count(case
            when t.is_revenue_eligible
                and t.requested_at >= dateadd('day', -90, (select reference_date from ref_date))
            then t.trip_id
        end) as completed_nonfraud_90d,

        count(case
            when t.requested_at >= dateadd('day', -30, (select reference_date from ref_date))
            then t.trip_id
        end) as any_trip_30d

    from trips t
    group by t.rider_id
),

final as (
    select
        r.rider_id,
        r.home_city,
        r.account_status,
        r.signup_at,
        r.is_referred,

        -- Trip metrics
        coalesce(m.total_trips_requested, 0) as total_trips_requested,
        coalesce(m.completed_trips, 0) as completed_trips,
        coalesce(m.completed_nonfraud_trips, 0) as completed_nonfraud_trips,
        coalesce(m.cancelled_trips, 0) as cancelled_trips,
        coalesce(m.fraud_trips, 0) as fraud_trips,
        coalesce(m.total_gross_fare_usd, 0) as total_gross_fare_usd,
        coalesce(m.total_captured_usd, 0) as total_captured_usd,
        m.first_trip_at,
        m.last_trip_at,

        -- Active rider definitions (Assumption: multi-definition model)
        -- Definition 1: CRM flag (vanity)
        case when r.account_status = 'active' then true else false end as is_active_account,

        -- Definition 2: Completed non-fraud trip in trailing 30d (Growth)
        case when coalesce(m.completed_nonfraud_30d, 0) > 0 then true else false end as is_active_30d,

        -- Definition 3: Completed non-fraud trip in trailing 90d (Finance/Investors)
        case when coalesce(m.completed_nonfraud_90d, 0) > 0 then true else false end as is_active_90d,

        -- Definition 4: Any trip requested in trailing 30d (Ops/Engagement)
        case when coalesce(m.any_trip_30d, 0) > 0 then true else false end as is_active_any_trip_30d

    from riders r
    left join rider_trip_metrics m on r.rider_id = m.rider_id
)

select * from final
