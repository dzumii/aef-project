-- Department headcounts must sum to total active persons
with dept_total as (
    select sum(active_headcount) as dept_sum
    from {{ ref('dim_department') }}
),
person_total as (
    select count(*) as person_count
    from {{ ref('fct_workforce') }}
    where is_currently_active = 1
)
select
    d.dept_sum,
    p.person_count
from dept_total d, person_total p
where d.dept_sum != p.person_count