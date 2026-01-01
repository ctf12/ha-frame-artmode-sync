"""Entity helper functions."""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .manager import FrameArtModeSyncManager

_LOGGER = logging.getLogger(__name__)


def normalize_timedelta(value: timedelta | int | float | str | None) -> timedelta | None:
    """
    Normalize a value to timedelta or None.
    
    Accepts:
    - timedelta: returned as-is
    - int/float: treated as seconds
    - str: numeric string treated as seconds, or empty/None -> None
    - None: returned as None
    """
    if value is None:
        return None
    if isinstance(value, timedelta):
        return value
    if isinstance(value, (int, float)):
        return timedelta(seconds=float(value))
    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            return timedelta(seconds=float(value))
        except (ValueError, TypeError):
            _LOGGER.warning("Cannot parse timedelta from string: %s", value)
            return None
    _LOGGER.warning("Unexpected type for timedelta normalization: %s (%s)", type(value), value)
    return None


def normalize_datetime(value: datetime | str | int | float | None) -> datetime | None:
    """
    Normalize a value to timezone-aware datetime or None.
    
    Accepts:
    - datetime: converted to UTC if not timezone-aware
    - str: ISO format string parsed to datetime
    - int/float: treated as Unix timestamp (seconds since epoch)
    - None: returned as None
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        # Ensure timezone-aware (UTC)
        return dt_util.as_utc(value)
    if isinstance(value, str):
        if not value.strip():
            return None
        parsed = dt_util.parse_datetime(value)
        if parsed is None:
            _LOGGER.warning("Cannot parse datetime from string: %s", value)
            return None
        return dt_util.as_utc(parsed)
    if isinstance(value, (int, float)):
        # Unix timestamp
        try:
            return dt_util.utc_from_timestamp(float(value))
        except (ValueError, OSError) as e:
            _LOGGER.warning("Cannot parse datetime from timestamp: %s (%s)", value, e)
            return None
    _LOGGER.warning("Unexpected type for datetime normalization: %s (%s)", type(value), value)
    return None


def normalize_time(value: time | str | None) -> time | None:
    """
    Normalize a value to datetime.time or None.
    
    Accepts:
    - time: returned as-is
    - str: ISO time format string (HH:MM:SS or HH:MM) parsed using fromisoformat or dt_util.parse_time
    - None: returned as None
    """
    if value is None:
        return None
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            # Try fromisoformat first (supports HH:MM:SS and HH:MM)
            return time.fromisoformat(value)
        except (ValueError, TypeError):
            try:
                # Fallback to homeassistant.util.dt.parse_time
                parsed = dt_util.parse_time(value)
                if parsed:
                    return parsed
            except (ValueError, TypeError):
                pass
        _LOGGER.warning("Cannot parse time from string: %s", value)
        return None
    _LOGGER.warning("Unexpected type for time normalization: %s (%s)", type(value), value)
    return None


def ensure_isoformat(value: datetime | str | None) -> str | None:
    """
    Ensure a value is an ISO format string.
    
    - datetime: converted to ISO format string (timezone-aware)
    - str: returned as-is (assumed to be valid ISO)
    - None: returned as None
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        # Ensure timezone-aware before calling isoformat
        dt = dt_util.as_utc(value) if value.tzinfo is None else value
        return dt.isoformat()
    if isinstance(value, str):
        return value
    _LOGGER.warning("Cannot convert to ISO format: %s (%s)", type(value), value)
    return None


class FrameArtModeSyncEntity(Entity):
    """Base entity for Frame Art Mode Sync."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: FrameArtModeSyncManager,
        entity_id_suffix: str,
    ) -> None:
        """Initialize base entity."""
        self.hass = hass
        self.entry = entry
        self.manager = manager
        self.controller = manager.controller
        self._attr_unique_id = f"{entry.entry_id}_{entity_id_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data.get("pair_name", "Frame Art Mode Sync"),
            manufacturer="Samsung",
            model="The Frame",
            sw_version="Frame Art Mode Sync",
        )
        self._attr_has_entity_name = True

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.controller is not None

