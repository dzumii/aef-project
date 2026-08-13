-- fct_workforce must be exactly one row per person
select
    person_id,
    count(*) as row_count
from {{ ref('fct_workforce') }}
group by 1
having count(*) > 1