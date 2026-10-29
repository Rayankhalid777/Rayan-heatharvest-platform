"""Settings, read from environment variables (see .env.example)."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def database_url() -> str:
    url = _env("DATABASE_URL", f"sqlite:///{BASE_DIR / 'heatharvest.db'}")
    # Render and Heroku give postgres://; SQLAlchemy with psycopg 3 wants postgresql+psycopg://
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


SECRET_KEY = _env("SECRET_KEY") or secrets.token_hex(32)
PRODUCTION = _env("ENVIRONMENT", "development") == "production"
SITE_URL = _env("SITE_URL", "http://localhost:8000").rstrip("/")

ADMIN_EMAIL = _env("ADMIN_EMAIL")
ADMIN_PASSWORD = _env("ADMIN_PASSWORD")
ADMIN_NAME = _env("ADMIN_NAME", "HeatHarvest admin")

SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = int(_env("SMTP_PORT", "587"))
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD")
SMTP_TLS = _env("SMTP_TLS", "starttls")  # starttls | ssl | none
MAIL_FROM = _env("MAIL_FROM", SMTP_USER or "no-reply@heatharvest.example")
TEAM_NOTIFY_EMAIL = _env("TEAM_NOTIFY_EMAIL")

SIGNATORY_NAME = _env("SIGNATORY_NAME", "Prof. Awad Alquaity")
SIGNATORY_EMAIL = _env("SIGNATORY_EMAIL", "awad.alquaity@kfupm.edu.sa")
SIGNATORY_PHONE = _env("SIGNATORY_PHONE", "+966 53 194 6761")

SITE_DIR = BASE_DIR / "site"
