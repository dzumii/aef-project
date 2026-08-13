-- Severity: WARN — gap should be 8-12% per historical norm
-- Action: alert Finance if outside bounds, likely source data shift
select gap_rate
from {{ ref('mart_reconciliation') }}
where gap_rate < 0.05 or gap_rate > 0.20