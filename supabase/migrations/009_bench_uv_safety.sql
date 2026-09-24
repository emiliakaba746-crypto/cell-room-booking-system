-- Extend disinfection logging to individual clean benches.

alter table public.disinfection_sessions
  add column if not exists equipment_id bigint references public.equipment(id) on delete set null,
  add column if not exists resource_name text not null default '细胞间空间',
  add column if not exists resource_type text not null default 'room';

do $$ begin
  alter table public.disinfection_sessions
    add constraint disinfection_sessions_resource_type_check
    check (resource_type in ('room', 'bench'));
exception when duplicate_object then null; end $$;

create index if not exists disinfection_sessions_equipment_idx
  on public.disinfection_sessions(equipment_id, created_at desc);

create or replace function public.room_safety_state()
returns text
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  v_session public.disinfection_sessions%rowtype;
begin
  update public.disinfection_sessions
  set status = 'safe'
  where equipment_id is null
    and status = 'venting'
    and safe_at is not null
    and now() >= safe_at;

  select * into v_session
  from public.disinfection_sessions
  where equipment_id is null
    and status <> 'cancelled'
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
    return 'venting';
  end if;

  return 'safe';
end;
$$;

create or replace function public.equipment_safety_state(p_equipment_id bigint)
returns text
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  v_room_state text;
  v_session public.disinfection_sessions%rowtype;
begin
  v_room_state := public.room_safety_state();
  if v_room_state <> 'safe' then
    return v_room_state;
  end if;

  update public.disinfection_sessions
  set status = 'safe'
  where equipment_id = p_equipment_id
    and status = 'venting'
    and safe_at is not null
    and now() >= safe_at;

  select * into v_session
  from public.disinfection_sessions
  where equipment_id = p_equipment_id
    and status <> 'cancelled'
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
    return 'venting';
  end if;

  return 'safe';
end;
$$;

drop function if exists public.start_disinfection(text, integer, text);

create or replace function public.start_disinfection(
  p_method text default 'uv_ozone',
  p_duration_minutes integer default 30,
  p_notes text default '',
  p_equipment_id bigint default null
)
returns public.disinfection_sessions
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  v_user_id uuid := auth.uid();
  v_user_name text;
  v_equipment public.equipment%rowtype;
  v_resource_name text;
  v_resource_type text;
  v_safety_state text;
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

  if p_equipment_id is null then
    v_resource_name := '细胞间空间';
    v_resource_type := 'room';
  else
    select * into v_equipment
    from public.equipment
    where id = p_equipment_id
      and type = '超净工作台'
      and active = true;

    if v_equipment.id is null then
      raise exception '超净工作台不存在或已停用';
    end if;

    v_resource_name := v_equipment.name;
    v_resource_type := 'bench';

    if exists (
      select 1 from public.reservations
      where equipment_id = p_equipment_id
        and status = 'in_use'
    ) then
      raise exception '该超净工作台正在使用，禁止开启紫外消毒';
    end if;
  end if;

  v_safety_state := case
    when p_equipment_id is null then public.room_safety_state()
    else public.equipment_safety_state(p_equipment_id)
  end;

  if v_safety_state <> 'safe' then
    raise exception '该资源已有臭氧/紫外消毒记录尚未完成通风，请先结束并通风至安全时间';
  end if;

  select coalesce(nullif(display_name, ''), email, '未命名成员')
  into v_user_name
  from public.profiles
  where id = v_user_id;

  insert into public.disinfection_sessions (
    equipment_id,
    resource_name,
    resource_type,
    method,
    planned_duration_minutes,
    start_at,
    expected_end_at,
    status,
    started_by,
    started_by_name,
    notes
  ) values (
    p_equipment_id,
    v_resource_name,
    v_resource_type,
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
  select * into v_booking from public.reservations where id = p_booking_id for update;
  if v_booking.id is null then
    raise exception '预约不存在';
  end if;
  if public.room_safety_state() <> 'safe' then
    raise exception '当前细胞间空间臭氧/紫外消毒尚未完成通风，禁止开始使用';
  end if;
  if public.equipment_safety_state(v_booking.equipment_id) <> 'safe' then
    raise exception '该设备正在紫外消毒或通风，禁止开始使用';
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

grant execute on function public.equipment_safety_state(bigint) to authenticated;
grant execute on function public.start_disinfection(text, integer, text, bigint) to authenticated;
