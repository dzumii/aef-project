with trips as (
    select * from {{ ref('int_trips_enriched') }}
),

bridge as (
    select
        -- Line 1: Growth GMV
        sum(case when is_completed then gross_fare_usd else 0 end) as gmv_usd,

        -- Line 2: Cancellation fee revenue
        sum(case when has_cancellation_fee then captured_amount_usd else 0 end) as cancellation_fee_revenue_usd,

        -- Line 3: Gross platform revenue
        sum(case when is_completed then gross_fare_usd else 0 end)
          + sum(case when has_cancellation_fee then captured_amount_usd else 0 end) as gross_revenue_usd,

        -- Adjustments
        -- Line 4: Fraud reversals (completed + fraud flagged, captured amount)
        sum(case when is_fraud_flagged and has_captured_payment then captured_amount_usd else 0 end) as fraud_reversals_usd,

        -- Line 5: Uncollected fares (completed, non-fraud, no capture)
        sum(case when is_revenue_eligible and not has_captured_payment then gross_fare_usd else 0 end) as uncollected_fares_usd,

        -- Line 6: Processor fees on revenue-eligible captured payments
        sum(case when is_revenue_eligible and has_captured_payment then processor_fee_usd else 0 end) as processor_fees_usd,

        -- Line 7: Net collected revenue (Finance's number)
        sum(case when is_revenue_eligible and has_captured_payment
            then captured_amount_usd - processor_fee_usd else 0 end) as net_revenue_usd,

        -- Memo items
        sum(incentive_amount_usd) as total_incentive_spend_usd,

        sum(case when is_fraud_flagged then incentive_amount_usd else 0 end) as incentive_on_fraud_usd,

        -- Gap calculation
        sum(case when is_completed then gross_fare_usd else 0 end)
          - sum(case when is_revenue_eligible and has_captured_payment
                then captured_amount_usd - processor_fee_usd else 0 end) as total_gap_usd

    from trips
),

final as (
    select
        gmv_usd,
        cancellation_fee_revenue_usd,
        gross_revenue_usd,

        fraud_reversals_usd,
        uncollected_fares_usd,
        processor_fees_usd,

        net_revenue_usd,

        -- Gap breakdown
        total_gap_usd,
        round(fraud_reversals_usd / nullif(total_gap_usd, 0), 4) as fraud_pct_of_gap,
        round(uncollected_fares_usd / nullif(total_gap_usd, 0), 4) as uncollected_pct_of_gap,
        round(processor_fees_usd / nullif(total_gap_usd, 0), 4) as fees_pct_of_gap,

        -- Overall gap rate
        round(total_gap_usd / nullif(gmv_usd, 0), 4) as gap_rate,

        -- Memo
        total_incentive_spend_usd,
        incentive_on_fraud_usd

    from bridge
)

select * from final