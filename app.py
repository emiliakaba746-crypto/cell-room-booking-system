from __future__ import annotations

import base64
import html
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import streamlit as st

from booking import (
    BookingService,
    DAY_MINUTES,
    SHANGHAI,
    SLOT_MINUTES,
    first_error_message,
    format_local,
    format_minutes,
    load_settings,
    minute_offset,
    parse_timestamp,
    validate_booking_range,
)


COLLEGE_NAME = "中山大学农业与生物技术学院"
SYSTEM_NAME = "细胞间预约系统"
APP_FULL_NAME = f"{COLLEGE_NAME}{SYSTEM_NAME}"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
STATIC_DIR = Path(__file__).resolve().parent / "static"
FULL_LOGO_PATH = ASSETS_DIR / "college-logo-green.png"
EMBLEM_PATH = ASSETS_DIR / "college-emblem-green.png"
RESET_TEMPLATE_PATH = STATIC_DIR / "reset-password.template.html"
RESET_PAGE_PATH = STATIC_DIR / "reset-password.html"


def image_data_uri(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def ensure_reset_password_page(settings) -> None:
    """Generate the static password-reset page from runtime secrets."""
    if not RESET_TEMPLATE_PATH.exists():
        return
    page = RESET_TEMPLATE_PATH.read_text(encoding="utf-8")
    page = page.replace("__SUPABASE_URL__", settings.supabase_url)
    page = page.replace("__SUPABASE_ANON_KEY__", settings.supabase_anon_key)
    page = page.replace("__APP_URL__", settings.app_base_url)
    RESET_PAGE_PATH.write_text(page, encoding="utf-8")

st.set_page_config(
    page_title=APP_FULL_NAME,
    page_icon=str(EMBLEM_PATH),
    layout="wide",
    initial_sidebar_state="expanded",
)

CUSTOM_CSS = """
<style>
:root { --ink:#183153; --muted:#64748b; --line:#d9e2ec; --blue:#2563eb; --cyan:#0891b2; }
.block-container { padding-top: 1.7rem; padding-bottom: 2.5rem; }
.hero {
  border: 1px solid #dbeafe;
  background: linear-gradient(135deg, #eff6ff 0%, #ecfeff 100%);
  border-radius: 18px;
  padding: 20px 24px;
  margin-bottom: 18px;
}
.hero h1 { margin: 0 0 4px 0; color: var(--ink); font-size: 1.75rem; }
.hero p { margin: 0; color: #475569; }
.brand-row { display:flex; align-items:center; gap:22px; }
.brand-logo { width:min(360px, 42vw); height:auto; object-fit:contain; }
.brand-copy { min-width:0; }
.brand-college { color:#166534; font-size:.92rem; font-weight:700; letter-spacing:.04em; margin-bottom:3px; }
@media (max-width: 780px) { .brand-row { align-items:flex-start; gap:12px; } .brand-logo { width:160px; } .hero h1 { font-size:1.25rem; } }
.metric-card {
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 14px 16px;
  background: white;
  min-height: 92px;
}
.metric-card .label { color: var(--muted); font-size: .84rem; }
.metric-card .value { color: var(--ink); font-size: 1.55rem; font-weight: 700; margin-top: 5px; }
.timeline-shell { overflow: auto; border: 1px solid var(--line); border-radius: 14px; background: white; }
.timeline { min-width: 980px; display: grid; grid-template-columns: 74px repeat(var(--resource-count), minmax(150px, 1fr)); }
.timeline-head { position: sticky; top: 0; z-index: 5; background: #f8fafc; border-bottom: 1px solid var(--line); min-height: 56px; }
.time-head, .resource-head { padding: 9px 10px; border-right: 1px solid var(--line); }
.resource-head b { display: block; color: var(--ink); }
.resource-head span { color: var(--muted); font-size: .78rem; }
.time-column { position: relative; height: 1440px; border-right: 1px solid var(--line); background: #fbfdff; }
.time-label { position:absolute; left:0; right:0; height:60px; border-top:1px dashed #e2e8f0; padding:3px 7px 0; color:#7c8798; font-size:.72rem; }
.resource-column {
  position: relative;
  height: 1440px;
  border-right: 1px solid var(--line);
  background-image: repeating-linear-gradient(to bottom, transparent 0, transparent 59px, #edf2f7 59px, #edf2f7 60px);
}
.booking-block {
  position: absolute;
  left: 5px;
  right: 5px;
  min-height: 24px;
  border-radius: 8px;
  padding: 5px 7px;
  overflow: hidden;
  color: #0f172a;
  font-size: .75rem;
  line-height: 1.18;
  border-left: 4px solid #2563eb;
  background: #dbeafe;
  box-shadow: 0 1px 3px rgba(15,23,42,.12);
  z-index: 2;
}
.booking-block.in_use { background:#dcfce7; border-left-color:#16a34a; }
.booking-block.completed { background:#f1f5f9; border-left-color:#64748b; color:#64748b; }
.booking-block.cancelled, .booking-block.no_show { display:none; }
.booking-block b { display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.booking-block span { display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.status-pill { display:inline-block; border-radius:999px; padding:2px 8px; font-size:.76rem; font-weight:600; }
.status-approved { background:#dcfce7; color:#166534; }
.status-pending { background:#fef3c7; color:#92400e; }
.status-suspended { background:#fee2e2; color:#991b1b; }
.status-booked { background:#dbeafe; color:#1d4ed8; }
.status-in_use { background:#dcfce7; color:#166534; }
.status-completed { background:#e2e8f0; color:#475569; }
.status-cancelled,.status-no_show { background:#fee2e2; color:#991b1b; }
.small-note { color: var(--muted); font-size: .82rem; }
[data-testid="stSidebar"] { background: #f8fbff; }
</style>
"""

STATUS_LABELS = {
    "booked": "已预约",
    "in_use": "使用中",
    "completed": "已完成",
    "cancelled": "已取消",
    "no_show": "未到",
}
ROLE_LABELS = {"admin": "管理员", "member": "成员"}
PROFILE_STATUS_LABELS = {"pending": "待审批", "approved": "已授权", "suspended": "已停用"}


def service() -> BookingService:
    if "booking_service" not in st.session_state:
        st.session_state.booking_service = BookingService(load_settings())
    return st.session_state.booking_service


def current_user():
    return st.session_state.get("session_user")


def rerun() -> None:
    st.rerun()


def action_button(label: str, callback: Callable[[], Any], *, key: str, success: str, type: str = "secondary") -> None:
    if st.button(label, key=key, type=type, use_container_width=True):
        try:
            callback()
            st.success(success)
            st.rerun()
        except Exception as error:
            st.error(first_error_message(error))


def render_header(title: str, subtitle: str) -> None:
    logo_uri = image_data_uri(FULL_LOGO_PATH)
    st.markdown(
        f'<div class="hero"><div class="brand-row">'
        f'<img class="brand-logo" src="{logo_uri}" alt="{html.escape(COLLEGE_NAME)}">'
        f'<div class="brand-copy"><div class="brand-college">{html.escape(COLLEGE_NAME)}</div>'
        f'<h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )


def render_login() -> None:
    settings = load_settings()
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    render_header(SYSTEM_NAME, "两台超净工作台、四台培养箱，全天 00:00–24:00 在线预约与使用记录。")
    left, middle, right = st.columns([1, 1.35, 1])
    with middle:
        tab_login, tab_register, tab_forgot = st.tabs(["账号登录", "注册新账号", "找回密码"])
        with tab_login:
            with st.form("login_form", border=True):
                email = st.text_input("邮箱", placeholder="name@example.com")
                password = st.text_input("密码", type="password")
                submitted = st.form_submit_button("登录", type="primary", use_container_width=True)
            if submitted:
                if not email or not password:
                    st.warning("请输入邮箱和密码。")
                else:
                    try:
                        user = service().sign_in(email.strip().lower(), password)
                        st.session_state.session_user = user
                        st.rerun()
                    except Exception as error:
                        st.error(first_error_message(error))
        with tab_register:
            st.caption("注册后账号为“待审批”，管理员授权后才能提交预约。")
            with st.form("register_form", border=True):
                display_name = st.text_input("姓名", placeholder="例如：张三")
                email = st.text_input("邮箱", key="register_email", placeholder="name@example.com")
                phone = st.text_input("手机号（必填）", placeholder="请输入手机号")
                student_staff_id = st.text_input("工号 / 学号（两者填其一，必填）", placeholder="请输入工号或学号")
                advisor = st.text_input("导师 / 负责老师（必填）", placeholder="请输入导师或负责老师姓名")
                password = st.text_input("设置密码（至少 8 位）", type="password")
                confirm = st.text_input("确认密码", type="password")
                submitted = st.form_submit_button("提交注册", type="primary", use_container_width=True)
            if submitted:
                if len(password) < 8:
                    st.warning("密码至少需要 8 位。")
                elif password != confirm:
                    st.warning("两次输入的密码不一致。")
                elif not display_name.strip() or not email.strip():
                    st.warning("请填写姓名和邮箱。")
                elif not phone.strip():
                    st.warning("请填写手机号。")
                elif not student_staff_id.strip():
                    st.warning("请填写工号或学号。")
                elif not advisor.strip():
                    st.warning("请填写导师或负责老师。")
                else:
                    try:
                        user = service().sign_up(
                            email.strip().lower(),
                            password,
                            display_name.strip(),
                            phone.strip(),
                            student_staff_id.strip(),
                            advisor.strip(),
                        )
                        if user is None:
                            st.error("注册失败，请稍后重试。")
                        else:
                            st.session_state.session_user = user
                            st.success("注册成功。若邮箱确认功能已开启，请先完成邮箱验证。")
                            st.rerun()
                    except Exception as error:
                        st.error(first_error_message(error))
        with tab_forgot:
            st.caption("输入注册邮箱，系统会发送密码重置邮件。请在邮件中打开链接并设置新密码。")
            with st.form("forgot_password_form", border=True):
                forgot_email = st.text_input("注册邮箱", placeholder="name@example.com")
                forgot_submitted = st.form_submit_button("发送重置邮件", type="primary", use_container_width=True)
            if forgot_submitted:
                if not forgot_email.strip():
                    st.warning("请输入注册邮箱。")
                else:
                    try:
                        ensure_reset_password_page(settings)
                        service().request_password_reset(
                            forgot_email.strip().lower(),
                            f"{settings.app_base_url}/app/static/reset-password.html",
                        )
                        st.success("重置邮件已发送。请检查邮箱（包括垃圾邮件），然后按邮件中的链接设置新密码。")
                    except Exception as error:
                        st.error(first_error_message(error))


def render_access_state(user) -> bool:
    if user.status == "suspended":
        render_header("账号已停用", "请联系管理员重新授权后再使用预约系统。")
        return False
    if user.status != "approved":
        render_header("等待管理员审批", "注册已成功。管理员完成培训与账号授权后即可预约。")
        st.info(f"当前账号：{user.email}\n\n审批状态：待审批")
        if st.button("刷新审批状态"):
            service_user = service().current_user()
            if service_user:
                st.session_state.session_user = service_user
            st.rerun()
        return False
    return True


def render_sidebar(user) -> str:
    with st.sidebar:
        st.image(str(EMBLEM_PATH), width=96)
        st.markdown("### 细胞间预约系统")
        st.caption(COLLEGE_NAME)
        st.caption(f"登录：{user.display_name}")
        role = "主账号 / 管理员" if user.is_admin else "已授权成员"
        st.markdown(f"**{role}**")
        st.divider()
        pages = ["预约日历", "我的预约", "修改预约", "使用记录", "每周五卫生安排", "个人资料"]
        if user.is_admin:
            pages += ["成员授权", "设备管理", "预约管理", "使用统计"]
        page = st.radio("功能导航", pages, label_visibility="collapsed")
        st.divider()
        if st.button("退出登录", use_container_width=True):
            try:
                service().sign_out()
            finally:
                st.session_state.pop("session_user", None)
                st.session_state.pop("booking_service", None)
                st.rerun()
        st.caption("预约冲突由数据库事务检查，避免两个人同时抢占同一设备。")
    return page


def render_metrics(reservations: list[dict[str, Any]], user) -> None:
    today = date.today()
    today_rows = [row for row in reservations if format_local(row["start_at"], "%Y-%m-%d") == today.isoformat()]
    mine = [row for row in reservations if row.get("user_id") == user.id]
    active = [row for row in today_rows if row.get("status") in {"booked", "in_use"}]
    minutes = sum(int(row.get("reserved_minutes") or 0) for row in mine)
    columns = st.columns(4)
    values = [
        ("今日预约", f"{len(active)} 条"),
        ("当日我的预约", f"{len(mine)} 条"),
        ("我的累计时长", f"{minutes / 60:.1f} 小时"),
        ("当前身份", ROLE_LABELS.get(user.role, user.role)),
    ]
    for column, (label, value) in zip(columns, values):
        with column:
            st.markdown(
                f'<div class="metric-card"><div class="label">{html.escape(label)}</div>'
                f'<div class="value">{html.escape(value)}</div></div>',
                unsafe_allow_html=True,
            )


def render_timeline(equipment: list[dict[str, Any]], reservations: list[dict[str, Any]], user) -> None:
    if not equipment:
        st.info("暂无可用设备。")
        return
    resource_count = len(equipment)
    html_parts = [
        f'<div class="timeline-shell"><div class="timeline" style="--resource-count:{resource_count}">',
        '<div class="timeline-head time-head"><b>时间</b></div>',
    ]
    for item in equipment:
        html_parts.append(
            f'<div class="timeline-head resource-head"><b>{html.escape(item["name"])}</b>'
            f'<span>{html.escape(item.get("type") or "")} · {html.escape(item.get("location") or "")}</span></div>'
        )
    html_parts.append('<div class="time-column">')
    for hour in range(24):
        html_parts.append(f'<div class="time-label" style="top:{hour * 60}px">{hour:02d}:00</div>')
    html_parts.append("</div>")

    for item in equipment:
        html_parts.append('<div class="resource-column">')
        for row in reservations:
            if int(row.get("equipment_id") or 0) != int(item["id"]):
                continue
            status = str(row.get("status") or "booked")
            if status in {"cancelled", "no_show"}:
                continue
            start_local = parse_timestamp(row["start_at"])
            end_local = parse_timestamp(row["end_at"])
            start_minutes = start_local.hour * 60 + start_local.minute
            if end_local.date() > start_local.date():
                end_minutes = DAY_MINUTES
            else:
                end_minutes = end_local.hour * 60 + end_local.minute
            top = start_minutes / DAY_MINUTES * 100
            height = max(1.7, (end_minutes - start_minutes) / DAY_MINUTES * 100)
            owner = str(row.get("booked_by_name") or "其他成员")
            if row.get("user_id") == user.id:
                owner = f"{owner}（我）"
            phone = str(row.get("booked_by_phone") or "未填写")
            student_staff_id = str(row.get("booked_by_student_staff_id") or "未填写")
            advisor = str(row.get("booked_by_advisor") or "未填写")
            purpose = str(row.get("purpose") or "").strip()
            detail = f"{html.escape(owner)} · {html.escape(phone)}"
            tooltip = (
                f'{owner}｜{format_local(row["start_at"], "%H:%M")}–{format_local(row["end_at"], "%H:%M")}'
                f'｜手机：{phone}｜工号/学号：{student_staff_id}｜导师：{advisor}｜使用目的：{purpose}｜细胞类型：{str(row.get("cell_type") or "未填写")}'
            )
            html_parts.append(
                f'<div class="booking-block {html.escape(status)}" title="{html.escape(tooltip)}" '
                f'style="top:{top:.4f}%;height:{height:.4f}%">'
                f'<b>{format_local(row["start_at"], "%H:%M")}–{format_local(row["end_at"], "%H:%M")}</b>'
                f'<span>{detail}</span></div>'
            )
        html_parts.append("</div>")
    html_parts.append("</div></div>")
    st.markdown("".join(html_parts), unsafe_allow_html=True)


def render_calendar(user) -> None:
    render_header("预约日历", "按设备查看 24 小时占用情况，并在空白时段提交预约。")
    col_date, col_refresh = st.columns([3, 1])
    with col_date:
        selected_day = st.date_input("选择日期", value=date.today(), format="YYYY-MM-DD")
    with col_refresh:
        st.write("")
        st.write("")
        if st.button("刷新日历", use_container_width=True):
            st.rerun()

    try:
        equipment = service().list_equipment()
        reservations = service().list_reservations(day=selected_day, all_users=True)
    except Exception as error:
        st.error(first_error_message(error))
        return

    render_metrics(reservations, user)
    st.markdown("#### 24 小时设备时间轴")
    st.caption("绿色为使用中，蓝色为已预约，灰色为已完成；点击色块可查看预约人、时间和用途。")
    render_timeline(equipment, reservations, user)

    st.markdown("#### 当日预约明细")
    detail_rows = []
    for row in reservations:
        detail_rows.append(
            {
                "开始": format_local(row["start_at"], "%H:%M"),
                "结束": format_local(row["end_at"], "%H:%M"),
                "设备": (row.get("equipment") or {}).get("name", ""),
                "预约人": row.get("booked_by_name", ""),
                "手机号": row.get("booked_by_phone", ""),
                "工号 / 学号": row.get("booked_by_student_staff_id", ""),
                "导师 / 负责老师": row.get("booked_by_advisor", ""),
                "预约使用目的": row.get("purpose", ""),
                "培养细胞类型": row.get("cell_type", ""),
                "状态": STATUS_LABELS.get(row.get("status"), row.get("status", "")),
            }
        )
    if detail_rows:
        st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)
    else:
        st.info("当天暂无预约。")

    st.divider()
    st.markdown("#### 新建预约")
    st.warning(
        "**使用前温馨提示**\n"
        "1. 使用前先做好台面、培养箱内壁及手部消毒，检查设备状态和耗材。\n"
        "2. 全程严格执行无菌操作，穿戴实验服、口罩和手套。\n"
        "3. 不得将污染、破损或来源不明的培养物放入工作台或培养箱。\n"
        "4. 使用后及时清理台面、内腔和废弃物，发现污染立即停用并报告管理员。\n"
        "5. 按时开始和结束使用，离开前关闭设备、气源和照明，带走个人物品。"
    )
    with st.form("booking_form", border=True):
        resource_names = {int(item["id"]): f'{item["name"]} · {item.get("location") or ""}' for item in equipment}
        equipment_id = st.selectbox(
            "设备",
            options=list(resource_names),
            format_func=lambda value: resource_names[value],
        )
        starts = [format_minutes(value) for value in range(0, DAY_MINUTES, SLOT_MINUTES)]
        ends = [format_minutes(value) for value in range(SLOT_MINUTES, DAY_MINUTES + 1, SLOT_MINUTES)]
        start_col, end_col = st.columns(2)
        with start_col:
            start_label = st.selectbox("开始时间", starts, index=18)
        with end_col:
            default_end_index = min(starts.index(start_label) + 2, len(ends) - 1)
            end_label = st.selectbox("结束时间", ends, index=default_end_index)
        purpose = st.text_area(
            "预约使用目的（必填）",
            max_chars=300,
            placeholder="例如：细胞传代、换液、接种、取样、显微镜观察等",
        )
        cell_type = st.text_input(
            "培养的细胞类型（必填）",
            placeholder="例如：HEK293、A549、原代神经细胞等；如不培养细胞请填写“无”",
        )
        confirmed = st.checkbox("我已阅读并确认遵守以上使用事项")
        submitted = st.form_submit_button(
            "提交预约",
            type="primary",
            use_container_width=True,
            disabled=not confirmed,
        )
    if submitted:
        if not purpose.strip():
            st.error("请填写预约使用目的。")
        elif not cell_type.strip():
            st.error("请填写培养的细胞类型；如不培养细胞请填写“无”。")
        else:
            try:
                start_at, end_at = validate_booking_range(
                    selected_day,
                    minute_offset(start_label),
                    minute_offset(end_label),
                )
                service().create_booking(
                    equipment_id=equipment_id,
                    start_at=start_at,
                    end_at=end_at,
                    purpose=purpose.strip(),
                    cell_type=cell_type.strip(),
                )
                st.success("预约成功。")
                st.rerun()
            except Exception as error:
                st.error(first_error_message(error))


def reservation_dataframe(rows: list[dict[str, Any]], user) -> pd.DataFrame:
    data = []
    for row in rows:
        data.append(
            {
                "预约号": str(row.get("id", ""))[:8],
                "日期": format_local(row["start_at"], "%Y-%m-%d"),
                "设备": (row.get("equipment") or {}).get("name", ""),
                "开始": format_local(row["start_at"], "%H:%M"),
                "结束": format_local(row["end_at"], "%H:%M"),
                "时长(分钟)": int(row.get("reserved_minutes") or 0),
                "预约人": "我" if row.get("user_id") == user.id else row.get("booked_by_name", ""),
                "状态": STATUS_LABELS.get(row.get("status"), row.get("status", "")),
                "预约目的": row.get("purpose", ""),
                "培养细胞类型": row.get("cell_type", ""),
            }
        )
    return pd.DataFrame(data)


def render_my_bookings(user) -> None:
    render_header("我的预约", "查看即将到来和历史预约，取消仍可取消的预约。")
    try:
        rows = service().list_reservations(user_id=user.id, all_users=False, limit=500)
    except Exception as error:
        st.error(first_error_message(error))
        return
    now = datetime.now(SHANGHAI)
    upcoming = [
        row
        for row in rows
        if row.get("status") in {"booked", "in_use"}
        and datetime.fromisoformat(str(row["end_at"]).replace("Z", "+00:00")) >= now
    ]
    st.markdown(f"#### 即将到来（{len(upcoming)}）")
    for row in upcoming:
        equipment_name = (row.get("equipment") or {}).get("name", "设备")
        with st.container(border=True):
            left, middle, right = st.columns([2, 2, 1])
            with left:
                st.markdown(f"**{equipment_name}**")
                st.write(f'{format_local(row["start_at"], "%Y-%m-%d %H:%M")} – {format_local(row["end_at"], "%H:%M")}')
            with middle:
                st.markdown(f'**{STATUS_LABELS.get(row["status"], row["status"])}**')
                st.caption(
                    f"目的：{row.get('purpose') or '未填写'}｜细胞类型：{row.get('cell_type') or '未填写'}"
                )
            with right:
                if row["status"] == "booked":
                    action_button(
                        "取消预约",
                        lambda booking_id=row["id"]: service().cancel_booking(booking_id),
                        key=f'cancel_{row["id"]}',
                        success="预约已取消。",
                    )
                if row["status"] == "booked":
                    action_button(
                        "开始使用",
                        lambda booking_id=row["id"]: service().start_usage(booking_id),
                        key=f'start_{row["id"]}',
                        success="已开始计时。",
                    )
                elif row["status"] == "in_use":
                    action_button(
                        "结束使用",
                        lambda booking_id=row["id"]: service().complete_usage(booking_id),
                        key=f'complete_{row["id"]}',
                        success="已结束并记录实际使用时长。",
                    )

    st.divider()
    st.markdown("#### 全部预约")
    frame = reservation_dataframe(rows, user)
    st.dataframe(frame, use_container_width=True, hide_index=True)


def render_modify_booking(user) -> None:
    render_header("修改预约", "预约开始前可以自行修改设备和时间，修改后立即生效，无需管理员审批。")
    try:
        rows = service().list_reservations(user_id=user.id, all_users=False, limit=500)
        equipment = service().list_equipment()
    except Exception as error:
        st.error(first_error_message(error))
        return

    now = datetime.now(SHANGHAI)
    eligible = [
        row
        for row in rows
        if row.get("status") == "booked"
        and parse_timestamp(row["start_at"]) > now
    ]
    if not eligible:
        st.info("当前没有可修改的预约。只有尚未开始且状态为“已预约”的记录可以修改。")
        return

    options = {}
    for row in eligible:
        equipment_name = (row.get("equipment") or {}).get("name", "设备")
        options[str(row["id"])] = (
            f'{format_local(row["start_at"], "%Y-%m-%d %H:%M")}–'
            f'{format_local(row["end_at"], "%H:%M")} · {equipment_name}'
        )
    booking_id = st.selectbox("选择要修改的预约", options=list(options), format_func=lambda value: options[value])
    selected = next(row for row in eligible if str(row["id"]) == booking_id)
    current_start = parse_timestamp(selected["start_at"])
    current_end = parse_timestamp(selected["end_at"])

    if not equipment:
        st.warning("暂无可用设备。")
        return

    equipment_options = {int(item["id"]): f'{item["name"]} · {item.get("location") or ""}' for item in equipment}
    equipment_ids = list(equipment_options)
    current_equipment_id = int(selected["equipment_id"])
    equipment_index = equipment_ids.index(current_equipment_id) if current_equipment_id in equipment_ids else 0

    start_options = [format_minutes(value) for value in range(0, DAY_MINUTES, SLOT_MINUTES)]
    end_options = [format_minutes(value) for value in range(SLOT_MINUTES, DAY_MINUTES + 1, SLOT_MINUTES)]
    current_start_minutes = current_start.hour * 60 + current_start.minute
    if current_end.date() > current_start.date():
        current_end_minutes = DAY_MINUTES
    else:
        current_end_minutes = current_end.hour * 60 + current_end.minute

    with st.form("modify_booking_form", border=True):
        equipment_id = st.selectbox(
            "新设备",
            options=equipment_ids,
            index=equipment_index,
            format_func=lambda value: equipment_options[value],
        )
        selected_day = st.date_input("新日期", value=current_start.date(), format="YYYY-MM-DD")
        start_col, end_col = st.columns(2)
        with start_col:
            start_index = start_options.index(format_minutes(current_start_minutes)) if format_minutes(current_start_minutes) in start_options else 18
            start_label = st.selectbox("新开始时间", start_options, index=start_index)
        with end_col:
            end_index = end_options.index(format_minutes(current_end_minutes)) if format_minutes(current_end_minutes) in end_options else min(start_index + 2, len(end_options) - 1)
            end_label = st.selectbox("新结束时间", end_options, index=end_index)
        purpose = st.text_area(
            "预约使用目的（必填）",
            value=str(selected.get("purpose") or ""),
            max_chars=300,
        )
        cell_type = st.text_input(
            "培养的细胞类型（必填）",
            value=str(selected.get("cell_type") or ""),
            placeholder="如不培养细胞请填写“无”",
        )
        st.caption("系统会在保存时重新检查设备冲突；如果新时段已被占用，将不会修改。")
        submitted = st.form_submit_button("保存修改（无需审批）", type="primary", use_container_width=True)

    if submitted:
        if not purpose.strip():
            st.error("请填写预约使用目的。")
        elif not cell_type.strip():
            st.error("请填写培养的细胞类型；如不培养细胞请填写“无”。")
        else:
            try:
                start_at, end_at = validate_booking_range(
                    selected_day,
                    minute_offset(start_label),
                    minute_offset(end_label),
                )
                service().update_booking(
                    booking_id=booking_id,
                    equipment_id=equipment_id,
                    start_at=start_at,
                    end_at=end_at,
                    purpose=purpose.strip(),
                    cell_type=cell_type.strip(),
                )
                st.success("预约已修改并立即生效。")
                st.rerun()
            except Exception as error:
                st.error(first_error_message(error))

def render_usage_history(user) -> None:
    render_header("使用记录", "系统同时记录预约时长与实际开始/结束时长，便于后续授权和管理。")
    try:
        end_at = datetime.now(SHANGHAI) + timedelta(days=1)
        start_at = end_at - timedelta(days=365)
        rows = service().usage_report(start_at, end_at)
        if not user.is_admin:
            rows = [row for row in rows if row.get("user_id") == user.id]
    except Exception as error:
        st.error(first_error_message(error))
        return
    if not rows:
        st.info("暂无使用记录。")
        return
    frame = pd.DataFrame(rows)
    preferred = [
        "start_at",
        "end_at",
        "equipment_name",
        "user_name",
        "status",
        "reserved_minutes",
        "actual_minutes",
        "purpose",
        "cell_type",
    ]
    frame = frame[[column for column in preferred if column in frame.columns]]
    frame = frame.rename(
        columns={
            "start_at": "开始时间",
            "end_at": "结束时间",
            "equipment_name": "设备",
            "user_name": "使用人",
            "status": "状态",
            "reserved_minutes": "预约分钟",
            "actual_minutes": "实际分钟",
            "purpose": "预约目的",
            "cell_type": "培养细胞类型",
        }
    )
    if "状态" in frame.columns:
        frame["状态"] = frame["状态"].map(lambda value: STATUS_LABELS.get(value, value))
    st.dataframe(frame, use_container_width=True, hide_index=True)


def render_profile(user) -> None:
    render_header("个人资料", "维护姓名和联系方式，方便管理员进行培训与使用管理。")
    with st.form("profile_form", border=True):
        display_name = st.text_input("姓名", value=user.display_name)
        phone = st.text_input("手机号", value=str(user.profile.get("phone") or ""))
        student_staff_id = st.text_input("工号 / 学号", value=str(user.profile.get("student_staff_id") or ""))
        advisor = st.text_input("导师 / 负责老师", value=str(user.profile.get("advisor") or ""))
        submitted = st.form_submit_button("保存资料", type="primary")
    if submitted:
        try:
            service().update_my_profile(
                display_name.strip(),
                phone.strip(),
                student_staff_id.strip(),
                advisor.strip(),
            )
            st.session_state.session_user = service().current_user()
            st.success("资料已保存。")
            st.rerun()
        except Exception as error:
            st.error(first_error_message(error))
    st.caption(f"登录邮箱：{user.email}")
    st.caption(f"账号状态：{PROFILE_STATUS_LABELS.get(user.status, user.status)}")


def render_members_admin(user) -> None:
    render_header("成员授权", "审批培训完成的成员，也可以分配管理员或停用账号。")
    try:
        profiles = service().list_profiles()
    except Exception as error:
        st.error(first_error_message(error))
        return
    pending = [row for row in profiles if row.get("status") == "pending"]
    st.markdown(f"#### 待审批（{len(pending)}）")
    if pending:
        for row in pending:
            with st.container(border=True):
                cols = st.columns([3, 1, 1])
                with cols[0]:
                    st.markdown(f'**{row.get("display_name") or "未填写姓名"}**')
                    st.caption(
                        f'{row.get("email", "")} · 手机：{row.get("phone") or "未填写"} · '
                        f'工号/学号：{row.get("student_staff_id") or "未填写"} · '
                        f'导师：{row.get("advisor") or "未填写"}'
                    )
                with cols[1]:
                    action_button(
                        "通过授权",
                        lambda user_id=row["id"]: service().set_profile_status(user_id, "approved"),
                        key=f'approve_{row["id"]}',
                        success="账号已授权。",
                        type="primary",
                    )
                with cols[2]:
                    action_button(
                        "停用",
                        lambda user_id=row["id"]: service().set_profile_status(user_id, "suspended"),
                        key=f'suspend_{row["id"]}',
                        success="账号已停用。",
                    )
    else:
        st.info("暂无待审批成员。")

    st.divider()
    st.markdown("#### 全部成员")
    frame = pd.DataFrame(profiles)
    if not frame.empty:
        show_columns = [column for column in ["display_name", "email", "phone", "student_staff_id", "advisor", "role", "status", "created_at"] if column in frame.columns]
        frame = frame[show_columns].rename(
            columns={
                "display_name": "姓名",
                "email": "邮箱",
                "phone": "手机号",
                "student_staff_id": "工号/学号",
                "advisor": "导师/负责老师",
                "role": "角色",
                "status": "状态",
                "created_at": "注册时间",
            }
        )
        if "角色" in frame.columns:
            frame["角色"] = frame["角色"].map(lambda value: ROLE_LABELS.get(value, value))
        if "状态" in frame.columns:
            frame["状态"] = frame["状态"].map(lambda value: PROFILE_STATUS_LABELS.get(value, value))
        st.dataframe(frame, use_container_width=True, hide_index=True)

    editable = [row for row in profiles if row.get("id") != user.id]
    if editable:
        options = {str(row["id"]): f'{row.get("display_name") or "未命名"} · {row.get("email", "")}' for row in editable}
        selected_id = st.selectbox("选择成员进行权限调整", options=list(options), format_func=lambda value: options[value])
        selected = next(row for row in editable if str(row["id"]) == selected_id)
        col_role, col_status = st.columns(2)
        with col_role:
            role = st.selectbox("角色", ["member", "admin"], index=0 if selected.get("role") == "member" else 1, format_func=lambda value: ROLE_LABELS[value])
        with col_status:
            status = st.selectbox(
                "状态",
                ["pending", "approved", "suspended"],
                index=["pending", "approved", "suspended"].index(selected.get("status", "pending")),
                format_func=lambda value: PROFILE_STATUS_LABELS[value],
            )
        if st.button("保存成员权限", type="primary"):
            try:
                service().set_profile_role(selected_id, role)
                service().set_profile_status(selected_id, status)
                st.success("成员权限已更新。")
                st.rerun()
            except Exception as error:
                st.error(first_error_message(error))


def render_equipment_admin() -> None:
    render_header("设备管理", "维护超净工作台和培养箱的名称、位置与启用状态。")
    try:
        equipment = service().list_equipment(include_inactive=True)
    except Exception as error:
        st.error(first_error_message(error))
        return
    rows = []
    for item in equipment:
        rows.append(
            {
                "ID": item["id"],
                "名称": item["name"],
                "类型": item.get("type", ""),
                "位置": item.get("location", ""),
                "排序": item.get("sort_order", 0),
                "启用": bool(item.get("active", True)),
            }
        )
    edited = st.data_editor(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        disabled=["ID"],
        column_config={
            "类型": st.column_config.SelectboxColumn(options=["超净工作台", "培养箱", "其他"]),
            "启用": st.column_config.CheckboxColumn(),
        },
        key="equipment_editor",
    )
    if st.button("保存设备修改", type="primary"):
        try:
            for row in edited.to_dict("records"):
                service().upsert_equipment(
                    equipment_id=int(row["ID"]) if pd.notna(row["ID"]) else None,
                    name=str(row["名称"]).strip(),
                    equipment_type=str(row["类型"]).strip(),
                    location=str(row["位置"]).strip(),
                    sort_order=int(row["排序"]),
                    active=bool(row["启用"]),
                )
            st.success("设备信息已保存。")
            st.rerun()
        except Exception as error:
            st.error(first_error_message(error))

    with st.expander("新增设备"):
        with st.form("new_equipment"):
            name = st.text_input("名称")
            equipment_type = st.selectbox("类型", ["超净工作台", "培养箱", "其他"])
            location = st.text_input("位置")
            sort_order = st.number_input("排序", min_value=0, max_value=999, value=100)
            active = st.checkbox("启用", value=True)
            submitted = st.form_submit_button("新增", type="primary")
        if submitted and name.strip():
            try:
                service().upsert_equipment(
                    equipment_id=None,
                    name=name.strip(),
                    equipment_type=equipment_type,
                    location=location.strip(),
                    sort_order=int(sort_order),
                    active=active,
                )
                st.success("设备已新增。")
                st.rerun()
            except Exception as error:
                st.error(first_error_message(error))


def next_friday(value: date | None = None) -> date:
    current = value or date.today()
    return current + timedelta(days=(4 - current.weekday()) % 7)


def render_cleaning_schedule(user) -> None:
    render_header(
        "每周五卫生安排",
        "根据上一周的预约使用时长和频率自动推荐本周五卫生负责人；管理员可以手动调整。",
    )

    today = date.today()
    selected_friday = st.date_input(
        "选择要查看的周五",
        value=next_friday(today),
        format="YYYY-MM-DD",
        key="cleaning_friday",
    )
    if selected_friday.weekday() != 4:
        st.warning("请选择星期五。")
        return

    try:
        current = service().ensure_cleaning_assignment(selected_friday)
    except Exception as error:
        st.error(first_error_message(error))
        current = {}

    if current:
        source_label = "系统自动计算" if current.get("assignment_source") == "auto" else "管理员调整"
        cols = st.columns(3)
        with cols[0]:
            st.metric("本周五卫生负责人", current.get("assignee_name") or "未确定")
        with cols[1]:
            st.metric("上一周使用时长", f"{int(current.get('score_minutes') or 0) / 60:.1f} 小时")
        with cols[2]:
            st.metric("上一周预约次数", f"{int(current.get('reservation_count') or 0)} 次")
        st.caption(
            f"安排方式：{source_label}。计分方式：上一周使用分钟数 + 预约次数 × 30 分钟；"
            "总分最高者优先，若分数相同则优先安排较久未打扫的成员。"
        )
        if current.get("note"):
            st.info(f"管理员备注：{current['note']}")
    else:
        st.info("暂时没有可安排的卫生负责人。")

    st.divider()
    st.markdown("#### 周五卫生安排表")
    history_rows = []
    for delta in range(-4, 5):
        friday = selected_friday + timedelta(weeks=delta)
        if friday.weekday() != 4:
            continue
        try:
            row = service().ensure_cleaning_assignment(friday)
        except Exception:
            row = {}
        history_rows.append(
            {
                "日期": friday.isoformat(),
                "卫生负责人": row.get("assignee_name") or "未确定",
                "使用时长(小时)": round(int(row.get("score_minutes") or 0) / 60, 1),
                "预约次数": int(row.get("reservation_count") or 0),
                "安排方式": "管理员调整" if row.get("assignment_source") == "manual" else "系统自动",
                "备注": row.get("note") or "",
            }
        )
    st.dataframe(pd.DataFrame(history_rows), use_container_width=True, hide_index=True)

    if user.is_admin:
        st.divider()
        st.markdown("#### 管理员调整卫生安排")
        try:
            profiles = [
                row
                for row in service().list_profiles()
                if row.get("status") == "approved"
            ]
        except Exception as error:
            st.error(first_error_message(error))
            return
        if not profiles:
            st.info("暂无已授权成员可供调整。")
            return

        profile_options = {
            str(row["id"]): f'{row.get("display_name") or "未命名"} · {row.get("email", "")}'
            for row in profiles
        }
        profile_ids = list(profile_options)
        current_assignee = str(current.get("assignee_id") or "")
        default_index = profile_ids.index(current_assignee) if current_assignee in profile_ids else 0
        assignee_id = st.selectbox(
            "指定卫生负责人",
            options=profile_ids,
            index=default_index,
            format_func=lambda value: profile_options[value],
            key=f"cleaning_assignee_{selected_friday.isoformat()}",
        )
        note = st.text_input(
            "管理员备注",
            value=str(current.get("note") or ""),
            placeholder="例如：请重点清洁培养箱周围台面",
            key=f"cleaning_note_{selected_friday.isoformat()}",
        )
        if st.button("保存卫生安排", type="primary", key=f"save_cleaning_{selected_friday.isoformat()}"):
            try:
                service().set_cleaning_assignment(selected_friday, assignee_id, note.strip())
                st.success("卫生安排已更新。")
                st.rerun()
            except Exception as error:
                st.error(first_error_message(error))

def render_reservations_admin(user) -> None:
    render_header("预约管理", "管理员可取消预约、标记未到，并查看全部设备占用。")
    selected_day = st.date_input("管理日期", value=date.today(), key="admin_booking_day")
    try:
        rows = service().list_reservations(day=selected_day, all_users=True, limit=1000)
    except Exception as error:
        st.error(first_error_message(error))
        return
    frame = reservation_dataframe(rows, user)
    st.dataframe(frame, use_container_width=True, hide_index=True)
    if not rows:
        st.info("当天没有预约记录。")
        return
    options = {
        str(row["id"]): (
            f'{format_local(row["start_at"], "%H:%M")}–{format_local(row["end_at"], "%H:%M")} · '
            f'{(row.get("equipment") or {}).get("name", "")} · {row.get("booked_by_name", "")} · '
            f'{STATUS_LABELS.get(row.get("status"), row.get("status", ""))}'
        )
        for row in rows
    }
    booking_id = st.selectbox("选择预约", options=list(options), format_func=lambda value: options[value])
    selected = next(row for row in rows if str(row["id"]) == booking_id)

    col_cancel, col_no_show, col_complete, col_delete = st.columns(4)
    with col_cancel:
        action_button(
            "取消预约",
            lambda: service().cancel_booking(booking_id),
            key=f"admin_cancel_{booking_id}",
            success="预约已取消。",
        )
    with col_no_show:
        action_button(
            "标记未到",
            lambda: service().client.rpc("mark_no_show", {"p_booking_id": booking_id}).execute(),
            key=f"admin_no_show_{booking_id}",
            success="已标记未到。",
        )
    with col_complete:
        action_button(
            "结束使用",
            lambda: service().complete_usage(booking_id),
            key=f"admin_complete_{booking_id}",
            success="已结束使用。",
        )
    with col_delete:
        confirm_delete = st.checkbox("确认永久删除", key=f"confirm_delete_{booking_id}")
        if st.button(
            "删除记录",
            key=f"admin_delete_{booking_id}",
            type="primary",
            use_container_width=True,
        ):
            if not confirm_delete:
                st.warning("请先勾选“确认永久删除”。")
            else:
                try:
                    service().delete_booking(booking_id)
                    st.success("预约记录已永久删除。")
                    st.rerun()
                except Exception as error:
                    st.error(first_error_message(error))
    st.caption("删除操作不可恢复；如需保留历史，请优先使用取消预约或标记未到。")


def render_usage_admin() -> None:
    render_header("使用统计", "按时间范围汇总预约时长、实际使用时长和人员记录，并可导出 CSV。")
    today = date.today()
    col_start, col_end = st.columns(2)
    with col_start:
        start_day = st.date_input("开始日期", value=today - timedelta(days=30), key="usage_start")
    with col_end:
        end_day = st.date_input("结束日期", value=today, key="usage_end")
    start_at = datetime.combine(start_day, datetime.min.time(), tzinfo=SHANGHAI)
    end_at = datetime.combine(end_day + timedelta(days=1), datetime.min.time(), tzinfo=SHANGHAI)
    try:
        rows = service().usage_report(start_at, end_at)
    except Exception as error:
        st.error(first_error_message(error))
        return
    if not rows:
        st.info("所选范围暂无记录。")
        return
    frame = pd.DataFrame(rows)
    columns = [
        "start_at",
        "end_at",
        "equipment_name",
        "user_name",
        "user_email",
        "status",
        "reserved_minutes",
        "actual_minutes",
        "purpose",
        "cell_type",
        "notes",
    ]
    frame = frame[[column for column in columns if column in frame.columns]]
    frame = frame.rename(
        columns={
            "start_at": "预约开始",
            "end_at": "预约结束",
            "equipment_name": "设备",
            "user_name": "使用人",
            "user_email": "邮箱",
            "status": "状态",
            "reserved_minutes": "预约分钟",
            "actual_minutes": "实际分钟",
            "purpose": "预约目的",
            "cell_type": "培养细胞类型",
            "notes": "备注",
        }
    )
    st.dataframe(frame, use_container_width=True, hide_index=True)
    if "实际分钟" in frame.columns:
        actual_total = pd.to_numeric(frame["实际分钟"], errors="coerce").fillna(0).sum()
    elif "预约分钟" in frame.columns:
        actual_total = pd.to_numeric(frame["预约分钟"], errors="coerce").fillna(0).sum()
    else:
        actual_total = 0
    st.metric("合计使用时长", f"{actual_total / 60:.1f} 小时")
    csv_data = frame.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "导出 CSV",
        data=csv_data,
        file_name=f"cell-room-usage-{start_day}-{end_day}.csv",
        mime="text/csv",
        type="primary",
    )


def main() -> None:
    if not current_user():
        render_login()
        return

    user = current_user()
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    page = render_sidebar(user)
    if not render_access_state(user):
        return
    if page == "预约日历":
        render_calendar(user)
    elif page == "我的预约":
        render_my_bookings(user)
    elif page == "修改预约":
        render_modify_booking(user)
    elif page == "使用记录":
        render_usage_history(user)
    elif page == "每周五卫生安排":
        render_cleaning_schedule(user)
    elif page == "个人资料":
        render_profile(user)
    elif page == "成员授权" and user.is_admin:
        render_members_admin(user)
    elif page == "设备管理" and user.is_admin:
        render_equipment_admin()
    elif page == "预约管理" and user.is_admin:
        render_reservations_admin(user)
    elif page == "使用统计" and user.is_admin:
        render_usage_admin()


if __name__ == "__main__":
    main()
































