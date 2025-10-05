import enum
import os
from pathlib import Path
from tempfile import gettempdir
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict
from yarl import URL

TEMP_DIR = Path(gettempdir())


class LogLevel(str, enum.Enum):
    """Possible log levels."""

    NOTSET = "NOTSET"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    FATAL = "FATAL"


class Settings(BaseSettings):
    """
    Application settings.

    These parameters can be configured
    with environment variables.
    """

    host: str = "127.0.0.1"
    port: int = 8000
    # quantity of workers for uvicorn
    workers_count: int = 1
    # Enable uvicorn reloading
    reload: bool = False

    # Current environment
    environment: str = "dev"

    # ffmpeg binaries
    ffmpeg: str = (
        os.environ.get("FFMPEG_BINARY") or f"{os.environ.get('HOME', '')}/ffmpeg/ffmpeg"
    )
    ffprobe: str = (
        os.environ.get("FFPROBE_BINARY")
        or f"{os.environ.get('HOME', '')}/ffmpeg/ffprobe"
    )

    log_level: LogLevel = LogLevel.INFO
    # Variables for the database
    db_host: str = os.environ.get("VIDX_DB_HOST") or "localhost"
    db_port: int = int(os.environ.get("VIDX_DB_PORT") or 27017)
    db_user: str = os.environ.get("VIDX_DB_USER") or "vidx"
    db_pass: str = os.environ.get("VIDX_DB_PASS") or "vidx"
    db_base: str = os.environ.get("VIDX_DB_BASE") or "admin"
    db_echo: bool = False

    # Variables for RabbitMQ
    rabbitmq_host: str = os.environ.get("RABBITMQ_HOST") or "localhost"
    rabbitmq_port: int = int(os.environ.get("RABBITMQ_PORT") or 5672)
    rabbitmq_user: Optional[str] = os.environ.get("RABBITMQ_USER") or "vidx"
    rabbitmq_pass: Optional[str] = os.environ.get("RABBITMQ_PASS") or "vidx"
    rabbitmq_base: Optional[str] = os.environ.get("RABBITMQ_BASE") or "/"
    rabbitmq_queue_name: str = "vidx_processing"
    rabbitmq_exchange_name: str = "vidx_exchange"
    rabbitmq_routing_key: str = "vidx.process"

    jwt_secret: str = os.environ.get("VIDX_JWT_SECRET") or "change_me"
    jwt_algorithm: str = os.environ.get("VIDX_JWT_ALGORITHM") or "HS256"
    jwt_expiration_minutes: int = int(os.environ.get("VIDX_JWT_EXP_MINUTES") or 60)

    google_client_id: str | None = os.environ.get("VIDX_GOOGLE_CLIENT_ID")
    google_client_secret: str | None = os.environ.get("VIDX_GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = (
        os.environ.get("VIDX_GOOGLE_REDIRECT_URI")
        or "http://localhost:8000/api/auth/google/callback"
    )
    google_scope: tuple[str, ...] = ("openid", "email", "profile")
    google_token_uri: str = "https://oauth2.googleapis.com/token"
    google_authorize_uri: str = "https://accounts.google.com/o/oauth2/v2/auth"
    google_revoke_uri: str = "https://oauth2.googleapis.com/revoke"

    @property
    def db_url(self) -> URL:
        """
        Assemble database URL from settings.

        :return: database URL.
        """
        return URL.build(
            scheme="mongodb",
            host=self.db_host,
            port=self.db_port,
            user=self.db_user,
            password=self.db_pass,
            path=f"/{self.db_base}",
        )

    @property
    def rabbitmq_url(self) -> URL:
        """
        Assemble RabbitMQ URL from settings.

        :return: rabbitmq URL.
        """
        path = ""
        if self.rabbitmq_base is not None:
            path = f"/{self.rabbitmq_base}"

        return URL.build(
            scheme="amqp",
            host=self.rabbitmq_host,
            port=self.rabbitmq_port,
            user=self.rabbitmq_user,
            password=self.rabbitmq_pass,
            path=path,
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="VIDX_",
        env_file_encoding="utf-8",
    )


settings = Settings()
