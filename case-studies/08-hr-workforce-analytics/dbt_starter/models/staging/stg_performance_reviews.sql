with source as (
    select * from {{ source('raw', 'raw_performance_reviews') }}
),

-- Deduplicate: keep latest review_date per employee-period (ties broken by review_id)
ranked as (
    select
        *,
        row_number() over (
            partition by employee_id, review_period
            order by review_date desc nulls last, review_id desc
        ) as _row_num
    from source
),

cleaned as (
    select
        review_id,
        employee_id,
        person_id,
        review_period,
        rating,
        review_score,
        reviewer_id,
        review_date::date as review_date,
        case when review_date is null then true else false end as is_missing_review_date,
        case when _row_num > 1 then true else false end as is_duplicate_submission

    from ranked
)

select * from cleaned
where not is_duplicate_submission