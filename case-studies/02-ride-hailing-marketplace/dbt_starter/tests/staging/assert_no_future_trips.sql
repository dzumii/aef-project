-- Severity: WARN — trips with future timestamps indicate clock skew
-- Action: log and continue, escalate if >0.1% of trips
select trip_id, requested_at
from {{ ref('stg_trips') }}
where requested_at > current_timestamp()