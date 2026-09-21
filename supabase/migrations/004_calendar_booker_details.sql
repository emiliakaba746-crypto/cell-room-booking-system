-- Show booker contact and training details on the calendar.

alter table public.reservations add column if not exists booked_by_phone text not null default '';
alter table public.reservations add column if not exists booked_by_student_staff_id text not null default '';
alter table public.reservations add column if not exists booked_by_advisor text not null default '';

create or replace function public.sync_reservation_booker_from_profile()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.reservations
  set booked_by_name = coalesce(new.display_name, new.email, ''),
      booked_by_email = coalesce(new.email, ''),
      booked_by_phone = coalesce(new.phone, ''),
      booked_by_student_staff_id = coalesce(new.student_staff_id, ''),
      booked_by_advisor = coalesce(new.advisor, '')
  where user_id = new.id;
  return new;
end;
$$;

drop trigger if exists profiles_sync_reservations on public.profiles;
create trigger profiles_sync_reservations
after update of display_name, email, phone, student_staff_id, advisor on public.profiles
for each row execute function public.sync_reservation_booker_from_profile();

update public.reservations r
set booked_by_name = coalesce(p.display_name, p.email, r.booked_by_name),
    booked_by_email = coalesce(p.email, r.booked_by_email),
    booked_by_phone = coalesce(p.phone, ''),
    booked_by_student_staff_id = coalesce(p.student_staff_id, ''),
    booked_by_advisor = coalesce(p.advisor, '')
from public.profiles p
where p.id = r.user_id
  and (
    r.booked_by_phone <> coalesce(p.phone, '') or
    r.booked_by_student_staff_id <> coalesce(p.student_staff_id, '') or
    r.booked_by_advisor <> coalesce(p.advisor, '') or
    r.booked_by_name <> coalesce(p.display_name, p.email, r.booked_by_name) or
    r.booked_by_email <> coalesce(p.email, r.booked_by_email)
  );

create or replace function public.create_booking(
  p_equipment_id bigint,
  p_start_at timestamptz,
  p_end_at timestamptz,
  p_purpose text default ''
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
    user_id, equipment_id, start_at, end_at, purpose, status,
    booked_by_name, booked_by_email, booked_by_phone,
    booked_by_student_staff_id, booked_by_advisor
  ) values (
    v_user_id, p_equipment_id, p_start_at, p_end_at, coalesce(p_purpose, ''), 'booked',
    coalesce(v_profile.display_name, v_profile.email, ''),
    coalesce(v_profile.email, ''),
    coalesce(v_profile.phone, ''),
    coalesce(v_profile.student_staff_id, ''),
    coalesce(v_profile.advisor, '')
  ) returning id into v_booking_id;

  return jsonb_build_object('id', v_booking_id);
end;
$$;

grant execute on function public.create_booking(bigint, timestamptz, timestamptz, text) to authenticated;
