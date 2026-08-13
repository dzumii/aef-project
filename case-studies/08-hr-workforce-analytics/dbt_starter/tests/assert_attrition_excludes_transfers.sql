-- The reconciled exit count should never include transfers
-- Verify by checking that no person in exits has ONLY transferred records (no termination)
select f.person_id
from {{ ref('fct_workforce') }} f
where f.is_currently_active = 0
  and f.last_termination_date is null
  and not exists (
    select 1 from {{ ref('int_employment_stints') }} s
    where s.person_id = f.person_id
      and s.employment_status = 'terminated'
  )