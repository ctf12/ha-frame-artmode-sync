"""Time entities for Frame Art Mode Sync."""

from __future__ import annotations

import logging
from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..const import DEFAULT_ACTIVE_END, DEFAULT_ACTIVE_START
from ..entity_helpers import FrameArtModeSyncEntity, normalize_time
from ..manager import FrameArtModeSyncManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up time entities."""
    manager: FrameArtModeSyncManager = hass.data["frame_artmode_sync"][entry.entry_id]
    async_add_entities([
        FrameArtModeSyncActiveStartTime(hass, entry, manager),
        FrameArtModeSyncActiveEndTime(hass, entry, manager),
    ])


class FrameArtModeSyncActiveStartTime(FrameArtModeSyncEntity, TimeEntity):
    """Time entity for active start."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: FrameArtModeSyncManager,
    ) -> None:
        """Initialize time entity."""
        super().__init__(hass, entry, manager, "active_start")
        self._attr_name = "Active Start"
        self._attr_icon = "mdi:clock-time-four-outline"

    @property
    def native_value(self) -> time | None:
        """Return current time value as datetime.time."""
        if not self.controller:
            return None
        options = {**self.entry.data, **self.entry.options}
        value = options.get("active_start", DEFAULT_ACTIVE_START)
        # Normalize: convert string to time object if needed
        normalized = normalize_time(value)
        if normalized is None:
            # Fallback to default if parsing failed
            _LOGGER.warning("Failed to parse active_start time, using default: %s", value)
            normalized = normalize_time(DEFAULT_ACTIVE_START)
        return normalized

    async def async_set_value(self, value: time | str) -> None:
        """Set time value."""
        if self.controller:
            # Normalize input to time object, then store as string
            normalized = normalize_time(value)
            if normalized is None:
                _LOGGER.warning("Invalid time value provided: %s", value)
                return
            
            # Store as ISO format string (HH:MM:SS) for consistency
            time_str = normalized.isoformat()
            options = dict(self.entry.options)
            options["active_start"] = time_str
            self.controller.config["active_start"] = time_str
            self.hass.config_entries.async_update_entry(self.entry, options=options)
            await self.controller._update_active_hours()
            await self.controller._compute_and_enforce(force=True)


class FrameArtModeSyncActiveEndTime(FrameArtModeSyncEntity, TimeEntity):
    """Time entity for active end."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: FrameArtModeSyncManager,
    ) -> None:
        """Initialize time entity."""
        super().__init__(hass, entry, manager, "active_end")
        self._attr_name = "Active End"
        self._attr_icon = "mdi:clock-time-four-outline"

    @property
    def native_value(self) -> time | None:
        """Return current time value as datetime.time."""
        if not self.controller:
            return None
        options = {**self.entry.data, **self.entry.options}
        value = options.get("active_end", DEFAULT_ACTIVE_END)
        # Normalize: convert string to time object if needed
        normalized = normalize_time(value)
        if normalized is None:
            # Fallback to default if parsing failed
            _LOGGER.warning("Failed to parse active_end time, using default: %s", value)
            normalized = normalize_time(DEFAULT_ACTIVE_END)
        return normalized

    async def async_set_value(self, value: time | str) -> None:
        """Set time value."""
        if self.controller:
            # Normalize input to time object, then store as string
            normalized = normalize_time(value)
            if normalized is None:
                _LOGGER.warning("Invalid time value provided: %s", value)
                return
            
            # Store as ISO format string (HH:MM:SS) for consistency
            time_str = normalized.isoformat()
            options = dict(self.entry.options)
            options["active_end"] = time_str
            self.controller.config["active_end"] = time_str
            self.hass.config_entries.async_update_entry(self.entry, options=options)
            await self.controller._update_active_hours()
            await self.controller._compute_and_enforce(force=True)

