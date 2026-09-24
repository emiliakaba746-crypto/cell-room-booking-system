-- Public, read-only dashboard for reservations and disinfection safety.

create or replace function public.get_public_dashboard(p_day date default current_date)
returns jsonb
language sql
security definer
set search_path = public, auth
as $$
with equipment_data as (
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'id', e.id,
        'name', e.name,
        'type', e.type,
        'location', e.location,
        'sort_order', e.sort_order,
        'safety_state',
          case
            when e.type = '超净工作台' then public.equipment_safety_state(e.id)
            else 'safe'
          end
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
  'room_safety_state', public.room_safety_state(),
  'equipment', equipment_data.items,
  'reservations', reservation_data.items,
  'disinfection', disinfection_data.items
)
from equipment_data, reservation_data, disinfection_data;
$$;

grant execute on function public.get_public_dashboard(date) to anon, authenticated;
