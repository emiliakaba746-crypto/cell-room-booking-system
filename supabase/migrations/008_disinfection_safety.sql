-- Ozone/UV disinfection logging and room-safety enforcement.

create table if not exists public.disinfection_sessions (
  id uuid primary key default gen_random_uuid(),
  method text not null default 'uv_ozone'
    check (method in ('uv', 'ozone', 'uv_ozone')),
  planned_duration_minutes integer not null default 30
    check (planned_duration_minutes between 1 and 60),
  start_at timestamptz not null default now(),
  expected_end_at timestamptz not null,
  ended_at timestamptz,
  ventilation_started_at timestamptz,
  ventilation_minutes integer not null default 30
    check (ventilation_minutes between 30 and 120),
  safe_at timestamptz,
  status text not null default 'active'
    check (status in ('active', 'venting', 'safe', 'cancelled')),
  started_by uuid references auth.users(id) on delete set null,
  started_by_name text not null default '',
  ended_by uuid references auth.users(id) on delete set null,
  ended_by_name text not null default '',
  notes text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists disinfection_sessions_start_idx
  on public.disinfection_sessions(start_at desc);
create index if not exists disinfection_sessions_status_idx
  on public.disinfection_sessions(status, safe_at);

drop trigger if exists disinfection_sessions_touch_updated_at on public.disinfection_sessions;
create trigger disinfection_sessions_touch_updated_at
before update on public.disinfection_sessions
for each row execute function public.touch_updated_at();

create or replace function public.room_safety_state()
returns text
language plpgsql
stable
security definer
set search_path = public, auth
as $$
declare
  v_session public.disinfection_sessions%rowtype;
begin
  select * into v_session
  from public.disinfection_sessions
  where status <> 'cancelled'
  order by created_at desc
  limit 1;

  if v_session.id is null or v_session.status = 'safe' then
    return 'safe';
  end if;

  if v_session.status = 'active' then
    if now() < v_session.expected_end_at then
      return 'disinfecting';
    end if;
    return 'awaiting_ventilation';
  end if;

  if v_session.status = 'venting' then
    if v_session.safe_at is not null and now() >= v_session.safe_at then
      return 'safe';
    end if;
    return 'venting';
  end if;

  return 'safe';
end;
$$;

create or replace function public.start_disinfection(
  p_method text default 'uv_ozone',
  p_duration_minutes integer default 30,
  p_notes text default ''
)
returns public.disinfection_sessions
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  v_user_id uuid := auth.uid();
  v_user_name text;
  v_session public.disinfection_sessions;
begin
  if not public.is_approved() and not public.is_admin() then
    raise exception 'not approved';
  end if;

  if p_method not in ('uv', 'ozone', 'uv_ozone') then
    raise exception '消毒方式无效';
  end if;

  if p_duration_minutes < 1 or p_duration_minutes > 60 then
    raise exception '单次臭氧/紫外消毒不能超过 60 分钟';
  end if;

  if exists (
    select 1 from public.reservations
    where status = 'in_use'
  ) then
    raise exception '当前有预约正在使用，禁止开启臭氧/紫外消毒';
  end if;

  update public.disinfection_sessions
  set status = 'safe'
  where status = 'venting'
    and safe_at is not null
    and now() >= safe_at;

  if public.room_safety_state() <> 'safe' then
    raise exception '已有臭氧/紫外消毒记录尚未完成通风，请先结束并通风至安全时间';
  end if;

  select coalesce(nullif(display_name, ''), email, '未命名成员')
  into v_user_name
  from public.profiles
  where id = v_user_id;

  insert into public.disinfection_sessions (
    method,
    planned_duration_minutes,
    start_at,
    expected_end_at,
    status,
    started_by,
    started_by_name,
    notes
  ) values (
    p_method,
    p_duration_minutes,
    now(),
    now() + make_interval(mins => p_duration_minutes),
    'active',
    v_user_id,
    coalesce(v_user_name, '未命名成员'),
    coalesce(p_notes, '')
  ) returning * into v_session;

  return v_session;
end;
$$;

create or replace function public.finish_disinfection(
  p_session_id uuid,
  p_ventilation_minutes integer default 30
)
returns public.disinfection_sessions
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  v_user_id uuid := auth.uid();
  v_user_name text;
  v_session public.disinfection_sessions;
begin
  if not public.is_approved() and not public.is_admin() then
    raise exception 'not approved';
  end if;

  if p_ventilation_minutes < 30 or p_ventilation_minutes > 120 then
    raise exception '通风时间必须为 30 到 120 分钟';
  end if;

  select * into v_session
  from public.disinfection_sessions
  where id = p_session_id
  for update;

  if v_session.id is null then
    raise exception '消毒记录不存在';
  end if;

  if v_session.status <> 'active' then
    raise exception '当前记录不是进行中的消毒';
  end if;

  select coalesce(nullif(display_name, ''), email, '未命名成员')
  into v_user_name
  from public.profiles
  where id = v_user_id;

  update public.disinfection_sessions
  set status = 'venting',
      ended_at = now(),
      ventilation_started_at = now(),
      ventilation_minutes = p_ventilation_minutes,
      safe_at = now() + make_interval(mins => p_ventilation_minutes),
      ended_by = v_user_id,
      ended_by_name = coalesce(v_user_name, '未命名成员')
  where id = p_session_id
  returning * into v_session;

  return v_session;
end;
$$;

create or replace function public.confirm_disinfection_safe(p_session_id uuid)
returns public.disinfection_sessions
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  v_session public.disinfection_sessions;
begin
  if not public.is_approved() and not public.is_admin() then
    raise exception 'not approved';
  end if;

  select * into v_session
  from public.disinfection_sessions
  where id = p_session_id
  for update;

  if v_session.id is null then
    raise exception '消毒记录不存在';
  end if;

  if v_session.status <> 'venting' then
    raise exception '当前记录不在通风阶段';
  end if;

  if v_session.safe_at is null or now() < v_session.safe_at then
    raise exception '通风时间尚未达到，禁止提前确认安全';
  end if;

  update public.disinfection_sessions
  set status = 'safe'
  where id = p_session_id
  returning * into v_session;

  return v_session;
end;
$$;

create or replace function public.delete_disinfection_session(p_session_id uuid)
returns void
language plpgsql
security definer
set search_path = public, auth
as $$
begin
  if not public.is_admin() then
    raise exception 'not authorized';
  end if;

  delete from public.disinfection_sessions where id = p_session_id;
  if not found then
    raise exception '消毒记录不存在';
  end if;
end;
$$;

-- Recreate start_usage with a hard room-safety gate.
create or replace function public.start_usage(p_booking_id uuid)
returns void
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  v_booking public.reservations%rowtype;
  v_user_id uuid := auth.uid();
begin
  if public.room_safety_state() <> 'safe' then
    raise exception '当前臭氧/紫外消毒尚未完成通风，禁止开始使用';
  end if;

  select * into v_booking from public.reservations where id = p_booking_id for update;
  if v_booking.id is null then
    raise exception '预约不存在';
  end if;
  if v_booking.user_id <> v_user_id and not public.is_admin() then
    raise exception 'not authorized';
  end if;
  if v_booking.status <> 'booked' then
    raise exception '只有已预约状态可以开始使用';
  end if;
  if now() < v_booking.start_at - interval '15 minutes' then
    raise exception '尚未到预约开始时间，最早可提前 15 分钟开始';
  end if;
  update public.reservations set status = 'in_use' where id = p_booking_id;
  insert into public.usage_sessions (reservation_id, actual_start)
  values (p_booking_id, now())
  on conflict (reservation_id) do update set actual_start = excluded.actual_start, actual_end = null;
end;
$$;

alter table public.disinfection_sessions enable row level security;

drop policy if exists disinfection_sessions_select on public.disinfection_sessions;
create policy disinfection_sessions_select on public.disinfection_sessions
for select to authenticated
using (public.is_approved() or public.is_admin());

grant select on public.disinfection_sessions to authenticated;
grant execute on function public.room_safety_state() to authenticated;
grant execute on function public.start_disinfection(text, integer, text) to authenticated;
grant execute on function public.finish_disinfection(uuid, integer) to authenticated;
grant execute on function public.confirm_disinfection_safe(uuid) to authenticated;
grant execute on function public.delete_disinfection_session(uuid) to authenticated;
