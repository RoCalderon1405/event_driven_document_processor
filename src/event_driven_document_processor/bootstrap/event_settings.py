"""Delivery budgets shared by provisioning and the Lambda adapter."""

from pydantic import Field, model_validator

from event_driven_document_processor.bootstrap.settings import Settings


class EventSettings(Settings):
    """Ensure the first post-crash redelivery occurs after lease expiry, with retry margin."""

    processing_queue_name: str = Field(
        default="document-processing", pattern=r"^[A-Za-z0-9_-]{1,75}$"
    )
    processing_dlq_name: str = Field(
        default="document-processing-dlq", pattern=r"^[A-Za-z0-9_-]{1,80}$"
    )
    processing_function_name: str = Field(
        default="document-processing", pattern=r"^[A-Za-z0-9_-]{1,64}$"
    )
    processing_role_name: str = Field(
        default="document-processing", pattern=r"^[A-Za-z0-9_-]{1,64}$"
    )
    processing_lambda_timeout: int = Field(default=150, ge=3, le=900)
    processing_visibility_timeout: int = Field(default=900, ge=1, le=43200)
    processing_max_receive_count: int = Field(default=5, ge=3, le=20)
    processing_batch_size: int = Field(default=2, ge=1, le=10)

    @property
    def record_budget_seconds(self) -> float:
        """Reserve read/parse, repository I/O/retry backoff and one final read overrun."""
        backoff = sum(min(20, 2**attempt) for attempt in range(self.aws_max_attempts - 1))
        return (
            self.processing_read_timeout_seconds
            + self.processing_validation_timeout_seconds
            + 3 * self.aws_max_attempts * (self.aws_connect_timeout + self.aws_read_timeout)
            + 3 * backoff
            + self.aws_read_timeout
            + 1
        )

    @model_validator(mode="after")
    def validate_delivery_budgets(self) -> EventSettings:
        """Do not exhaust redrive on active claims left behind by a killed invocation."""
        if (
            not self.record_budget_seconds
            < self.processing_lambda_timeout
            < self.processing_lease_seconds
        ):
            raise ValueError("Require record budget < Lambda timeout < processing lease")
        if self.processing_visibility_timeout < max(
            6 * self.processing_lambda_timeout,
            self.processing_lease_seconds + 5,
        ):
            raise ValueError(
                "Visibility must cover six Lambda timeouts and lease plus five seconds"
            )
        if len({self.processing_queue_name, self.processing_dlq_name}) != 2:
            raise ValueError("Processing queue and DLQ must differ")
        return self
