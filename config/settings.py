# config/settings.py
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional, Literal
from dotenv import load_dotenv
import json
from cryptography.fernet import Fernet
load_dotenv()

SameSite = Literal["lax", "strict", "none"]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str = Field(..., min_length=16)
    SECURITY_PASSWORD_SALT: str = Field(..., min_length=8)
    ENCRYPTION_KEY: str = Field(..., min_length=44)
    DATABASE_HOST: str
    DATABASE_PORT: int
    DATABASE_USER: str
    DATABASE_PASSWORD: str
    DATABASE_NAME: str

    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        return (
            f"postgresql://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
        )

    REDIS_HOST: Optional[str] = None
    REDIS_PORT: Optional[int] = None
    REDIS_DB: int = 0

    @property
    def REDIS_URL(self) -> str:
        if not self.REDIS_HOST or not self.REDIS_PORT:
            return "redis://localhost:6379/0"  # safe default
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    CORS_ALLOWED_ORIGINS: List[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    CORS_ALLOW_ORIGIN_REGEX: Optional[str] = None

    @field_validator("CORS_ALLOWED_ORIGINS", mode="before")
    @classmethod
    def _parse_origins(cls, v):
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                try:
                    arr = json.loads(s)
                    if isinstance(arr, list):
                        return [str(x).strip() for x in arr if str(x).strip()]
                except Exception:
                    pass
            return [p.strip() for p in s.split(",") if p.strip()]
        return ["http://localhost:5173"]

    SESSION_COOKIE_NAME: str = "session_id"
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_MAX_AGE: int = 60 * 60 * 24
    SESSION_COOKIE_SECURE: bool = False
    SESSION_COOKIE_SAMESITE: SameSite = "lax"
    SESSION_COOKIE_DOMAIN: Optional[str] = None
    CROSS_SITE_COOKIES: bool = False

    @field_validator("SESSION_COOKIE_SAMESITE", mode="before")
    @classmethod
    def _normalize_samesite(cls, v):
        if not isinstance(v, str):
            return "lax"
        s = v.strip().lower()
        return s if s in {"lax", "strict", "none"} else "lax"

    @property
    def cookie_samesite_effective(self) -> SameSite:
        return "none" if self.CROSS_SITE_COOKIES else self.SESSION_COOKIE_SAMESITE

    @property
    def cookie_secure_effective(self) -> bool:
        return True if self.CROSS_SITE_COOKIES else self.SESSION_COOKIE_SECURE

settings = Settings()
try:
    FERNET_INSTANCE = Fernet(settings.ENCRYPTION_KEY.encode())
except Exception as e:
    raise ValueError("Invalid ENCRYPTION_KEY") from e