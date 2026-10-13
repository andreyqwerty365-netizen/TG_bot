from datetime import UTC, date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Deadline(Strict):
    precision: Literal["date", "instant"]
    value: str
    original: str = Field(min_length=1, max_length=1000)
    timezone: str

    @model_validator(mode="after")
    def valid(self):
        try:
            ZoneInfo(self.timezone)
        except (KeyError, ValueError) as error:
            raise ValueError("Unknown IANA timezone") from error
        if self.precision == "date":
            date.fromisoformat(self.value)
        else:
            instant = datetime.fromisoformat(self.value.replace("Z", "+00:00"))
            if instant.tzinfo is None:
                raise ValueError("Timezone required")
            self.value = instant.astimezone(UTC).isoformat()
        return self


class Interpretation(Strict):
    source_version_id: str
    operation: Literal["create", "clarify", "propose_update"]
    kind: Literal["task", "waiting", "note"] = "task"
    title: str = Field(default="", max_length=2000)
    obvious: bool = False
    question: str | None = Field(default=None, max_length=1000)
    deadline: Deadline | None = None
    reminder_at: datetime | None = None
    target_id: str | None = None
    target_version: int | None = Field(default=None, gt=0)
    change: Literal["close", "reminder", "deadline", "title", "plan", "defer", "resume", "cancel", "focus"] | None = None
    planned_on: date | None = None
    return_on: date | None = None
    focused: bool | None = None

    @field_validator("reminder_at")
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Reminder must include timezone")
        return value.astimezone(UTC) if value else None

    @model_validator(mode="after")
    def meaningful(self):
        if self.operation == "clarify":
            if not self.question:
                raise ValueError("Question required")
        elif self.operation == "create":
            if not self.title.strip() or self.target_id or self.change:
                raise ValueError("Invalid creation")
        elif not self.target_id or not self.target_version or not self.change:
            raise ValueError("Bound target and version required")
        if self.change == "reminder" and not self.reminder_at:
            raise ValueError("Reminder required")
        if self.change == "title" and not self.title.strip():
            raise ValueError("Title required")
        if self.change == "plan" and not self.planned_on:
            raise ValueError("Execution date required")
        if self.change == "defer" and not self.return_on:
            raise ValueError("Return date required")
        if self.change == "focus" and self.focused is None:
            raise ValueError("Focus value required")
        return self


class Incoming(Strict):
    external_id: str = Field(min_length=1, max_length=128)
    account: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=16000)
    revision: int = Field(default=1, gt=0)
    original_at: datetime | None = None

    @field_validator("original_at")
    @classmethod
    def aware(cls, value):
        if value and value.tzinfo is None:
            raise ValueError("Original timestamp must include timezone")
        return value
