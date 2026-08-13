with trips as (
    select * from {{ ref('int_trips_enriched') }}
),

monthly_kpis as (
    select
        date_trunc('month', requested_at)::date as report_month,

        -- GMV: all completed trips (incl fraud) — Growth's number
        sum(case when is_completed then gross_fare_usd else 0 end) as gmv_usd,

        -- Cancellation fee revenue
        sum(case when has_cancellation_fee then captured_amount_usd else 0 end) as cancellation_fee_revenue_usd,

        -- Gross platform revenue (GMV + cancellation fees)
        sum(case when is_completed then gross_fare_usd else 0 end)
          + sum(case when has_cancellation_fee then captured_amount_usd else 0 end) as gross_revenue_usd,

        -- Net revenue: non-fraud completed with captured payment, minus processor fees
        sum(case when is_revenue_eligible then captured_amount_usd - processor_fee_usd else 0 end) as net_revenue_usd,

        -- Fraud amount (captured before flag — will be reversed)
        sum(case when is_fraud_flagged then captured_amount_usd else 0 end) as fraud_revenue_usd,

        -- Uncollected (completed non-fraud, no capture)
        sum(case when is_revenue_eligible and not has_captured_payment then gross_fare_usd else 0 end) as uncollected_fare_usd,

        -- Processor fees
        sum(case when is_revenue_eligible then processor_fee_usd else 0 end) as processor_fees_usd,

        -- Incentive spend
        sum(incentive_amount_usd) as incentive_spend_usd,

        -- Trip counts
        count(*) as total_trip_requests,
        count(case when is_completed then trip_id end) as completed_trips,
        count(case when trip_status = 'cancelled' then trip_id end) as cancelled_trips,
        count(case when is_fraud_flagged then trip_id end) as fraud_trips,
        count(case when is_revenue_eligible then trip_id end) as revenue_eligible_trips,

        -- Rates
        round(count(case when trip_status = 'cancelled' then trip_id end)::float
              / count(*), 4) as cancellation_rate,

        round(count(case when is_fraud_flagged then trip_id end)::float
              / nullif(count(case when is_completed then trip_id end), 0), 4) as fraud_rate,

        -- Take rate: net revenue / GMV
        case
            when sum(case when is_completed then gross_fare_usd else 0 end) > 0
            then round(
                sum(case when is_revenue_eligible then captured_amount_usd - processor_fee_usd else 0 end)::float
                / sum(case when is_completed then gross_fare_usd else 0 end), 4)
            else 0
        end as take_rate,

        -- Active riders/drivers this month
        count(distinct rider_id) as active_riders,
        count(distinct case when is_completed then driver_id end) as active_drivers

    from trips
    group by date_trunc('month', requested_at)::date
)

select * from monthly_kpis
order by report_month