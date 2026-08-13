-- Severity: WARN — captured amount should not exceed gross fare (possible overcharge)
-- Action: log, flag for manual review
select trip_id, gross_fare, captured_amount
from {{ ref('int_trips_enriched') }}
where captured_amount > gross_fare * 1.1
  and is_completed = true