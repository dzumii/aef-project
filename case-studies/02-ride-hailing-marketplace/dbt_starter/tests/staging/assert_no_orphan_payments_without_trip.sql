-- Severity: ERROR — payments must reference valid trips
-- Action: block pipeline
select payment_id, trip_id
from {{ ref('stg_payments') }}
where trip_id not in (select trip_id from {{ ref('stg_trips') }})