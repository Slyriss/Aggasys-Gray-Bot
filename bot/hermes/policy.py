from __future__ import annotations

from .guardrails import scan_prompt_for_threats
from .models import ActionDecision, ActionRisk, ActionStatus, HermesAction


class HermesPolicy:
    """Central approval policy for Gray's operational actions."""

    READ_ONLY_ACTIONS = {
        "calculator",
        "get_datetime",
        "hermes_status",
        "list_schedules",
        "web_search",
        "wiki_search",
        "standup_status",
        "daily_brief",
        "ops_status",
    }

    INTERNAL_WORKFLOW_ACTIONS = {
        "standup_start",
        "standup_update",
        "standup_update_natural",
        "standup_chase",
        "standup_close",
        "schedule_daily_standup",
        "schedule_standup_chase",
        "schedule_web_monitor",
        "pause_schedule",
        "resume_schedule",
        "remove_schedule",
    }

    CONFIRMATION_REQUIRED = {
        "send_external_message",
        "place_order",
        "log_leave",
        "update_hr_record",
        "create_supplier_order",
        "submit_tender",
        "delete_data",
        "change_permissions",
    }

    READ_ONLY_PREFIXES = ("approval:", "denial:")

    def decide(self, action: HermesAction) -> ActionDecision:
        threat = scan_prompt_for_threats(str(action.params.get("prompt", "")))
        if threat:
            return ActionDecision(
                status=ActionStatus.DENIED,
                reason=threat,
                action=action,
            )

        if action.risk == ActionRisk.CRITICAL:
            return ActionDecision(
                status=ActionStatus.DENIED,
                reason="Critical actions are blocked until a dedicated admin approval path exists.",
                action=action,
            )

        if not self._is_registered_action(action.name):
            return ActionDecision(
                status=ActionStatus.DENIED,
                reason=f"Unknown Hermes action `{action.name}` is not in the allowed action registry.",
                action=action,
            )

        if self._is_read_only(action.name) or action.risk == ActionRisk.READ_ONLY:
            return ActionDecision(
                status=ActionStatus.ALLOWED,
                reason="Read-only or informational action.",
                action=action,
            )

        if action.name in self.CONFIRMATION_REQUIRED or action.risk in {ActionRisk.MEDIUM, ActionRisk.HIGH}:
            return ActionDecision(
                status=ActionStatus.NEEDS_CONFIRMATION,
                reason="This action can affect people, money, records, or external commitments.",
                action=action,
                confirmation_prompt=self._confirmation_prompt(action),
            )

        return ActionDecision(
            status=ActionStatus.ALLOWED,
            reason="Low-risk internal workflow action.",
            action=action,
        )

    def _is_registered_action(self, name: str) -> bool:
        return (
            self._is_read_only(name)
            or name in self.INTERNAL_WORKFLOW_ACTIONS
            or name in self.CONFIRMATION_REQUIRED
        )

    def _is_read_only(self, name: str) -> bool:
        return name in self.READ_ONLY_ACTIONS or name.startswith(self.READ_ONLY_PREFIXES)

    def _confirmation_prompt(self, action: HermesAction) -> str:
        return (
            f"Hermes needs confirmation before running `{action.name}`.\n"
            f"Reason: {action.description}\n"
            "Reply with explicit approval before Gray proceeds."
        )
