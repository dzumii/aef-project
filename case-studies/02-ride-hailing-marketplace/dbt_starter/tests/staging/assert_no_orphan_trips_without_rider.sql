-- Severity: ERROR — trips must reference valid riders
-- Action: block pipeline, escalate to data engineering
select trip_id, rider_id
from {{ ref('stg_trips') }}
where rider_id not in (select rider_id from {{ ref('stg_riders') }})