-- Internal messages for administrator notices and cleaning reminders.

create table if not exists public.internal_messages (
  id uuid primary key default gen_random_uuid(),
  sender_id uuid references auth.users(id) on delete set null,
  sender_name text not null default '',
  recipient_id uuid not null references public.profiles(id) on delete cascade,
  recipient_name text not null default '',
  title text not null check (length(btrim(title)) between 1 and 120),
  content text not null check (length(btrim(content)) between 1 and 3000),
  message_type text not null default 'general'
    check (message_type in ('general', 'cleaning')),
  related_date date,
  read_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists internal_messages_recipient_idx on public.internal_messages(recipient_id, created_at desc);
create index if not exists internal_messages_unread_idx on public.internal_messages(recipient_id) where read_at is null;

create or replace function public.send_internal_message(
  p_recipient_id uuid,
  p_title text,
  p_content text,
  p_message_type text default 'general',
  p_related_date date default null
)
returns public.internal_messages
language plpgsql security definer set search_path = public, auth
as $$
declare
  v_sender_id uuid := auth.uid();
  v_sender_name text;
  v_recipient_name text;
  v_message public.internal_messages;
begin
  if not public.is_admin() then raise exception 'not authorized'; end if;
  if btrim(coalesce(p_title, '')) = '' or length(btrim(p_title)) > 120 then raise exception '通知标题长度必须为 1 到 120 个字符'; end if;
  if btrim(coalesce(p_content, '')) = '' or length(btrim(p_content)) > 3000 then raise exception '通知内容长度必须为 1 到 3000 个字符'; end if;
  if p_message_type not in ('general', 'cleaning') then raise exception '通知类型无效'; end if;
  select coalesce(nullif(display_name, ''), email, '管理员') into v_sender_name from public.profiles where id = v_sender_id;
  select coalesce(nullif(display_name, ''), email, '未命名成员') into v_recipient_name from public.profiles where id = p_recipient_id and status = 'approved';
  if v_recipient_name is null then raise exception '收件人不存在或尚未授权'; end if;
  insert into public.internal_messages (sender_id, sender_name, recipient_id, recipient_name, title, content, message_type, related_date)
  values (v_sender_id, coalesce(v_sender_name, '管理员'), p_recipient_id, v_recipient_name, btrim(p_title), btrim(p_content), p_message_type, p_related_date)
  returning * into v_message;
  return v_message;
end;
$$;

create or replace function public.broadcast_internal_message(
  p_title text,
  p_content text,
  p_message_type text default 'general',
  p_related_date date default null
)
returns integer
language plpgsql security definer set search_path = public, auth
as $$
declare
  v_sender_id uuid := auth.uid();
  v_sender_name text;
  v_count integer := 0;
begin
  if not public.is_admin() then raise exception 'not authorized'; end if;
  if btrim(coalesce(p_title, '')) = '' or btrim(coalesce(p_content, '')) = '' then raise exception '通知标题和内容不能为空'; end if;
  select coalesce(nullif(display_name, ''), email, '管理员') into v_sender_name from public.profiles where id = v_sender_id;
  insert into public.internal_messages (sender_id, sender_name, recipient_id, recipient_name, title, content, message_type, related_date)
  select v_sender_id, coalesce(v_sender_name, '管理员'), p.id, coalesce(nullif(p.display_name, ''), p.email, '未命名成员'), btrim(p_title), btrim(p_content), p_message_type, p_related_date
  from public.profiles p where p.status = 'approved' and p.id <> v_sender_id;
  get diagnostics v_count = row_count;
  return v_count;
end;
$$;

create or replace function public.mark_message_read(p_message_id uuid)
returns void
language plpgsql security definer set search_path = public, auth
as $$
begin
  update public.internal_messages set read_at = coalesce(read_at, now()) where id = p_message_id and recipient_id = auth.uid();
  if not found then raise exception '通知不存在或无权操作'; end if;
end;
$$;

create or replace function public.mark_all_messages_read()
returns integer
language plpgsql security definer set search_path = public, auth
as $$
declare v_count integer := 0;
begin
  update public.internal_messages set read_at = now() where recipient_id = auth.uid() and read_at is null;
  get diagnostics v_count = row_count;
  return v_count;
end;
$$;

create or replace function public.send_cleaning_reminder(p_friday date, p_content text default '')
returns public.internal_messages
language plpgsql security definer set search_path = public, auth
as $$
declare
  v_assignment public.cleaning_assignments;
  v_sender_id uuid := auth.uid();
  v_sender_name text;
  v_content text;
  v_message public.internal_messages;
begin
  if not public.is_admin() then raise exception 'not authorized'; end if;
  v_assignment := public.ensure_cleaning_assignment(p_friday);
  if v_assignment.assignee_id is null then raise exception '该周五尚未安排卫生负责人'; end if;
  select coalesce(nullif(display_name, ''), email, '管理员') into v_sender_name from public.profiles where id = v_sender_id;
  v_content := nullif(btrim(coalesce(p_content, '')), '');
  if v_content is null then
    v_content := format('您被安排负责 %s 的细胞间卫生。请按要求完成台面、培养箱、地面和废弃物清理，并在完成后告知管理员。', to_char(p_friday, 'YYYY-MM-DD'));
  end if;
  insert into public.internal_messages (sender_id, sender_name, recipient_id, recipient_name, title, content, message_type, related_date)
  values (v_sender_id, coalesce(v_sender_name, '管理员'), v_assignment.assignee_id, v_assignment.assignee_name, '本周五卫生提醒', v_content, 'cleaning', p_friday)
  returning * into v_message;
  return v_message;
end;
$$;

alter table public.internal_messages enable row level security;
drop policy if exists internal_messages_select on public.internal_messages;
create policy internal_messages_select on public.internal_messages for select to authenticated using (recipient_id = auth.uid() or public.is_admin());
grant select on public.internal_messages to authenticated;
grant execute on function public.send_internal_message(uuid, text, text, text, date) to authenticated;
grant execute on function public.broadcast_internal_message(text, text, text, date) to authenticated;
grant execute on function public.mark_message_read(uuid) to authenticated;
grant execute on function public.mark_all_messages_read() to authenticated;
grant execute on function public.send_cleaning_reminder(date, text) to authenticated;
