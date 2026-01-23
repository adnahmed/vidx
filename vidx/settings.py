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

    # Queue & Storage abstraction types
    queue_type: str = os.environ.get("QUEUE_TYPE") or "rabbitmq"  # rabbitmq | sqs
    storage_type: str = os.environ.get("STORAGE_TYPE") or "local"  # local | s3
    cache_type: str = os.environ.get("CACHE_TYPE") or "redis"  # redis | elasticache

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
    db_type: str = os.environ.get("DB_TYPE") or "mongodb"  # mongodb | documentdb

    # Variables for RabbitMQ
    rabbitmq_host: str = os.environ.get("RABBITMQ_HOST") or "localhost"
    rabbitmq_port: int = int(os.environ.get("RABBITMQ_PORT") or 5672)
    rabbitmq_user: Optional[str] = os.environ.get("RABBITMQ_USER") or "vidx"
    rabbitmq_pass: Optional[str] = os.environ.get("RABBITMQ_PASS") or "vidx"
    rabbitmq_base: Optional[str] = os.environ.get("RABBITMQ_BASE") or "/"
    rabbitmq_queue_name: str = "vidx_processing"
    rabbitmq_exchange_name: str = "vidx_exchange"
    rabbitmq_routing_key: str = "vidx.process"

    # AWS configuration (used for S3/SQS and LocalStack)
    aws_region: str = os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    aws_access_key_id: Optional[str] = os.environ.get("AWS_ACCESS_KEY_ID")
    aws_secret_access_key: Optional[str] = os.environ.get("AWS_SECRET_ACCESS_KEY")
    aws_session_token: Optional[str] = os.environ.get("AWS_SESSION_TOKEN")
    aws_endpoint_url: Optional[str] = os.environ.get("AWS_ENDPOINT_URL")  # for LocalStack e.g. http://localhost:4566

    # S3 configuration
    s3_bucket: Optional[str] = os.environ.get("AWS_S3_BUCKET")
    s3_presign_expiry_seconds: int = int(os.environ.get("S3_PRESIGN_EXPIRY") or 3600)

    # SQS configuration
    sqs_queue_name: str = os.environ.get("SQS_QUEUE_NAME") or "vidx-processing"
    sqs_visibility_timeout: int = int(os.environ.get("SQS_VISIBILITY_TIMEOUT") or 300)
    sqs_message_retention_seconds: int = int(os.environ.get("SQS_RETENTION_SECONDS") or 1209600)  # 14 days

    # Redis configuration (for local development)
    redis_host: str = os.environ.get("REDIS_HOST") or "localhost"
    redis_port: int = int(os.environ.get("REDIS_PORT") or 6379)
    redis_db: int = int(os.environ.get("REDIS_DB") or 0)
    redis_password: Optional[str] = os.environ.get("REDIS_PASSWORD")

    # ElastiCache configuration (for AWS production)
    elasticache_endpoint: Optional[str] = os.environ.get("ELASTICACHE_ENDPOINT")
    elasticache_port: int = int(os.environ.get("ELASTICACHE_PORT") or 6379)
    elasticache_password: Optional[str] = os.environ.get("ELASTICACHE_PASSWORD")
    elasticache_ssl: bool = os.environ.get("ELASTICACHE_SSL", "true").lower() == "true"

    # DynamoDB configuration (for AWS/LocalStack)
    dynamodb_table_name: str = os.environ.get("DYNAMODB_TABLE_NAME") or "vidx-items"

    # AWS Batch configuration (for distributed video processing)
    batch_enabled: bool = os.environ.get("BATCH_ENABLED", "false").lower() == "true"
    batch_job_queue: str = os.environ.get("BATCH_JOB_QUEUE") or "vidx-processing-queue"
    batch_job_definition: str = (
        os.environ.get("BATCH_JOB_DEFINITION") or "vidx-video-merge"
    )
    task_execution_strategy: str = os.environ.get("TASK_EXECUTION_STRATEGY") or "auto"
    # "auto" = use AWS Batch in prod, local in dev
    # "aws-batch" = force AWS Batch
    # "local" = force local execution (for testing)

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
        # Support both MongoDB and AWS DocumentDB by toggling TLS parameters when required.
        scheme = "mongodb"
        if self.db_type.lower() == "documentdb":
            # DocumentDB typically requires TLS; pymongo/motor use mongodb scheme with tls.
            # Connection options can be appended via query parameters.
            return URL.build(
                scheme=scheme,
                host=self.db_host,
                port=self.db_port,
                user=self.db_user,
                password=self.db_pass,
                path=f"/{self.db_base}",
                query={
                    "tls": "true",
                    # Optionally supply a CA file if provided via environment
                    # Motor honors 'tlsCAFile' when present
                    **({"tlsCAFile": os.environ.get("TLS_CA_FILE")} if os.environ.get("TLS_CA_FILE") else {}),
                },
            )
        return URL.build(
            scheme=scheme,
            host=self.db_host,
            port=self.db_port,
            user=self.db_user,
            password=self.db_pass,
            path=f"/{self.db_base}",
        )

    @property
    def broker_url(self) -> URL:
        """
        Compute Celery broker URL based on QUEUE_TYPE.

        For RabbitMQ, returns amqp://... URL.
        For AWS SQS, returns sqs:// scheme (Celery will pick up AWS creds from env).
        """
        if self.queue_type.lower() == "sqs":
            # Celery SQS broker uses sqs://; region and options supplied via celery.conf
            return URL("sqs://")
        # Default to RabbitMQ
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
