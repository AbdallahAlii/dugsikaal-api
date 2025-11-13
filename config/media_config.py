# config/media_config.py
from typing import Optional, List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()

class MediaSettings(BaseSettings):
    MEDIA_BACKEND: str = "local"
    MEDIA_ALLOWED_EXTS: List[str] = Field(
        default_factory=lambda: ["png", "jpg", "jpeg", "webp","csv", "xlsx", "xls"]
    )
    MEDIA_MAX_MB: int = 5
    S3_ENDPOINT_URL: Optional[str] = None
    S3_REGION: str = "us-east-1"
    S3_BUCKET: str = "erp-media"
    S3_ACCESS_KEY: Optional[str] = None
    S3_SECRET_KEY: Optional[str] = None
    S3_PUBLIC_BASE: Optional[str] = None
    S3_SIGNED_URL_TTL: int = 300


    LOCAL_MEDIA_ROOT: str = "media"
    LOCAL_PUBLIC_BASE: str = "/media"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = MediaSettings()