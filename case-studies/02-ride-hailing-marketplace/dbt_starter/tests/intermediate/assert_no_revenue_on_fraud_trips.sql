-- Severity: ERROR — net_revenue must be 0 for fraud trips per Assumption 3
-- Action: block pipeline
select trip_id, net_revenue_local, is_fraud_flagged
from {{ ref('int_trips_enriched') }}
where is_fraud_flagged = true
  and net_revenue_local > 0