-- After dedup, no employee should have two reviews for the same period
select
    employee_id,
    review_period,
    count(*) as cnt
from {{ ref('stg_performance_reviews') }}
group by 1, 2
having count(*) > 1