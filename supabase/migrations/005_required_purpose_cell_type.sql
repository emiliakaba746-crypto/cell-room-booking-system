-- Require booking purpose and cultured cell type.

alter table public.reservations add column if not exists cell_type text not null default '';

drop function if exists public.create_booking(bigint, timestamptz, timestamptz, text);
drop function if exists public.update_booking(uuid, bigint, timestamptz, timestamptz, text);

create or replace function public.create_booking(
  p_equipment_id bigint,
  p_start_at timestamptz,
  p_end_at timestamptz,
  p_purpose text default '',
  p_cell_type text default ''
)
returns jsonb
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  v_user_id uuid := auth.uid();
  v_profile public.profiles%rowtype;
  v_booking_id uuid;
  v_local_day date;
  v_has_conflict boolean;
begin
  if v_user_id is null then
    raise exception 'not authenticated';
  end if;

  select * into v_profile from public.profiles where id = v_user_id;
  if v_profile.id is null then
    raise exception 'profile not found';
  end if;
  if v_profile.status <> 'approved' and not public.is_admin() then
    raise exception 'not approved';
  end if;

  if btrim(coalesce(p_purpose, '')) = '' then
    raise exception '请填写预约使用目的';
  end if;

  if btrim(coalesce(p_cell_type, '')) = '' then
    raise exception '请填写培养的细胞类型';
  end if;

  if p_end_at <= p_start_at then
    raise exception '结束时间必须晚于开始时间';
  end if;

  if (p_start_at at time zone 'Asia/Shanghai')::date <>
     (((p_end_at - interval '1 microsecond') at time zone 'Asia/Shanghai')::date) then
    raise exception '预约必须位于同一天内';
  end if;

  if (p_end_at - p_start_at) > interval '24 hours' then
    raise exception '单次预约不能超过 24 小时';
  end if;

  if not exists (select 1 from public.equipment where id = p_equipment_id and active = true) then
    raise exception '设备不存在或已停用';
  end if;

  v_local_day := (p_start_at at time zone 'Asia/Shanghai')::date;
  perform pg_advisory_xact_lock(hashtext(p_equipment_id::text || ':' || v_local_day::text));

  select exists (
    select 1
    from public.reservations r
    where r.equipment_id = p_equipment_id
      and r.status in ('booked', 'in_use')
      and tstzrange(r.start_at, r.end_at, '[)') && tstzrange(p_start_at, p_end_at, '[)')
  ) into v_has_conflict;

  if v_has_conflict then
    raise exception '该设备在所选时间段已有预约';
  end if;

  insert into public.reservations (
    user_id, equipment_id, start_at, end_at, purpose, cell_type, status,
    booked_by_name, booked_by_email, booked_by_phone,
    booked_by_student_staff_id, booked_by_advisor
  ) values (
    v_user_id, p_equipment_id, p_start_at, p_end_at,
    btrim(p_purpose), btrim(p_cell_type), 'booked',
    coalesce(v_profile.display_name, v_profile.email, ''),
    coalesce(v_profile.email, ''),
    coalesce(v_profile.phone, ''),
    coalesce(v_profile.student_staff_id, ''),
    coalesce(v_profile.advisor, '')
  ) returning id into v_booking_id;

  return jsonb_build_object('id', v_booking_id);
end;
$$;

create or replace function public.update_booking(
  p_booking_id uuid,
  p_equipment_id bigint,
  p_start_at timestamptz,
  p_end_at timestamptz,
  p_purpose text default '',
  p_cell_type text default ''
)
returns void
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  v_user_id uuid := auth.uid();
  v_booking public.reservations%rowtype;
  v_local_day date;
  v_has_conflict boolean;
begin
  if v_user_id is null then
    raise exception 'not authenticated';
  end if;

  if not public.is_admin() and not public.is_approved() then
    raise exception 'not approved';
  end if;

  if btrim(coalesce(p_purpose, '')) = '' then
    raise exception '请填写预约使用目的';
  end if;

  if btrim(coalesce(p_cell_type, '')) = '' then
    raise exception '请填写培养的细胞类型';
  end if;

  select * into v_booking from public.reservations where id = p_booking_id for update;
  if v_booking.id is null then
    raise exception '预约不存在';
  end if;

  if v_booking.user_id <> v_user_id and not public.is_admin() then
    raise exception 'not authorized';
  end if;

  if v_booking.status <> 'booked' then
    raise exception '只有“已预约”状态可以修改';
  end if;

  if not public.is_admin() and now() >= v_booking.start_at then
    raise exception '预约开始后不能自行修改';
  end if;

  if not public.is_admin() and now() >= p_start_at then
    raise exception '新的预约时间必须晚于当前时间';
  end if;

  if p_end_at <= p_start_at then
    raise exception '结束时间必须晚于开始时间';
  end if;

  if (p_start_at at time zone 'Asia/Shanghai')::date <>
     (((p_end_at - interval '1 microsecond') at time zone 'Asia/Shanghai')::date) then
    raise exception '预约必须位于同一天内';
  end if;

  if (p_end_at - p_start_at) > interval '24 hours' then
    raise exception '单次预约不能超过 24 小时';
  end if;

  if not exists (select 1 from public.equipment where id = p_equipment_id and active = true) then
    raise exception '设备不存在或已停用';
  end if;

  v_local_day := (p_start_at at time zone 'Asia/Shanghai')::date;
  perform pg_advisory_xact_lock(hashtext(p_equipment_id::text || ':' || v_local_day::text));

  select exists (
    select 1
    from public.reservations r
    where r.id <> p_booking_id
      and r.equipment_id = p_equipment_id
      and r.status in ('booked', 'in_use')
      and tstzrange(r.start_at, r.end_at, '[)') && tstzrange(p_start_at, p_end_at, '[)')
  ) into v_has_conflict;

  if v_has_conflict then
    raise exception '该设备在所选时间段已有预约';
  end if;

  update public.reservations
  set equipment_id = p_equipment_id,
      start_at = p_start_at,
      end_at = p_end_at,
      purpose = btrim(p_purpose),
      cell_type = btrim(p_cell_type)
  where id = p_booking_id;
end;
$$;

grant execute on function public.create_booking(bigint, timestamptz, timestamptz, text, text) to authenticated;
grant execute on function public.update_booking(uuid, bigint, timestamptz, timestamptz, text, text) to authenticated;

drop view if exists public.reservation_usage_summary;

create or replace view public.reservation_usage_summary
with (security_invoker = true)
as
select
  r.id,
  r.user_id,
  r.equipment_id,
  e.name as equipment_name,
  p.display_name as user_name,
  p.email as user_email,
  r.start_at,
  r.end_at,
  r.purpose,
  r.cell_type,
  r.status,
  r.booked_by_name,
  r.created_at,
  floor(extract(epoch from (r.end_at - r.start_at)) / 60)::integer as reserved_minutes,
  case
    when us.actual_end is not null then floor(extract(epoch from (us.actual_end - us.actual_start)) / 60)::integer
    else null
  end as actual_minutes,
  us.actual_start,
  us.actual_end,
  us.notes
from public.reservations r
join public.equipment e on e.id = r.equipment_id
join public.profiles p on p.id = r.user_id
left join public.usage_sessions us on us.reservation_id = r.id;

grant select on public.reservation_usage_summary to authenticated;

