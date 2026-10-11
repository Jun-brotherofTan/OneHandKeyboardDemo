"""
Helpers for the agent's alerting engine (alert rules and their status).

The agent evaluates user-defined and built-in alert rules every 15 seconds
and reports each enabled rule's state (``ok``, ``pending`` or ``firing``) at
``/api/v1/alerts/status``. Rules come from ``/api/v1/alerts/rules``. Alert
state is not pushed over the websocket, so it is refreshed by the regular
coordinator poll.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import TYPE_CHECKING, Final

from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

if TYPE_CHECKING:
    from .api.models import AlertRule, AlertStatus
    from .coordinator import UnraidData

# Key prefix of the per-rule binary sensors. No static entity key starts with
# it (the static alert entities use "alert_event" and "alerts_firing"), so
# stale entity cleanup never removes a static entity by mistake.
ALERT_RULE_KEY_PREFIX: Final = "alert_rule_"

ALERT_STATE_FIRING: Final = "firing"


def alert_rule_key(rule_id: str) -> str:
    """
    Return the entity key for an alert rule's binary sensor.

    Rule IDs are free-form strings, so a short hash of the raw ID keeps two
    IDs that slugify alike (``disk-temp`` and ``disk_temp``) apart.
    """
    rule_hash = hashlib.md5(rule_id.encode(), usedforsecurity=False).hexdigest()[:6]
    return f"{ALERT_RULE_KEY_PREFIX}{slugify(rule_id)}_{rule_hash}"


def alert_rule_names(data: UnraidData | None) -> dict[str, str]:
    """
    Return ``{rule_id: rule_name}`` for every rule known to the agent.

    Rules come from the rule list (enabled and disabled) and, should that
    fetch fail, from the status list (enabled rules only).
    """
    names: dict[str, str] = {}
    if data is None:
        return names
    for status in data.alert_statuses or []:
        if status.rule_id:
            names[status.rule_id] = status.rule_name or status.rule_id
    for rule in data.alert_rules or []:
        if rule.id:
            names[rule.id] = rule.name or rule.id
    return names


def find_alert_rule(data: UnraidData | None, rule_id: str) -> AlertRule | None:
    """Return the rule with the given ID, if the agent listed it."""
    if data is None:
        return None
    for rule in data.alert_rules or []:
        if rule.id == rule_id:
            return rule
    return None


def find_alert_status(data: UnraidData | None, rule_id: str) -> AlertStatus | None:
    """Return the status of the rule with the given ID (enabled rules only)."""
    if data is None:
        return None
    for status in data.alert_statuses or []:
        if status.rule_id == rule_id:
            return status
    return None


def alert_since(status: AlertStatus) -> datetime | None:
    """
    Return when a pending or firing rule entered its state.

    The agent sends Go's zero time (``0001-01-01T00:00:00Z``) for rules in
    the ``ok`` state, which is reported as None.
    """
    if not status.since:
        return None
    since = dt_util.parse_datetime(status.since)
    if since is None or since.year <= 1:
        return None
    return since
