-- Severity: ERROR — fares cannot be negative
-- Action: block pipeline, investigate source
select trip_id, gross_fare
from {{ ref('stg_trips') }}
where gross_fare < 0