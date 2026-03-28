import os
import sys
from pathlib import Path


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [
    origin.strip() for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if origin.strip()
]
ENABLE_METRICS = env_bool("ENABLE_METRICS", False)
ENABLE_REDIS_CACHE = env_bool("ENABLE_REDIS_CACHE", False)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts",
    "apps.core",
    "apps.dm",
    "apps.forum",
    "apps.presence",
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
    "apps.core.middleware.SecurityHeadersMiddleware",
    "apps.core.middleware.FirstRunSetupMiddleware",
    "apps.presence.middleware.PresenceMiddleware",
]

if ENABLE_METRICS:
    MIDDLEWARE.insert(0, "apps.core.middleware.RequestMetricsMiddleware")

ROOT_URLCONF = "app.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.branding_context",
                "apps.core.context_processors.footer_context",
                "apps.core.context_processors.settings_context",
                "apps.core.context_processors.notifications_context",
                "apps.dm.context_processors.dm_context",
            ],
        },
    },
]

WSGI_APPLICATION = "app.wsgi.application"
ASGI_APPLICATION = "app.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "dchat"),
        "USER": os.getenv("POSTGRES_USER", "dchat"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "dchat"),
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}

if env_bool("DJANGO_USE_SQLITE", False):
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

if "test" in sys.argv:
    STORAGES["staticfiles"] = {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    }

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "forum:home"
LOGOUT_REDIRECT_URL = "forum:home"

CAPTCHA_ENABLED = env_bool("CAPTCHA_ENABLED", True)
CAPTCHA_PROVIDER = os.getenv("CAPTCHA_PROVIDER", "math")
EMAIL_VERIFICATION_REQUIRED = env_bool("EMAIL_VERIFICATION_REQUIRED", False)

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "8"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

DEFAULT_ACCENT_HEX = os.getenv("DEFAULT_ACCENT_HEX", "#f39c12")
DEFAULT_BG_HEX = os.getenv("DEFAULT_BG_HEX", "#0f1217")
DEFAULT_SURFACE_HEX = os.getenv("DEFAULT_SURFACE_HEX", "#1a1f29")
DEFAULT_TEXT_HEX = os.getenv("DEFAULT_TEXT_HEX", "#e5e7eb")
DEFAULT_MUTED_TEXT_HEX = os.getenv("DEFAULT_MUTED_TEXT_HEX", "#9ca3af")
DEFAULT_LINK_HEX = os.getenv("DEFAULT_LINK_HEX", "#7cc4ff")
EMBED_PARENT_DOMAIN = os.getenv("EMBED_PARENT_DOMAIN", "localhost")
KLIPY_APP_KEY = os.getenv("KLIPY_APP_KEY", "").strip()
KLIPY_API_BASE = os.getenv("KLIPY_API_BASE", "https://api.klipy.com").strip() or "https://api.klipy.com"
KLIPY_CONTENT_FILTER = os.getenv("KLIPY_CONTENT_FILTER", "medium").strip() or "medium"
KLIPY_ATTRIBUTION_URL = "https://docs.klipy.com/attribution"

if ENABLE_REDIS_CACHE:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": os.getenv("REDIS_URL", "redis://localhost:6379/1"),
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", False)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", False)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)

DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_BYTES + (1024 * 1024)
FILE_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_BYTES
