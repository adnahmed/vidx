from celery import Celery
from celery.result import AsyncResult

from vidx.settings import settings


class CeleryWorker:
    celery = Celery(
        "vidx",
        broker=str(settings.broker_url),
        result_backend=str(settings.db_url),
        result_persistent=True,
        include=["vidx.services.celery.tasks"],
    )

    def __new__(cls) -> "CeleryWorker":
        if not hasattr(cls, "instance"):
            cls.instance = super(CeleryWorker, cls).__new__(cls)
        return cls.instance

    def __init__(self) -> None:
        # Base Celery configuration common to both RabbitMQ and SQS
        base_conf = {
            "task_routes": {
                "vidx.tasks.*": {"queue": settings.rabbitmq_queue_name},
            },
            "task_default_queue": settings.rabbitmq_queue_name,
        }

        # SQS broker specifics
        if settings.queue_type.lower() == "sqs":
            base_conf.update(
                {
                    "broker_transport_options": {
                        "region": settings.aws_region,
                        "visibility_timeout": settings.sqs_visibility_timeout,
                    },
                }
            )
        else:
            # RabbitMQ specifics
            base_conf.update(
                {
                    "task_default_exchange": settings.rabbitmq_exchange_name,
                    "task_default_routing_key": settings.rabbitmq_routing_key,
                }
            )

        self.celery.conf.update(base_conf)

        if settings.environment.lower() in {"test", "pytest"}:
            return

        # Ensure the exchange/queue exists for RabbitMQ only
        if settings.queue_type.lower() != "sqs":
            with self.celery.connection() as connection:
                channel = connection.channel()
                channel.exchange_declare(
                    exchange=settings.rabbitmq_exchange_name,
                    type="direct",
                    durable=True,
                    auto_delete=False,
                )  # Ensure exchange exists
                channel.queue_declare(
                    queue=settings.rabbitmq_queue_name,
                    durable=True,
                    auto_delete=False,
                )  # Ensure queue exists
                channel.queue_bind(
                    exchange=settings.rabbitmq_exchange_name,
                    queue=settings.rabbitmq_queue_name,
                    routing_key=settings.rabbitmq_routing_key,
                )  # Bind queue to exchange

    @classmethod
    def get_task_status(cls, task_id: str) -> str:
        """
        Get the status of a task.

        :param task_id: Task ID.
        :return: Task status.
        """
        task = cls.celery.AsyncResult(task_id)
        if task is None:
            raise ValueError(f"Task with ID {task_id} not found.")
        return task.status

    @classmethod
    def get_task_result(cls, task_id: str) -> AsyncResult:
        """
        Get the result of a task.

        :param task_id: Task ID.
        :return: Task result.
        """
        task = cls.celery.AsyncResult(task_id)
        if task is None:
            raise ValueError(f"Task with ID {task_id} not found.")
        if task.state == "PENDING":
            raise ValueError(f"Task with ID {task_id} is still pending.")
        if task.state == "FAILURE":
            raise ValueError(f"Task with ID {task_id} failed.")
        return task


celery = CeleryWorker().celery
