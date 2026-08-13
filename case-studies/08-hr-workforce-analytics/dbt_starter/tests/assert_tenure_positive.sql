-- Active employees must have positive tenure
select person_id, tenure_total_service_days
from {{ ref('fct_workforce') }}
where is_currently_active = 1
  and tenure_total_service_days <= 0