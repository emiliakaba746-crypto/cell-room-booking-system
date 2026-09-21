-- Reservation editing and admin deletion.

create or replace function public.update_booking(
  p_booking_id uuid,
  p_equipment_id bigint,
  p_start_at timestamptz,
  p_end_at timestamptz,
  p_purpose text default ''
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
      purpose = coalesce(p_purpose, '')
  where id = p_booking_id;
end;
$$;

create or replace function public.delete_booking(p_booking_id uuid)
returns void
language plpgsql
security definer
set search_path = public, auth
as $$
begin
  if not public.is_admin() then
    raise exception 'not authorized';
  end if;

  delete from public.reservations where id = p_booking_id;
  if not found then
    raise exception '预约不存在';
  end if;
end;
$$;

grant execute on function public.update_booking(uuid, bigint, timestamptz, timestamptz, text) to authenticated;
grant execute on function public.delete_booking(uuid) to authenticated;
