"""Small database/service layer for the Streamlit UI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from supabase import Client, create_client

from .config import Settings
from .utils import SHANGHAI, combine_local


@dataclass
class SessionUser:
    id: str
    email: str
    profile: dict[str, Any]

    @property
    def role(self) -> str:
        return str(self.profile.get("role") or "member")

    @property
    def status(self) -> str:
        return str(self.profile.get("status") or "pending")

    @property
    def display_name(self) -> str:
        return str(self.profile.get("display_name") or self.email or "用户")

    @property
    def is_admin(self) -> bool:
        return self.role == "admin" and self.status == "approved"

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"


class BookingService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client: Client = create_client(settings.supabase_url, settings.supabase_anon_key)

    def sign_in(self, email: str, password: str) -> SessionUser:
        response = self.client.auth.sign_in_with_password({"email": email, "password": password})
        if response.user is None or response.session is None:
            raise RuntimeError("登录失败，请检查邮箱和密码。")
        return self._load_user(response.user.id, response.user.email or email)

    def sign_up(
        self,
        email: str,
        password: str,
        display_name: str,
        phone: str,
        student_staff_id: str,
        advisor: str,
    ) -> SessionUser | None:
        response = self.client.auth.sign_up(
            {
                "email": email,
                "password": password,
                "options": {
                    "data": {
                        "display_name": display_name,
                        "phone": phone,
                        "student_staff_id": student_staff_id,
                        "advisor": advisor,
                    }
                },
            }
        )
        if response.session is None:
            raise RuntimeError("注册已提交，请先完成邮箱验证，然后返回登录。")
        if response.user is None:
            return None
        return self._load_user(response.user.id, response.user.email or email)

    def request_password_reset(self, email: str, redirect_to: str) -> None:
        self.client.auth.reset_password_for_email(
            email,
            {"redirect_to": redirect_to},
        )

    def sign_out(self) -> None:
        self.client.auth.sign_out()

    def _load_user(self, user_id: str, email: str) -> SessionUser:
        response = self.client.table("profiles").select("*").eq("id", user_id).maybe_single().execute()
        profile = response.data or {"id": user_id, "email": email}
        return SessionUser(id=user_id, email=email, profile=profile)

    def current_user(self) -> SessionUser | None:
        try:
            response = self.client.auth.get_user()
        except Exception:
            return None
        if response is None or response.user is None:
            return None
        return self._load_user(response.user.id, response.user.email or "")

    def list_equipment(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        query = self.client.table("equipment").select("*").order("sort_order")
        if not include_inactive:
            query = query.eq("active", True)
        return query.execute().data or []

    def list_reservations(
        self,
        *,
        day: date | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        user_id: str | None = None,
        all_users: bool = False,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        query = (
            self.client.table("reservations")
            .select("*, equipment(id,name,type,location)")
            .order("start_at")
            .limit(limit)
        )
        if day is not None:
            day_start = combine_local(day, 0, 0)
            day_end = day_start + timedelta(days=1)
            query = query.gte("start_at", day_start.isoformat()).lt("start_at", day_end.isoformat())
        if start_at is not None:
            query = query.gte("start_at", start_at.isoformat())
        if end_at is not None:
            query = query.lt("start_at", end_at.isoformat())
        if user_id and not all_users:
            query = query.eq("user_id", user_id)
        return query.execute().data or []

    def create_booking(
        self,
        *,
        equipment_id: int,
        start_at: datetime,
        end_at: datetime,
        purpose: str,
        cell_type: str,
    ) -> dict[str, Any]:
        response = self.client.rpc(
            "create_booking",
            {
                "p_equipment_id": equipment_id,
                "p_start_at": start_at.isoformat(),
                "p_end_at": end_at.isoformat(),
                "p_purpose": purpose,
                "p_cell_type": cell_type,
            },
        ).execute()
        return response.data or {}

    def update_booking(
        self,
        *,
        booking_id: str,
        equipment_id: int,
        start_at: datetime,
        end_at: datetime,
        purpose: str,
        cell_type: str,
    ) -> None:
        self.client.rpc(
            "update_booking",
            {
                "p_booking_id": booking_id,
                "p_equipment_id": equipment_id,
                "p_start_at": start_at.isoformat(),
                "p_end_at": end_at.isoformat(),
                "p_purpose": purpose,
                "p_cell_type": cell_type,
            },
        ).execute()

    def cancel_booking(self, booking_id: str) -> None:
        self.client.rpc("cancel_booking", {"p_booking_id": booking_id}).execute()

    def delete_booking(self, booking_id: str) -> None:
        self.client.rpc("delete_booking", {"p_booking_id": booking_id}).execute()

    def start_usage(self, booking_id: str) -> None:
        self.client.rpc("start_usage", {"p_booking_id": booking_id}).execute()

    def complete_usage(self, booking_id: str, notes: str = "") -> None:
        self.client.rpc("complete_usage", {"p_booking_id": booking_id, "p_notes": notes}).execute()

    def set_profile_status(self, user_id: str, status: str) -> None:
        self.client.table("profiles").update({"status": status}).eq("id", user_id).execute()

    def set_profile_role(self, user_id: str, role: str) -> None:
        self.client.table("profiles").update({"role": role}).eq("id", user_id).execute()

    def update_my_profile(
        self,
        display_name: str,
        phone: str,
        student_staff_id: str,
        advisor: str,
    ) -> None:
        self.client.rpc(
            "update_my_profile",
            {
                "p_display_name": display_name,
                "p_phone": phone,
                "p_student_staff_id": student_staff_id,
                "p_advisor": advisor,
            },
        ).execute()

    def promote_initial_admin(self) -> bool:
        response = self.client.rpc("promote_initial_admin").execute()
        return bool(response.data)

    def upsert_equipment(
        self,
        *,
        equipment_id: int | None,
        name: str,
        equipment_type: str,
        location: str,
        sort_order: int,
        active: bool,
    ) -> None:
        payload = {
            "name": name,
            "type": equipment_type,
            "location": location,
            "sort_order": sort_order,
            "active": active,
        }
        if equipment_id:
            self.client.table("equipment").update(payload).eq("id", equipment_id).execute()
        else:
            self.client.table("equipment").insert(payload).execute()

    def list_profiles(self) -> list[dict[str, Any]]:
        return self.client.table("profiles").select("*").order("created_at", desc=True).execute().data or []

    def ensure_cleaning_assignment(self, friday_date: date) -> dict[str, Any]:
        response = self.client.rpc(
            "ensure_cleaning_assignment",
            {"p_friday": friday_date.isoformat()},
        ).execute()
        data = response.data or []
        if isinstance(data, list):
            return data[0] if data else {}
        return data

    def get_cleaning_assignment(self, friday_date: date) -> dict[str, Any] | None:
        response = (
            self.client.table("cleaning_assignments")
            .select("*")
            .eq("friday_date", friday_date.isoformat())
            .maybe_single()
            .execute()
        )
        return response.data or None

    def list_cleaning_assignments(self, start_date: date, end_date: date) -> list[dict[str, Any]]:
        return (
            self.client.table("cleaning_assignments")
            .select("*")
            .gte("friday_date", start_date.isoformat())
            .lte("friday_date", end_date.isoformat())
            .order("friday_date")
            .execute()
            .data
            or []
        )

    def set_cleaning_assignment(
        self,
        friday_date: date,
        assignee_id: str,
        note: str = "",
    ) -> dict[str, Any]:
        response = self.client.rpc(
            "set_cleaning_assignment",
            {
                "p_friday": friday_date.isoformat(),
                "p_assignee_id": assignee_id,
                "p_note": note,
            },
        ).execute()
        data = response.data or []
        if isinstance(data, list):
            return data[0] if data else {}
        return data

    def list_internal_messages(
        self,
        user_id: str,
        *,
        all_users: bool = False,
        unread_only: bool = False,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query = (
            self.client.table("internal_messages")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
        )
        if not all_users:
            query = query.eq("recipient_id", user_id)
        if unread_only:
            query = query.is_("read_at", None)
        return query.execute().data or []

    def list_disinfection_sessions(
        self,
        limit: int = 100,
        *,
        equipment_id: int | None = None,
        room_only: bool = False,
    ) -> list[dict[str, Any]]:
        query = (
            self.client.table("disinfection_sessions")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
        )
        if room_only:
            query = query.is_("equipment_id", None)
        elif equipment_id is not None:
            query = query.eq("equipment_id", equipment_id)
        return query.execute().data or []

    def list_open_disinfection_sessions(self) -> list[dict[str, Any]]:
        return (
            self.client.table("disinfection_sessions")
            .select("*")
            .in_("status", ["active", "venting"])
            .order("created_at", desc=True)
            .execute()
            .data
            or []
        )

    def latest_disinfection_session(
        self,
        *,
        equipment_id: int | None = None,
        room_only: bool = False,
    ) -> dict[str, Any] | None:
        query = (
            self.client.table("disinfection_sessions")
            .select("*")
            .neq("status", "cancelled")
            .order("created_at", desc=True)
            .limit(1)
        )
        if room_only:
            query = query.is_("equipment_id", None)
        elif equipment_id is not None:
            query = query.eq("equipment_id", equipment_id)
        response = query.execute()
        rows = response.data or []
        return rows[0] if rows else None

    def room_safety_state(self) -> str:
        response = self.client.rpc("room_safety_state").execute()
        return str(response.data or "safe")

    def equipment_safety_state(self, equipment_id: int) -> str:
        response = self.client.rpc(
            "equipment_safety_state",
            {"p_equipment_id": equipment_id},
        ).execute()
        return str(response.data or "safe")

    def start_disinfection(
        self,
        method: str,
        duration_minutes: int,
        notes: str = "",
        equipment_id: int | None = None,
    ) -> dict[str, Any]:
        response = self.client.rpc(
            "start_disinfection",
            {
                "p_method": method,
                "p_duration_minutes": duration_minutes,
                "p_notes": notes,
                "p_equipment_id": equipment_id,
            },
        ).execute()
        data = response.data or []
        if isinstance(data, list):
            return data[0] if data else {}
        return data

    def finish_disinfection(
        self,
        session_id: str,
        ventilation_minutes: int = 30,
    ) -> dict[str, Any]:
        response = self.client.rpc(
            "finish_disinfection",
            {
                "p_session_id": session_id,
                "p_ventilation_minutes": ventilation_minutes,
            },
        ).execute()
        data = response.data or []
        if isinstance(data, list):
            return data[0] if data else {}
        return data

    def confirm_disinfection_safe(self, session_id: str) -> dict[str, Any]:
        response = self.client.rpc(
            "confirm_disinfection_safe",
            {"p_session_id": session_id},
        ).execute()
        data = response.data or []
        if isinstance(data, list):
            return data[0] if data else {}
        return data

    def delete_disinfection_session(self, session_id: str) -> None:
        self.client.rpc(
            "delete_disinfection_session",
            {"p_session_id": session_id},
        ).execute()

    def count_unread_messages(self, user_id: str) -> int:
        response = (
            self.client.table("internal_messages")
            .select("id", count="exact")
            .eq("recipient_id", user_id)
            .is_("read_at", None)
            .execute()
        )
        return int(response.count or 0)

    def mark_message_read(self, message_id: str) -> None:
        self.client.rpc("mark_message_read", {"p_message_id": message_id}).execute()

    def mark_all_messages_read(self) -> None:
        self.client.rpc("mark_all_messages_read").execute()

    def send_internal_message(
        self,
        recipient_id: str,
        title: str,
        content: str,
        *,
        message_type: str = "general",
        related_date: date | None = None,
    ) -> dict[str, Any]:
        response = self.client.rpc(
            "send_internal_message",
            {
                "p_recipient_id": recipient_id,
                "p_title": title,
                "p_content": content,
                "p_message_type": message_type,
                "p_related_date": related_date.isoformat() if related_date else None,
            },
        ).execute()
        data = response.data or []
        if isinstance(data, list):
            return data[0] if data else {}
        return data

    def broadcast_internal_message(
        self,
        title: str,
        content: str,
        *,
        message_type: str = "general",
        related_date: date | None = None,
    ) -> int:
        response = self.client.rpc(
            "broadcast_internal_message",
            {
                "p_title": title,
                "p_content": content,
                "p_message_type": message_type,
                "p_related_date": related_date.isoformat() if related_date else None,
            },
        ).execute()
        return int(response.data or 0)

    def send_cleaning_reminder(
        self,
        friday_date: date,
        content: str,
    ) -> dict[str, Any]:
        response = self.client.rpc(
            "send_cleaning_reminder",
            {
                "p_friday": friday_date.isoformat(),
                "p_content": content,
            },
        ).execute()
        data = response.data or []
        if isinstance(data, list):
            return data[0] if data else {}
        return data

    def usage_report(self, start_at: datetime, end_at: datetime) -> list[dict[str, Any]]:
        response = (
            self.client.table("reservation_usage_summary")
            .select("*")
            .gte("start_at", start_at.isoformat())
            .lt("start_at", end_at.isoformat())
            .order("start_at", desc=True)
            .execute()
        )
        return response.data or []


def first_error_message(error: Exception) -> str:
    """Return a compact, user-facing error from supabase-py exceptions."""
    message = str(error)
    replacements = {
        "duplicate key value violates unique constraint": "该时间段已被预约，请选择其他时间。",
        "exclusion constraint": "该设备在所选时间段已有预约。",
        "该设备在所选时间段已有预约": "该设备在所选时间段已有预约，请选择其他时间。",
        "not approved": "账号尚未通过管理员审批。",
        "not authorized": "没有执行该操作的权限。",
        "JWT": "登录状态已过期，请重新登录。",
    }
    for needle, friendly in replacements.items():
        if needle.lower() in message.lower():
            return friendly
    return message





