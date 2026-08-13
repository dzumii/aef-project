-- Severity: WARN — all 12 months should be present for full-year reporting
-- Action: alert if a month is missing (late data arrival)
select count(distinct report_month) as month_count
from {{ ref('mart_marketplace_kpis') }}
having count(distinct report_month) < 12