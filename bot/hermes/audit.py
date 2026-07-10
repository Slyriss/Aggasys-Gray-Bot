from __future__ import annotations

import json
import logging
from typing import Any

from .models import ActionDecision, ActionStatus

logger = logging.getLogger(__name__)


async def record_decision(decision: ActionDecision, status: str | None = None) -> None:
    """Best-effort audit log. Never break user-facing bot flow."""
    try:
        from db import save_hermes_audit_log

        action = decision.action
        await save_hermes_audit_log(
            user_id=action.actor_user_id,
            chat_id=action.chat_id,
            action_name=action.name,
            risk=action.risk.value,
            decision=decision.status.value,
            status=status or _default_status(decision.status),
            details={
                "description": action.description,
                "reason": decision.reason,
                "params": _json_safe(action.params),
                "idempotency_key": action.idempotency_key,
            },
        )
    except Exception as exc:
        logger.warning("Hermes audit write failed: %s", exc)


def _default_status(status: ActionStatus) -> str:
    if status == ActionStatus.ALLOWED:
        return "executed"
    if status == ActionStatus.NEEDS_CONFIRMATION:
        return "pending_confirmation"
    return "blocked"


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)
