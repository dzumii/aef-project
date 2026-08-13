with source as (
    select * from {{ source('raw', 'raw_departments') }}
)

select
    department_id,
    department_code,
    department_name,
    division,
    cost_center
from source