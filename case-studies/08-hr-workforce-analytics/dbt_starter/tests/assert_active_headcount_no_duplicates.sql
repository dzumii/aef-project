-- No person should have more than one active record after dedup
select
    person_id,
    count(*) as active_records
from {{ ref('stg_employees') }}
where employment_status = 'active'
group by 1
having count(*) > 1