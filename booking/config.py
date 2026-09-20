"""Application settings loaded from Streamlit secrets or environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

import streamlit as st


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_anon_key: str
    app_timezone: str = "Asia/Shanghai"
    initial_admin_email: str = ""
    app_name: str = "细胞间预约系统"


def _secret(name: str, default: str = "") -> str:
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.getenv(name, default)


def load_settings() -> Settings:
    url = _secret("SUPABASE_URL").strip()
    key = _secret("SUPABASE_ANON_KEY").strip()
    if not url or not key:
        raise RuntimeError(
            "缺少 SUPABASE_URL 或 SUPABASE_ANON_KEY，请检查 Streamlit secrets 或容器环境变量。"
        )
    return Settings(
        supabase_url=url,
        supabase_anon_key=key,
        app_timezone=_secret("APP_TIMEZONE", "Asia/Shanghai"),
        initial_admin_email=_secret("INITIAL_ADMIN_EMAIL").strip().lower(),
        app_name=_secret("APP_NAME", "细胞间预约系统"),
    )
