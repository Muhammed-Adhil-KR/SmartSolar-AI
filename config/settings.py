"""
Django settings for the Intelligent Decision Support System for Solar Energy.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-only-key-change-in-.env-o0kqaik7bt",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "True") == "True"

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'accounts',
    'solar',
    'forecast',
    'decision_support',
    'dashboard',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
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
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'solar.context_processors.solar_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'dashboard:home'
LOGOUT_REDIRECT_URL = 'accounts:login'

GRID_EMISSION_FACTOR_KG_PER_KWH = float(
    os.environ.get("GRID_EMISSION_FACTOR_KG_PER_KWH", "0.72")
)

# --- ML model integration (Phase 9) ---
ML_MODEL_PATH = BASE_DIR / "ml_models" / "random_forest_tuned.pkl"
ML_MODEL_NAME = "RandomForestRegressor (tuned)"   # stored with each prediction in Phase 10

# Must match the model's training columns AND their order exactly.
MODEL_FEATURES = [
    "Temperature_C",
    "Humidity_%",
    "WindSpeed_mps",
    "Solar_Irradiance_kWhm2",
    "Rainfall_mm",
    "Day_of_Year",
]

# Capacity scaling is ON: the model was trained on ~3 kW households, so its output is
# multiplied by (user's capacity_kw / MODEL_REFERENCE_CAPACITY_KW).
# Set MODEL_REFERENCE_CAPACITY_KW to the exact capacity of the training households.
PREDICTION_SCALE_BY_CAPACITY = True
MODEL_REFERENCE_CAPACITY_KW = 3.0


# --- Decision Support System (Phase 11) ---
CURRENCY_SYMBOL = "₹"
DSS_DEFAULT_SOLAR_WINDOW = (9, 16)     # used when hourly sunlight data is unavailable
DSS_WINDOW_PEAK_FRACTION = 0.5         # window = hours with sunlight >= 50% of the day's peak
DSS_MIN_PEAK_IRRADIANCE_WM2 = 150      # below this peak, sunlight is too weak to recommend shifting loads
DSS_MIN_USEFUL_GENERATION_KWH = 1.0    # below this predicted generation, skip shift advice
DSS_LOW_COVERAGE_RATIO = 0.5           # "poor day": generation below 50% of expected usage
DSS_LOW_BATTERY_SOC_PERCENT = 50       # "low battery": charge below 50%
DSS_MAX_SCHEDULE_RECOMMENDATIONS = 5   # at most 5 appliance-scheduling tips per day