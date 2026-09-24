-- Friday cleaning schedule based on recent usage time and frequency.

create table if not exists public.cleaning_assignments (
  id uuid primary key default gen_random_uuid(),
  friday_date date not null unique,
  assignee_id uuid references public.profiles(id) on delete set null,
  assignee_name text not null default '',
  assignment_source text not null default 'auto'
    check (assignment_source in ('auto', 'manual')),
  score_minutes integer not null default 0,
  reservation_count integer not null default 0,
  note text not null default '',
  assigned_by uuid references auth.users(id) on delete set null,
  assigned_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists cleaning_assignments_friday_idx
  on public.cleaning_assignments(friday_date);

drop trigger if exists cleaning_assignments_touch_updated_at on public.cleaning_assignments;
create trigger cleaning_assignments_touch_updated_at
before update on public.cleaning_assignments
for each row execute function public.touch_updated_at();

create or replace function public.ensure_cleaning_assignment(p_friday date)
returns public.cleaning_assignments
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  v_assignment public.cleaning_assignments;
  v_week_start date := p_friday - 7;
  v_week_end date := p_friday;
  v_user_id uuid := auth.uid();
begin
  if v_user_id is null then
    raise exception 'not authenticated';
  end if;

  if not public.is_approved() and not public.is_admin() then
    raise exception 'not approved';
  end if;

  if extract(isodow from p_friday) <> 5 then
    raise exception '卫生安排日期必须是周五';
  end if;

  select * into v_assignment
  from public.cleaning_assignments
  where friday_date = p_friday;

  if v_assignment.id is not null then
    return v_assignment;
  end if;

  with usage_stats as (
    select
      p.id,
      p.display_name,
      p.email,
      p.created_at,
      count(r.id)::integer as reservation_count,
      coalesce(
        sum(
          case
            when us.actual_end is not null
              then extract(epoch from (us.actual_end - us.actual_start)) / 60
            else extract(epoch from (r.end_at - r.start_at)) / 60
          end
        ),
        0
      )::integer as score_minutes
    from public.profiles p
    left join public.reservations r
      on r.user_id = p.id
      and r.status in ('booked', 'in_use', 'completed')
      and (r.start_at at time zone 'Asia/Shanghai')::date >= v_week_start
      and (r.start_at at time zone 'Asia/Shanghai')::date < v_week_end
    left join public.usage_sessions us
      on us.reservation_id = r.id
    where p.status = 'approved'
    group by p.id, p.display_name, p.email, p.created_at
  ),
  last_cleaned as (
    select assignee_id, max(friday_date) as last_clean_date
    from public.cleaning_assignments
    where friday_date < p_friday
    group by assignee_id
  ),
  ranked as (
    select
      u.id,
      u.display_name,
      u.email,
      u.score_minutes,
      u.reservation_count,
      u.score_minutes + (u.reservation_count * 30) as weighted_score,
      l.last_clean_date
    from usage_stats u
    left join last_cleaned l on l.assignee_id = u.id
  )
  insert into public.cleaning_assignments (
    friday_date,
    assignee_id,
    assignee_name,
    assignment_source,
    score_minutes,
    reservation_count,
    note,
    assigned_by,
    assigned_at
  )
  select
    p_friday,
    id,
    coalesce(nullif(display_name, ''), email, '未命名成员'),
    'auto',
    score_minutes,
    reservation_count,
    '',
    v_user_id,
    now()
  from ranked
  order by
    weighted_score desc,
    last_clean_date asc nulls first,
    created_at asc
  limit 1
  on conflict (friday_date) do nothing
  returning * into v_assignment;

  if v_assignment.id is null then
    select * into v_assignment
    from public.cleaning_assignments
    where friday_date = p_friday;
  end if;

  if v_assignment.id is null then
    raise exception '没有可安排卫生的成员';
  end if;

  return v_assignment;
end;
$$;

create or replace function public.set_cleaning_assignment(
  p_friday date,
  p_assignee_id uuid,
  p_note text default ''
)
returns public.cleaning_assignments
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  v_assignment public.cleaning_assignments;
  v_name text;
  v_user_id uuid := auth.uid();
begin
  if not public.is_admin() then
    raise exception 'not authorized';
  end if;

  if extract(isodow from p_friday) <> 5 then
    raise exception '卫生安排日期必须是周五';
  end if;

  select coalesce(nullif(display_name, ''), email, '未命名成员')
  into v_name
  from public.profiles
  where id = p_assignee_id and status = 'approved';

  if v_name is null then
    raise exception '所选成员不存在或尚未授权';
  end if;

  insert into public.cleaning_assignments (
    friday_date,
    assignee_id,
    assignee_name,
    assignment_source,
    score_minutes,
    reservation_count,
    note,
    assigned_by,
    assigned_at
  )
  values (
    p_friday,
    p_assignee_id,
    v_name,
    'manual',
    0,
    0,
    coalesce(p_note, ''),
    v_user_id,
    now()
  )
  on conflict (friday_date) do update set
    assignee_id = excluded.assignee_id,
    assignee_name = excluded.assignee_name,
    assignment_source = 'manual',
    note = excluded.note,
    assigned_by = v_user_id,
    assigned_at = now()
  returning * into v_assignment;

  return v_assignment;
end;
$$;

alter table public.cleaning_assignments enable row level security;

drop policy if exists cleaning_assignments_select on public.cleaning_assignments;
create policy cleaning_assignments_select on public.cleaning_assignments
for select to authenticated
using (public.is_approved() or public.is_admin());

grant select on public.cleaning_assignments to authenticated;
grant execute on function public.ensure_cleaning_assignment(date) to authenticated;
grant execute on function public.set_cleaning_assignment(date, uuid, text) to authenticated;
