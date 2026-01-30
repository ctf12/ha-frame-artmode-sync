"""Binary sensor entities for Frame Art Mode Sync."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from ..entity_helpers import FrameArtModeSyncEntity
from ..manager import FrameArtModeSyncManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor entities."""
    manager: FrameArtModeSyncManager = hass.data["frame_artmode_sync"][entry.entry_id]
    async_add_entities([
        FrameArtModeSyncInActiveHoursBinarySensor(hass, entry, manager),
        FrameArtModeSyncATVActiveBinarySensor(hass, entry, manager),
        FrameArtModeSyncATVConnectedBinarySensor(hass, entry, manager),
        FrameArtModeSyncATVPushActiveBinarySensor(hass, entry, manager),
        FrameArtModeSyncFrameConnectedBinarySensor(hass, entry, manager),
        FrameArtModeSyncActualArtModeBinarySensor(hass, entry, manager),
        FrameArtModeSyncOverrideActiveBinarySensor(hass, entry, manager),
    ])


class FrameArtModeSyncInActiveHoursBinarySensor(FrameArtModeSyncEntity, BinarySensorEntity):
    """Binary sensor for active hours."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: FrameArtModeSyncManager,
    ) -> None:
        """Initialize binary sensor."""
        super().__init__(hass, entry, manager, "in_active_hours")
        self._attr_name = "In Active Hours"
        self._attr_icon = "mdi:clock-outline"
        self._update_task = None

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        # Update every minute to catch time window changes
        self._update_task = async_track_time_interval(
            self.hass, self._async_update_callback, timedelta(seconds=60)
        )
        self.async_on_remove(lambda: self._update_task() if self._update_task else None)

    @callback
    def _async_update_callback(self, now) -> None:
        """Update callback."""
        self.async_schedule_update_ha_state(True)

    @property
    def is_on(self) -> bool:
        """Return if in active hours."""
        if not self.controller:
            return False
        return self.controller._in_active_hours


class FrameArtModeSyncATVActiveBinarySensor(FrameArtModeSyncEntity, BinarySensorEntity):
    """Binary sensor for ATV active state."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: FrameArtModeSyncManager,
    ) -> None:
        """Initialize binary sensor."""
        super().__init__(hass, entry, manager, "atv_active")
        self._attr_name = "ATV Active"
        self._attr_icon = "mdi:apple"
        self._update_task = None

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        # Update frequently so users can observe push-driven changes quickly
        self._update_task = async_track_time_interval(
            self.hass, self._async_update_callback, timedelta(seconds=15)
        )
        self.async_on_remove(lambda: self._update_task() if self._update_task else None)

    @callback
    def _async_update_callback(self, now) -> None:
        """Update callback."""
        self.async_schedule_update_ha_state(True)

    @property
    def is_on(self) -> bool:
        """Return if ATV is active."""
        if not self.controller:
            return False
        return self.controller._atv_active

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra attributes."""
        if not self.controller:
            return {}
        return {
            "playback_state": self.controller._atv_playback_state,
        }


class _FrameArtModeSyncPollingBinarySensor(FrameArtModeSyncEntity, BinarySensorEntity):
    """Base binary sensor that triggers periodic state refresh."""

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


class FrameArtModeSyncATVConnectedBinarySensor(_FrameArtModeSyncPollingBinarySensor):
    """Binary sensor for Apple TV connection state."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, manager: FrameArtModeSyncManager) -> None:
        super().__init__(hass, entry, manager, "atv_connected")
        self._attr_name = "ATV Connected"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_icon = "mdi:apple"
        self._poll_interval = timedelta(seconds=15)

    @property
    def is_on(self) -> bool:
        if not self.controller or not getattr(self.controller, "atv_client", None):
            return False
        return bool(self.controller.atv_client.is_connected)


class FrameArtModeSyncATVPushActiveBinarySensor(_FrameArtModeSyncPollingBinarySensor):
    """Binary sensor indicating whether push updates are active (Companion)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, manager: FrameArtModeSyncManager) -> None:
        super().__init__(hass, entry, manager, "atv_push_active")
        self._attr_name = "ATV Push Active"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_icon = "mdi:bell-ring-outline"
        self._poll_interval = timedelta(seconds=15)

    @property
    def is_on(self) -> bool:
        if not self.controller or not getattr(self.controller, "atv_client", None):
            return False
        client = self.controller.atv_client
        # Use pyatv's real PushUpdater.active flag when available.
        # Some pyatv versions might not expose `.active`, so use getattr(..., False).
        try:
            return bool(
                client.atv
                and getattr(client.atv, "push_updater", None)
                and getattr(client.atv.push_updater, "active", False)
            )
        except Exception:  # noqa: BLE001
            return False


class FrameArtModeSyncFrameConnectedBinarySensor(_FrameArtModeSyncPollingBinarySensor):
    """Binary sensor for Frame TV websocket connection state."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, manager: FrameArtModeSyncManager) -> None:
        super().__init__(hass, entry, manager, "frame_connected")
        self._attr_name = "Frame Connected"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_icon = "mdi:television"
        self._poll_interval = timedelta(seconds=30)

    @property
    def is_on(self) -> bool:
        if not self.controller or not getattr(self.controller, "frame_client", None):
            return False
        return bool(self.controller.frame_client.is_connected)


class FrameArtModeSyncActualArtModeBinarySensor(_FrameArtModeSyncPollingBinarySensor):
    """Binary sensor reflecting the last observed TV Art Mode state."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, manager: FrameArtModeSyncManager) -> None:
        super().__init__(hass, entry, manager, "actual_artmode")
        self._attr_name = "TV Art Mode (Actual)"
        self._attr_icon = "mdi:image-frame"
        self._poll_interval = timedelta(seconds=30)

    @property
    def available(self) -> bool:
        if not self.controller:
            return False
        # If we've never successfully read art mode yet, mark unavailable (better than false).
        return getattr(self.controller, "_actual_artmode", None) is not None

    @property
    def is_on(self) -> bool:
        if not self.controller:
            return False
        return bool(getattr(self.controller, "_actual_artmode", False))


class FrameArtModeSyncOverrideActiveBinarySensor(FrameArtModeSyncEntity, BinarySensorEntity):
    """Binary sensor for manual override."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: FrameArtModeSyncManager,
    ) -> None:
        """Initialize binary sensor."""
        super().__init__(hass, entry, manager, "override_active")
        self._attr_name = "Override Active"
        self._attr_icon = "mdi:hand-back-left"
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
    def is_on(self) -> bool:
        """Return if override is active."""
        if not self.controller:
            return False
        from homeassistant.util import dt as dt_util
        from ..entity_helpers import normalize_datetime
        
        override_until = normalize_datetime(self.controller._manual_override_until)
        if override_until:
            return dt_util.utcnow() < override_until
        return False

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra attributes."""
        if not self.controller:
            return {}
        from homeassistant.util import dt as dt_util
        from ..entity_helpers import normalize_datetime
        
        override_until = normalize_datetime(self.controller._manual_override_until)
        if override_until:
            try:
                delta = override_until - dt_util.utcnow()
                remaining = int(delta.total_seconds()) if isinstance(delta, timedelta) else 0
                return {"remaining_seconds": max(0, remaining)}
            except (AttributeError, TypeError) as e:
                _LOGGER.warning("Error calculating override remaining time: %s", e)
                return {}
        return {}

