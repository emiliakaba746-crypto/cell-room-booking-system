-- Add the flow-cytometry room as a second managed area.
-- 流式细胞间：位于一更、二更之后，含 1 台分选型流式细胞仪、1 台分析型流式细胞仪，
-- 并具备房间级臭氧/紫外消毒能力，需要像细胞间一样登记并联动安全门禁。

-- 1) Which area an equipment belongs to.
alter table public.equipment
  add column if not exists room_key text not null default 'cell_room';

do $$ begin
  alter table public.equipment
    add constraint equipment_room_key_check
    check (room_key in ('cell_room', 'flow_room'));
exception when duplicate_object then null; end $$;

update public.equipment set room_key = 'cell_room' where room_key is null;

-- 2) Register the two flow cytometers.
insert into public.equipment (name, type, location, sort_order, active, room_key)
values
  ('分选型流式细胞仪', '流式细胞仪', '流式细胞间', 70, true, 'flow_room'),
  ('分析型流式细胞仪', '流式细胞仪', '流式细胞间', 80, true, 'flow_room')
on conflict (name) do update set
  type = excluded.type,
  location = excluded.location,
  sort_order = excluded.sort_order,
  room_key = excluded.room_key;

-- 3) Tag every disinfection record with its area.
alter table public.disinfection_sessions
  add column if not exists room_key text not null default 'cell_room';

do $$ begin
  alter table public.disinfection_sessions
    add constraint disinfection_sessions_room_key_check
    check (room_key in ('cell_room', 'flow_room'));
exception when duplicate_object then null; end $$;

update public.disinfection_sessions s
set room_key = e.room_key
from public.equipment e
where s.equipment_id = e.id
  and s.room_key is distinct from e.room_key;

create index if not exists disinfection_sessions_room_idx
  on public.disinfection_sessions(room_key, created_at desc);

-- 4) Display helper for area names.
create or replace function public.room_display_name(p_room_key text)
returns text
language sql
immutable
as $$
  select case p_room_key
    when 'flow_room' then '流式细胞间空间'
    else '细胞间空间'
  end;
$$;

-- 5) Room safety state, now per area.
create or replace function public.room_safety_state_for(p_room_key text default 'cell_room')
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
    and room_key = p_room_key
    and status = 'venting'
    and safe_at is not null
    and now() >= safe_at;

  select * into v_session
  from public.disinfection_sessions
  where equipment_id is null
    and room_key = p_room_key
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

-- Keep the original zero-argument function working as the cell-room alias.
create or replace function public.room_safety_state()
returns text
language sql
security definer
set search_path = public, auth
as $$ select public.room_safety_state_for('cell_room'); $$;

-- 6) Equipment safety now follows the area the equipment lives in.
create or replace function public.equipment_safety_state(p_equipment_id bigint)
returns text
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  v_room_key text;
  v_room_state text;
  v_session public.disinfection_sessions%rowtype;
begin
  select coalesce(room_key, 'cell_room') into v_room_key
  from public.equipment
  where id = p_equipment_id;

  if v_room_key is null then
    v_room_key := 'cell_room';
  end if;

  v_room_state := public.room_safety_state_for(v_room_key);
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

-- 7) Start disinfection for either area (equipment_id null) or a clean bench.
-- The previous 4-argument version stays in place for older clients and keeps
-- operating on the cell room; this 5-argument overload adds the area parameter.
create or replace function public.start_disinfection(
  p_method text,
  p_duration_minutes integer,
  p_notes text,
  p_equipment_id bigint,
  p_room_key text
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
  v_room_key text;
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
    if p_room_key not in ('cell_room', 'flow_room') then
      raise exception '区域无效';
    end if;

    v_room_key := p_room_key;
    v_resource_name := public.room_display_name(p_room_key);
    v_resource_type := 'room';

    if exists (
      select 1
      from public.reservations r
      join public.equipment e on e.id = r.equipment_id
      where coalesce(e.room_key, 'cell_room') = v_room_key
        and r.status = 'in_use'
    ) then
      raise exception '该区域有预约正在使用，禁止开启臭氧/紫外消毒';
    end if;
  else
    select * into v_equipment
    from public.equipment
    where id = p_equipment_id
      and type = '超净工作台'
      and active = true;

    if v_equipment.id is null then
      raise exception '超净工作台不存在或已停用';
    end if;

    v_room_key := coalesce(v_equipment.room_key, 'cell_room');
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
    when p_equipment_id is null then public.room_safety_state_for(v_room_key)
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
    room_key,
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
    v_room_key,
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

-- 8) Usage start gate now checks the booking's own area.
create or replace function public.start_usage(p_booking_id uuid)
returns void
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  v_booking public.reservations%rowtype;
  v_user_id uuid := auth.uid();
  v_room_key text;
begin
  select * into v_booking from public.reservations where id = p_booking_id for update;
  if v_booking.id is null then
    raise exception '预约不存在';
  end if;

  select coalesce(room_key, 'cell_room') into v_room_key
  from public.equipment
  where id = v_booking.equipment_id;
  v_room_key := coalesce(v_room_key, 'cell_room');

  if public.room_safety_state_for(v_room_key) <> 'safe' then
    raise exception '% 臭氧/紫外消毒尚未完成通风，禁止开始使用', public.room_display_name(v_room_key);
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

-- 9) Public dashboard exposes both areas and tags every equipment with its area.
create or replace function public.get_public_dashboard(p_day date default current_date)
returns jsonb
language sql
security definer
set search_path = public, auth
as $$
with room_list as (
  select * from (values ('cell_room'), ('flow_room')) as r(room_key)
),
room_data as (
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'room_key', rl.room_key,
        'name', public.room_display_name(rl.room_key),
        'safety_state', public.room_safety_state_for(rl.room_key)
      )
      order by case rl.room_key when 'cell_room' then 1 else 2 end
    ),
    '[]'::jsonb
  ) as items
  from room_list rl
),
equipment_data as (
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'id', e.id,
        'name', e.name,
        'type', e.type,
        'location', e.location,
        'sort_order', e.sort_order,
        'room_key', coalesce(e.room_key, 'cell_room'),
        'safety_state', public.equipment_safety_state(e.id)
      )
      order by e.sort_order
    ),
    '[]'::jsonb
  ) as items
  from public.equipment e
  where e.active = true
),
reservation_data as (
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'id', r.id,
        'equipment_id', r.equipment_id,
        'equipment_name', e.name,
        'room_key', coalesce(e.room_key, 'cell_room'),
        'start_at', r.start_at,
        'end_at', r.end_at,
        'status', r.status,
        'masked_name',
          case
            when length(coalesce(p.display_name, '')) > 1
              then left(p.display_name, 1) || repeat('*', length(p.display_name) - 1)
            when coalesce(p.display_name, '') <> '' then p.display_name
            else '成员'
          end
      )
      order by r.start_at
    ),
    '[]'::jsonb
  ) as items
  from public.reservations r
  join public.equipment e on e.id = r.equipment_id
  join public.profiles p on p.id = r.user_id
  where (r.start_at at time zone 'Asia/Shanghai')::date = p_day
    and r.status in ('booked', 'in_use', 'completed')
),
disinfection_data as (
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'id', s.id,
        'equipment_id', s.equipment_id,
        'room_key', coalesce(s.room_key, 'cell_room'),
        'resource_name', s.resource_name,
        'resource_type', s.resource_type,
        'method', s.method,
        'planned_duration_minutes', s.planned_duration_minutes,
        'start_at', s.start_at,
        'expected_end_at', s.expected_end_at,
        'ended_at', s.ended_at,
        'ventilation_started_at', s.ventilation_started_at,
        'safe_at', s.safe_at,
        'status', s.status,
        'masked_operator',
          case
            when length(coalesce(s.started_by_name, '')) > 1
              then left(s.started_by_name, 1) || repeat('*', length(s.started_by_name) - 1)
            when coalesce(s.started_by_name, '') <> '' then s.started_by_name
            else '成员'
          end
      )
      order by s.created_at desc
    ),
    '[]'::jsonb
  ) as items
  from (
    select *
    from public.disinfection_sessions
    order by created_at desc
    limit 20
  ) s
)
select jsonb_build_object(
  'day', p_day,
  'room_safety_state', public.room_safety_state_for('cell_room'),
  'rooms', room_data.items,
  'equipment', equipment_data.items,
  'reservations', reservation_data.items,
  'disinfection', disinfection_data.items
)
from room_data, equipment_data, reservation_data, disinfection_data;
$$;

grant execute on function public.room_display_name(text) to anon, authenticated;
grant execute on function public.room_safety_state_for(text) to anon, authenticated;
grant execute on function public.room_safety_state() to anon, authenticated;
grant execute on function public.start_disinfection(text, integer, text, bigint, text) to authenticated;
grant execute on function public.get_public_dashboard(date) to anon, authenticated;
