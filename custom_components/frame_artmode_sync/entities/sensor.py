"""Sensor entities for Frame Art Mode Sync."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from ..const import HEALTH_BREAKER_OPEN, HEALTH_DEGRADED, HEALTH_OK
from ..entity_helpers import FrameArtModeSyncEntity
from ..manager import FrameArtModeSyncManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    manager: FrameArtModeSyncManager = hass.data["frame_artmode_sync"][entry.entry_id]
    async_add_entities([
        FrameArtModeSyncStatusSensor(hass, entry, manager),
        FrameArtModeSyncPairHealthSensor(hass, entry, manager),
        FrameArtModeSyncRecentEventsSensor(hass, entry, manager),
    ])


class FrameArtModeSyncStatusSensor(FrameArtModeSyncEntity, SensorEntity):
    """Status sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: FrameArtModeSyncManager,
    ) -> None:
        """Initialize sensor."""
        super().__init__(hass, entry, manager, "status")
        self._attr_name = "Status"
        self._attr_icon = "mdi:information"
        self._update_task = None

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        # Update every 30 seconds
        self._update_task = async_track_time_interval(
            self.hass, self._async_update_callback, timedelta(seconds=30)
        )
        self.async_on_remove(lambda: self._update_task() if self._update_task else None)

    @callback
    def _async_update_callback(self, now) -> None:
        """Update callback."""
        self.async_schedule_update_ha_state(True)

    @property
    def native_value(self) -> str:
        """Return status state."""
        if not self.controller:
            return "Unknown"
        return self.controller.status_state

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra attributes."""
        if not self.controller:
            return {}
        return self.controller.status_attributes


class FrameArtModeSyncPairHealthSensor(FrameArtModeSyncEntity, SensorEntity):
    """Pair health sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: FrameArtModeSyncManager,
    ) -> None:
        """Initialize sensor."""
        super().__init__(hass, entry, manager, "pair_health")
        self._attr_name = "Pair Health"
        self._attr_icon = "mdi:heart-pulse"

    @property
    def native_value(self) -> str:
        """Return health state."""
        if not self.controller:
            return "unknown"
        return self.controller._pair_health


class FrameArtModeSyncRecentEventsSensor(FrameArtModeSyncEntity, SensorEntity):
    """Recent events sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: FrameArtModeSyncManager,
    ) -> None:
        """Initialize sensor."""
        super().__init__(hass, entry, manager, "recent_events")
        self._attr_name = "Recent Events"

    @property
    def native_value(self) -> str:
        """Return events text."""
        if not self.controller:
            return "No events"
        return self.controller.recent_events_text[:255]  # Limit for state

    async def async_update(self) -> None:
        """Update sensor."""
        # Events are managed by controller
        pass

