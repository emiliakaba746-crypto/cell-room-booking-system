-- Registration profile fields and safer bootstrap.

alter table public.profiles add column if not exists student_staff_id text not null default '';
alter table public.profiles add column if not exists advisor text not null default '';

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public, auth
as $$
begin
  insert into public.profiles (id, email, display_name, phone, student_staff_id, advisor)
  values (
    new.id,
    coalesce(new.email, ''),
    coalesce(new.raw_user_meta_data ->> 'display_name', ''),
    coalesce(new.raw_user_meta_data ->> 'phone', ''),
    coalesce(new.raw_user_meta_data ->> 'student_staff_id', ''),
    coalesce(new.raw_user_meta_data ->> 'advisor', '')
  )
  on conflict (id) do update set
    email = excluded.email,
    display_name = case when public.profiles.display_name = '' then excluded.display_name else public.profiles.display_name end,
    phone = case when public.profiles.phone = '' then excluded.phone else public.profiles.phone end,
    student_staff_id = case when public.profiles.student_staff_id = '' then excluded.student_staff_id else public.profiles.student_staff_id end,
    advisor = case when public.profiles.advisor = '' then excluded.advisor else public.profiles.advisor end;
  return new;
end;
$$;

update public.profiles p
set
  phone = case when coalesce(p.phone, '') = '' then coalesce(u.raw_user_meta_data ->> 'phone', '') else p.phone end,
  student_staff_id = case when coalesce(p.student_staff_id, '') = '' then coalesce(u.raw_user_meta_data ->> 'student_staff_id', '') else p.student_staff_id end,
  advisor = case when coalesce(p.advisor, '') = '' then coalesce(u.raw_user_meta_data ->> 'advisor', '') else p.advisor end
from auth.users u
where u.id = p.id
  and (
    coalesce(p.phone, '') = '' or
    coalesce(p.student_staff_id, '') = '' or
    coalesce(p.advisor, '') = ''
  );

drop function if exists public.update_my_profile(text, text);

create or replace function public.update_my_profile(
  p_display_name text,
  p_phone text,
  p_student_staff_id text,
  p_advisor text
)
returns void
language plpgsql
security definer
set search_path = public, auth
as $$
begin
  if auth.uid() is null then
    raise exception 'not authenticated';
  end if;
  update public.profiles
  set display_name = coalesce(p_display_name, ''),
      phone = coalesce(p_phone, ''),
      student_staff_id = coalesce(p_student_staff_id, ''),
      advisor = coalesce(p_advisor, '')
  where id = auth.uid();
end;
$$;

grant execute on function public.update_my_profile(text, text, text, text) to authenticated;

-- Do not let arbitrary authenticated users bootstrap themselves as admin.
revoke execute on function public.promote_initial_admin() from authenticated;
