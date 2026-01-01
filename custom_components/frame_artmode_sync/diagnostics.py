"""Diagnostics for Frame Art Mode Sync."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

REDACT_KEYS = {
    "frame_token",
    "token",
    "frame_host",
    "frame_mac",
    "apple_tv_host",
    "apple_tv_identifier",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    if entry.entry_id not in hass.data.get(DOMAIN, {}):
        return {}

    manager = hass.data[DOMAIN][entry.entry_id]
    if not manager:
        return {}
    
    controller = manager.controller
    if not controller:
        return {}

    # Gather diagnostics
    diagnostics: dict[str, Any] = {
        "entry": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "data": async_redact_data(entry.data, REDACT_KEYS),
            "options": async_redact_data(entry.options, REDACT_KEYS),
        },
        "controller": {
            "pair_name": controller.pair_name,
            "enabled": controller._enabled,
            "atv_active": controller._atv_active,
            "atv_playback_state": controller._atv_playback_state,
            "desired_mode": controller._desired_mode,
            "actual_artmode": controller._actual_artmode,
            "in_active_hours": controller._in_active_hours,
            "home_ok": controller._home_ok,
            "phase": controller._phase,
            "pair_health": controller._pair_health,
            "breaker_open": controller._breaker_open,
            "manual_override_active": controller._manual_override_until is not None,
            "command_count_5min": len(controller._command_times),
            "connect_fail_count": controller._connect_fail_count,
            "command_fail_count": controller._command_fail_count,
            "verify_fail_count": controller._verify_fail_count,
        },
        "frame_client": {
            "connection_failures": controller.frame_client.connection_failures,
            "is_connected": controller.frame_client._tv is not None,
        },
        "atv_client": {
            "is_connected": controller.atv_client.is_connected,
        },
    }

    return diagnostics

