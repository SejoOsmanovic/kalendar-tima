import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ["SECRET_KEY"]
DEBUG = False
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin-allow-popups"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
if os.getenv("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(os.environ["RENDER_EXTERNAL_HOSTNAME"])
ROOT_URLCONF = "tim.urls"
INSTALLED_APPS = ["django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions",
                  "django.contrib.messages", "django.contrib.staticfiles", "tim"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware",
              "django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.common.CommonMiddleware",
              "django.middleware.csrf.CsrfViewMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware",
              "django.contrib.messages.middleware.MessageMiddleware", "django.middleware.clickjacking.XFrameOptionsMiddleware"]
if os.getenv("LOCAL_SQLITE") == "1":
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "local.sqlite3"}}
else:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
    if os.getenv("DATABASE_URL"):
        import dj_database_url
        DATABASES = {"default": dj_database_url.config(ssl_require=True)}
    else:
        DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", "HOST": "db",
                     "NAME": "kalendar", "USER": "kalendar", "PASSWORD": os.environ["POSTGRES_PASSWORD"]}}
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True,
              "OPTIONS": {"context_processors": ["django.template.context_processors.request",
              "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages",
              "tim.views.badge"]}}]
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
LOGIN_URL = "/prijava/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = LOGIN_URL
LANGUAGE_CODE = "en"
TIME_ZONE = os.getenv("TIME_ZONE", "Europe/Sarajevo")
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
if os.getenv("HTTPS") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
