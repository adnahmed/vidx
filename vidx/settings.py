import enum
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

    log_level: LogLevel = LogLevel.INFO
    # Variables for the database
    db_host: str = "localhost"
    db_port: int = 27017
    db_user: str = "vidx"
    db_pass: str = "vidx"
    db_base: str = "admin"
    db_echo: bool = False

    # Variables for RabbitMQ
    rabbitmq_host: str = "rabbitmq"
    rabbitmq_port: int = 5672
    rabbitmq_user: Optional[str] = "vidx"
    rabbitmq_pass: Optional[str] = "vidx"
    rabbitmq_base: Optional[int] = None

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
