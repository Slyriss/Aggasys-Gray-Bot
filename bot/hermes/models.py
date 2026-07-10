from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionRisk(str, Enum):
    READ_ONLY = "read_only"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ActionStatus(str, Enum):
    ALLOWED = "allowed"
    NEEDS_CONFIRMATION = "needs_confirmation"
    DENIED = "denied"


@dataclass(frozen=True)
class HermesAction:
    name: str
    description: str
    actor_user_id: int | None = None
    chat_id: int | None = None
    risk: ActionRisk = ActionRisk.LOW
    params: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None


@dataclass(frozen=True)
class ActionDecision:
    status: ActionStatus
    reason: str
    action: HermesAction
    confirmation_prompt: str | None = None

    @property
    def allowed(self) -> bool:
        return self.status == ActionStatus.ALLOWED

    @property
    def needs_confirmation(self) -> bool:
        return self.status == ActionStatus.NEEDS_CONFIRMATION
