from __future__ import annotations

import os
from datetime import datetime, timedelta

from .models import ActionDecision

APPROVAL_TTL_HOURS = int(os.getenv("HERMES_APPROVAL_TTL_HOURS", "24"))


def approval_summary(approval: dict) -> str:
    requested = approval.get("requested_at")
    when = requested.strftime("%d %b %H:%M") if hasattr(requested, "strftime") else ""
    expires = approval.get("expires_at")
    expiry = expires.strftime("%d %b %H:%M") if hasattr(expires, "strftime") else ""
    expiry_line = f"\nExpires: {expiry}" if expiry else ""
    return (
        f"#{approval['id']} `{approval['action_name']}` ({approval['risk']})\n"
        f"Reason: {approval['reason']}\n"
        f"Requested: {when}{expiry_line}"
    )


async def create_approval_from_decision(decision: ActionDecision) -> int:
    from db import create_hermes_approval_request

    action = decision.action
    return await create_hermes_approval_request(
        user_id=action.actor_user_id,
        chat_id=action.chat_id,
        action_name=action.name,
        risk=action.risk.value,
        prompt=decision.confirmation_prompt or "",
        reason=decision.reason,
        params=action.params,
        expires_at=approval_expiry(),
    )


def approval_expiry(now: datetime | None = None) -> datetime:
    base = now or datetime.now()
    return base + timedelta(hours=APPROVAL_TTL_HOURS)
