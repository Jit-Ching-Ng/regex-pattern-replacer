"""
Django settings for the regex replacement service.

Every deployment-specific value is read from the environment (optionally from a
``backend/.env`` file) so the same code runs locally, in Docker and on a PaaS.
See ``.env.example`` for the full list.
"""
from __future__ import annotations

import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value not in (None, "") else default


def env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return float(value) if value not in (None, "") else default


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env_str(name, default).split(",") if item.strip()]


# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------
DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = env_str("DJANGO_SECRET_KEY") or ("dev-insecure-secret-key" if DEBUG else "")
if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
# Render (and similar platforms) expose the public hostname in an env var.
_platform_host = env_str("RENDER_EXTERNAL_HOSTNAME")
if _platform_host:
    ALLOWED_HOSTS.append(_platform_host)

CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
if _platform_host:
    CSRF_TRUSTED_ORIGINS.append(f"https://{_platform_host}")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "processor",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Static files, media and the built React app
# --------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Uploaded files and the Parquet snapshots produced by every operation.
MEDIA_ROOT = Path(env_str("DATA_DIR") or BASE_DIR / "data").resolve()
MEDIA_URL = "/media/"  # never routed publicly; files are served through the API

# In production the React build is copied here and served by WhiteNoise.
FRONTEND_DIST_DIR = BASE_DIR / "frontend_dist"
if FRONTEND_DIST_DIR.exists():
    WHITENOISE_ROOT = FRONTEND_DIST_DIR

# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
REST_FRAMEWORK = {
    # The app is anonymous by design: datasets are addressed by random UUIDs.
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "EXCEPTION_HANDLER": "processor.api.exception_handler.api_exception_handler",
        "URL_FORMAT_OVERRIDE": None,
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": env_str("API_RATE_LIMIT", "600/hour")},
}

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")
CORS_EXPOSE_HEADERS = ["Content-Disposition"]

# --------------------------------------------------------------------------
# Upload & processing limits
# --------------------------------------------------------------------------
MAX_UPLOAD_SIZE_MB = env_int("MAX_UPLOAD_SIZE_MB", 50)
# Uploads above this size are streamed to a temp file instead of memory.
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

MAX_ROWS = env_int("MAX_ROWS", 1_000_000)
REGEX_CELL_TIMEOUT_SECONDS = env_float("REGEX_CELL_TIMEOUT_SECONDS", 0.5)
OPERATION_TIME_BUDGET_SECONDS = env_float("OPERATION_TIME_BUDGET_SECONDS", 90)
TRANSFORM_MAX_UNIQUE_VALUES = env_int("TRANSFORM_MAX_UNIQUE_VALUES", 500)
TRANSFORM_BATCH_SIZE = env_int("TRANSFORM_BATCH_SIZE", 40)

# --------------------------------------------------------------------------
# LLM
# --------------------------------------------------------------------------
LLM_PROVIDER = env_str("LLM_PROVIDER", "anthropic").lower()
LLM_API_KEY = env_str("LLM_API_KEY") or env_str("ANTHROPIC_API_KEY") or env_str("OPENAI_API_KEY")
LLM_MODEL = env_str("LLM_MODEL")
LLM_BASE_URL = env_str("LLM_BASE_URL")
LLM_TIMEOUT_SECONDS = env_float("LLM_TIMEOUT_SECONDS", 45)
LLM_SEND_SAMPLE_VALUES = env_bool("LLM_SEND_SAMPLE_VALUES", True)

# --------------------------------------------------------------------------
# Security hardening for production
# --------------------------------------------------------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {"django": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}
