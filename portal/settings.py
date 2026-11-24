"""Django settings for the Monthly Report Generator portal.

All secrets and environment-specific values come from environment variables
(or a local ``.env`` file). Nothing secret is stored in the database.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in env(name, default).split(",") if x.strip()]


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
    "reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "portal.urls"

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

WSGI_APPLICATION = "portal.wsgi.application"

if env("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB"),
            "USER": env("POSTGRES_USER", "postgres"),
            "PASSWORD": env("POSTGRES_PASSWORD", ""),
            "HOST": env("POSTGRES_HOST", "localhost"),
            "PORT": env("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "id"
TIME_ZONE = env("TIME_ZONE", "Asia/Jakarta")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "media")))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "reports:list"
LOGOUT_REDIRECT_URL = "login"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}

# --------------------------------------------------------------------------
# Report generator settings
# --------------------------------------------------------------------------

# "live" = Prometheus + Jira Cloud, "demo" = synthetic data (no external access needed)
DATA_SOURCE_MODE = env("DATA_SOURCE_MODE", "demo")

PROVIDER_NAME = env("PROVIDER_NAME", "PT IDX Solusi Teknologi Informasi")
PROVIDER_SHORT = env("PROVIDER_SHORT", "IDXSTI")

REPORT_TEMPLATE_PATH = Path(env("REPORT_TEMPLATE_PATH", str(BASE_DIR / "templates" / "report_template.docx")))

# SLA defaults (service hours are 24x7)
DEFAULT_SLA_TARGET = env("DEFAULT_SLA_TARGET", "99.412")

# --- Prometheus (queried directly, the same source Grafana uses)
PROMETHEUS_URL = env("PROMETHEUS_URL", "")
PROMETHEUS_BEARER_TOKEN = env("PROMETHEUS_BEARER_TOKEN", "")
PROMETHEUS_USERNAME = env("PROMETHEUS_USERNAME", "")
PROMETHEUS_PASSWORD = env("PROMETHEUS_PASSWORD", "")
PROMETHEUS_VERIFY_TLS = env_bool("PROMETHEUS_VERIFY_TLS", True)
PROMETHEUS_STEP_SECONDS = int(env("PROMETHEUS_STEP_SECONDS", "900"))
PROMETHEUS_TIMEOUT_SECONDS = int(env("PROMETHEUS_TIMEOUT_SECONDS", "60"))

# PromQL per component kind and metric. Placeholders:
#   {selector}   -> label selector built from the component (e.g. instance="10.0.0.1:9100")
# Each query must return ONE series, as a percentage (0-100).
METRIC_QUERIES = {
    "vm": {
        "cpu": '100 * (1 - avg(rate(node_cpu_seconds_total{{mode="idle",{selector}}}[5m])))',
        "memory": '100 * (1 - sum(node_memory_MemAvailable_bytes{{{selector}}}) / sum(node_memory_MemTotal_bytes{{{selector}}}))',
        "disk": '100 * max(1 - node_filesystem_avail_bytes{{fstype!~"tmpfs|overlay|squashfs|devtmpfs",{selector}}}'
                ' / node_filesystem_size_bytes{{fstype!~"tmpfs|overlay|squashfs|devtmpfs",{selector}}})',
    },
    # Kubernetes (e.g. GKE Autopilot): usage relative to the pods' resource *requests*,
    # because Autopilot bills on requests.
    "k8s": {
        "cpu": '100 * sum(rate(container_cpu_usage_seconds_total{{container!="",{selector}}}[5m]))'
               ' / sum(kube_pod_container_resource_requests{{resource="cpu",{selector}}})',
        "memory": '100 * sum(container_memory_working_set_bytes{{container!="",{selector}}})'
                  ' / sum(kube_pod_container_resource_requests{{resource="memory",{selector}}})',
        "disk": '100 * max(kubelet_volume_stats_used_bytes{{{selector}}} / kubelet_volume_stats_capacity_bytes{{{selector}}})',
    },
}

# --- Jira Cloud
JIRA_BASE_URL = env("JIRA_BASE_URL", "")          # e.g. https://yourcompany.atlassian.net
JIRA_EMAIL = env("JIRA_EMAIL", "")
JIRA_API_TOKEN = env("JIRA_API_TOKEN", "")
JIRA_TIMEOUT_SECONDS = int(env("JIRA_TIMEOUT_SECONDS", "30"))
# Default JQL used to split incidents from service requests (overridable per project)
JIRA_DEFAULT_INCIDENT_JQL = env("JIRA_DEFAULT_INCIDENT_JQL", 'issuetype = Incident')
JIRA_DEFAULT_REQUEST_JQL = env("JIRA_DEFAULT_REQUEST_JQL", 'issuetype = "Service Request"')
# Custom field holding the follow-up / resolution notes (e.g. customfield_10050).
# Empty = use the latest comment.
JIRA_FOLLOWUP_FIELD = env("JIRA_FOLLOWUP_FIELD", "")

# --- Forecasting
FORECAST_MAX_HORIZON_DAYS = int(env("FORECAST_MAX_HORIZON_DAYS", "90"))
FORECAST_MIN_HORIZON_DAYS = 30
FORECAST_HISTORY_DAYS = int(env("FORECAST_HISTORY_DAYS", "180"))
# Status thresholds (percent) per metric: (attention, critical)
FORECAST_THRESHOLDS = {
    "cpu": (70.0, 85.0),
    "memory": (75.0, 90.0),
    "disk": (80.0, 90.0),
}
# Below this p95 (percent) for CPU/memory a resource is flagged as under-utilised
FORECAST_UNDERUTILISED_P95 = float(env("FORECAST_UNDERUTILISED_P95", "20"))

# --- PDF conversion (LibreOffice). UNO_PYTHON must be a Python that can `import uno`.
LIBREOFFICE_BINARY = env("LIBREOFFICE_BINARY", "soffice")
UNO_PYTHON = env("UNO_PYTHON", "/usr/bin/python3")
PDF_TIMEOUT_SECONDS = int(env("PDF_TIMEOUT_SECONDS", "180"))

# --- E-mail
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "localhost")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "cloud-report@example.com")
# Internal domains that are always allowed as recipients (e.g. CC to the ops team)
INTERNAL_EMAIL_DOMAINS = env_list("INTERNAL_EMAIL_DOMAINS")
X_FRAME_OPTIONS = "SAMEORIGIN"  # allow the PDF preview iframe on our own pages
