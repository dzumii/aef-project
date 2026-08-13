-- A transfer continuation should belong to the same stint as its predecessor
select
    cur.employee_id,
    cur.stint_id as cur_stint,
    pred.stint_id as pred_stint
from {{ ref('int_employment_stints') }} cur
join {{ ref('int_employment_stints') }} pred
    on cur.prior_employee_id = pred.employee_id
where cur.record_type = 'transfer_continuation'
  and cur.stint_id != pred.stint_id