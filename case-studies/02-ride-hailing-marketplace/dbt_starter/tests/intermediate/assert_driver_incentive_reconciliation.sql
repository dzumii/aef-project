-- Severity: ERROR — Driver Ops requirement: paid totals must match raw ledger
-- Action: block pipeline, do not publish driver mart until resolved
select
    d.driver_id,
    d.total_incentive_paid as mart_total,
    r.raw_total,
    abs(d.total_incentive_paid - r.raw_total) as diff
from {{ ref('int_driver_metrics') }} d
join (
    select driver_id, sum(bonus_amount) as raw_total
    from {{ source('raw', 'raw_driver_incentives') }}
    group by driver_id
) r on d.driver_id = r.driver_id
where abs(d.total_incentive_paid - r.raw_total) > 0.01