"""Uygulama ayarları. Tüm değerler ortam değişkeni veya .env dosyası ile ezilebilir."""
import os

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET_KEY = "dev-only-secret-key-change-me-in-production-0123456789"
# Herkesin bildiği anahtarlar: koddaki varsayılan ve .env.example'daki yer tutucu
INSECURE_SECRET_KEYS = {DEFAULT_SECRET_KEY, "change-me-to-a-long-random-string-at-least-32-chars"}

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "StudySpot"
    API_PREFIX: str = "/api/v1"
    DATABASE_URL: str = "sqlite:///./data/studyspot.db"
    TIMEZONE: str = "Europe/Istanbul"

    # --- Auth ---
    SECRET_KEY: str = DEFAULT_SECRET_KEY
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # İlk çalıştırmada oluşturulan admin hesabı
    ADMIN_EMAIL: str = "admin@example.com"
    ADMIN_PASSWORD: str = "Admin123!"
    ADMIN_NAME: str = "StudySpot Admin"

    # --- Rezervasyon kuralları ---
    MAX_RESERVATION_HOURS: float = 3      # tek rezervasyonun azami süresi
    DAILY_LIMIT_HOURS: float = 4          # öğrenci başına günlük toplam
    WEEKLY_LIMIT_HOURS: float = 12        # öğrenci başına haftalık toplam (Pzt-Paz)
    MAX_ADVANCE_DAYS: int = 14            # en fazla kaç gün sonrasına rezervasyon

    # --- Check-in ve ceza ---
    CHECKIN_OPEN_MINUTES_BEFORE: int = 10
    CHECKIN_GRACE_MINUTES: int = 15
    NO_SHOW_PENALTY_POINTS: int = 2
    LATE_CANCEL_MINUTES: int = 30
    LATE_CANCEL_PENALTY_POINTS: int = 1
    PENALTY_BAN_THRESHOLD: int = 6
    BAN_DAYS: int = 7

    # --- Arka plan görevleri ---
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_INTERVAL_SECONDS: int = 60
    REMINDER_MINUTES_BEFORE: int = 30

    # --- Harici API: resmi tatiller (date.nager.at) ---
    HOLIDAY_CHECK_ENABLED: bool = True
    HOLIDAY_COUNTRY: str = "TR"

    # --- E-posta ---
    EMAIL_BACKEND: str = "console"        # "console" (sadece log) | "smtp"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "StudySpot <no-reply@example.com>"
    SMTP_TLS: bool = True


settings = Settings()
