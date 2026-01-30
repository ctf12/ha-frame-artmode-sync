"""Sensor entities for Frame Art Mode Sync."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from ..const import HEALTH_BREAKER_OPEN, HEALTH_DEGRADED, HEALTH_OK
from ..entity_helpers import FrameArtModeSyncEntity, normalize_datetime
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
        FrameArtModeSyncPhaseSensor(hass, entry, manager),
        FrameArtModeSyncDesiredModeSensor(hass, entry, manager),
        FrameArtModeSyncATVPlaybackSensor(hass, entry, manager),
        FrameArtModeSyncLastActionAtSensor(hass, entry, manager),
        FrameArtModeSyncATVLastUpdateSensor(hass, entry, manager),
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


class _FrameArtModeSyncPollingSensor(FrameArtModeSyncEntity, SensorEntity):
    """Base sensor that triggers periodic state refresh."""

    _update_task = None
    _poll_interval = timedelta(seconds=30)

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self._update_task = async_track_time_interval(
            self.hass, self._async_update_callback, self._poll_interval
        )
        self.async_on_remove(lambda: self._update_task() if self._update_task else None)

    @callback
    def _async_update_callback(self, now) -> None:
        """Update callback."""
        self.async_schedule_update_ha_state(True)


class FrameArtModeSyncPhaseSensor(_FrameArtModeSyncPollingSensor):
    """Current controller phase sensor."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, manager: FrameArtModeSyncManager) -> None:
        super().__init__(hass, entry, manager, "phase")
        self._attr_name = "Phase"
        self._attr_icon = "mdi:progress-wrench"
        self._poll_interval = timedelta(seconds=30)

    @property
    def native_value(self) -> str:
        if not self.controller:
            return "unknown"
        return getattr(self.controller, "_phase", "unknown")


class FrameArtModeSyncDesiredModeSensor(_FrameArtModeSyncPollingSensor):
    """Desired mode sensor (ART/ATV/OFF)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, manager: FrameArtModeSyncManager) -> None:
        super().__init__(hass, entry, manager, "desired_mode")
        self._attr_name = "Desired Mode"
        self._attr_icon = "mdi:target"
        self._poll_interval = timedelta(seconds=30)

    @property
    def native_value(self) -> str:
        if not self.controller:
            return "unknown"
        return getattr(self.controller, "_desired_mode", None) or "unknown"


class FrameArtModeSyncATVPlaybackSensor(_FrameArtModeSyncPollingSensor):
    """Apple TV playback state (playing/paused/idle/etc)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, manager: FrameArtModeSyncManager) -> None:
        super().__init__(hass, entry, manager, "atv_playback")
        self._attr_name = "ATV Playback"
        self._attr_icon = "mdi:play-pause"
        # Update a bit faster so you can see push updates working
        self._poll_interval = timedelta(seconds=15)

    @property
    def native_value(self) -> str:
        if not self.controller:
            return "unknown"
        return getattr(self.controller, "_atv_playback_state", "unknown")


class FrameArtModeSyncLastActionAtSensor(_FrameArtModeSyncPollingSensor):
    """Timestamp of last enforcement action."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, manager: FrameArtModeSyncManager) -> None:
        super().__init__(hass, entry, manager, "last_action_at")
        self._attr_name = "Last Action At"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_icon = "mdi:clock-check-outline"
        self._poll_interval = timedelta(seconds=30)

    @property
    def native_value(self):
        if not self.controller:
            return None
        dt = normalize_datetime(getattr(self.controller, "_last_action_ts", None))
        return dt


class FrameArtModeSyncATVLastUpdateSensor(_FrameArtModeSyncPollingSensor):
    """Timestamp of last Apple TV state update observed by the client."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, manager: FrameArtModeSyncManager) -> None:
        super().__init__(hass, entry, manager, "atv_last_update")
        self._attr_name = "ATV Last Update"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_icon = "mdi:update"
        self._poll_interval = timedelta(seconds=15)

    @property
    def native_value(self):
        if not self.controller or not getattr(self.controller, "atv_client", None):
            return None
        last = getattr(self.controller.atv_client, "_last_update", None)
        if last is None:
            return None
        return dt_util.as_utc(last)

