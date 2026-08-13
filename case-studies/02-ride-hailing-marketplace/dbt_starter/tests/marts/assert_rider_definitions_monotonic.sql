-- Severity: ERROR — active_30d <= active_90d <= active_account (logical ordering)
-- Action: block pipeline, logic error in model
with counts as (
    select
        count(case when is_active_30d then 1 end) as active_30d,
        count(case when is_active_90d then 1 end) as active_90d,
        count(case when is_active_account then 1 end) as active_account
    from {{ ref('mart_riders') }}
)
select *
from counts
where active_30d > active_90d