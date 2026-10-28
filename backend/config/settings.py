"""
Django settings for the AJ Technologies admin dashboard.

Database : the same Supabase PostgreSQL as the website (DATABASE_URL in backend/.env).
           Tables are created by supabase_schema.sql in Supabase, not by Django.
Images   : Supabase Storage bucket "project-images" (SUPABASE_URL + SUPABASE_SERVICE_KEY).
Login    : one admin account from .env (ADMIN_EMAIL / ADMIN_PASSWORD).
           Sessions are kept in a signed cookie, so no extra tables are needed.
"""
import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env', encoding='utf-8-sig')


def env(name, default=''):
    return os.getenv(name, default).strip()


# ---------- Security ----------
SECRET_KEY = env('SECRET_KEY', 'development-only-key-change-me')
DEBUG = env('DEBUG', 'False').lower() == 'true'
ALLOWED_HOSTS = [h.strip() for h in env('ALLOWED_HOSTS', '127.0.0.1,localhost').split(',') if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in env('CSRF_TRUSTED_ORIGINS').split(',') if o.strip()]


# ---------- Apps (no default Django admin, no auth/session tables) ----------
INSTALLED_APPS = [
    'django.contrib.staticfiles',
    'main',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# ---------- Database: Supabase PostgreSQL ----------
DATABASE_URL = env('DATABASE_URL')
if not DATABASE_URL:
    raise ImproperlyConfigured(
        'DATABASE_URL is missing. Add your Supabase connection string to backend/.env, e.g. '
        'DATABASE_URL=postgresql://postgres:YOUR-PASSWORD@db.YOUR-REF.supabase.co:5432/postgres'
    )
DATABASES = {
    'default': dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=60,
        conn_health_checks=True,
        ssl_require=env('DATABASE_SSL', 'true').lower() == 'true',  # Supabase requires SSL
    )
}


# ---------- Supabase Storage (project images) ----------
SUPABASE_URL = env('SUPABASE_URL').rstrip('/')                       # https://YOUR-REF.supabase.co
SUPABASE_SERVICE_KEY = env('SUPABASE_SERVICE_KEY')                    # secret key: server only
SUPABASE_STORAGE_BUCKET = env('SUPABASE_STORAGE_BUCKET', 'project-images')
SUPABASE_IMAGE_FOLDER = 'projects'
MAX_IMAGE_MB = 5


# ---------- Admin login ----------
ADMIN_NAME = env('ADMIN_NAME', 'Admin')
ADMIN_EMAIL = env('ADMIN_EMAIL').lower()
ADMIN_PASSWORD = env('ADMIN_PASSWORD')

SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'   # no session table needed
SESSION_COOKIE_NAME = 'ajadmin_session'
SESSION_COOKIE_AGE = 60 * 60 * 12                                     # stay signed in for 12 hours
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_NAME = 'ajadmin_csrftoken'
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = not DEBUG                # HTTPS-only cookies when live
X_FRAME_OPTIONS = 'DENY'

# Used only to count wrong login attempts (kept in memory)
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}

# Uploads up to MAX_IMAGE_MB pass through Django before going to Supabase Storage
DATA_UPLOAD_MAX_MEMORY_SIZE = FILE_UPLOAD_MAX_MEMORY_SIZE = (MAX_IMAGE_MB + 1) * 1024 * 1024


# ---------- Region ----------
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True


# ---------- Static files ----------
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ---------- Logging: show API errors in the terminal ----------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'loggers': {'main': {'handlers': ['console'], 'level': 'INFO'}},
}