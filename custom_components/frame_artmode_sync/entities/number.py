"""Number entities for Frame Art Mode Sync."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..const import (
    DEFAULT_ATV_DEBOUNCE_SECONDS,
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_RETURN_DELAY_SECONDS,
)
from ..entity_helpers import FrameArtModeSyncEntity
from ..manager import FrameArtModeSyncManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities."""
    manager: FrameArtModeSyncManager = hass.data["frame_artmode_sync"][entry.entry_id]
    async_add_entities([
        FrameArtModeSyncReturnDelayNumber(hass, entry, manager),
        FrameArtModeSyncCooldownNumber(hass, entry, manager),
        FrameArtModeSyncATVDebounceNumber(hass, entry, manager),
    ])


class FrameArtModeSyncReturnDelayNumber(FrameArtModeSyncEntity, NumberEntity):
    """Number entity for return delay."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: FrameArtModeSyncManager,
    ) -> None:
        """Initialize number entity."""
        super().__init__(hass, entry, manager, "return_delay")
        self._attr_name = "Return Delay"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 300
        self._attr_native_step = 1
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:timer-outline"
        self._attr_native_unit_of_measurement = "s"

    @property
    def native_value(self) -> float | None:
        """Return current value."""
        if not self.controller:
            return None
        options = {**self.entry.data, **self.entry.options}
        return float(options.get("return_delay_seconds", DEFAULT_RETURN_DELAY_SECONDS))

    async def async_set_native_value(self, value: float) -> None:
        """Set value."""
        if self.controller:
            options = dict(self.entry.options)
            options["return_delay_seconds"] = int(value)
            self.controller.config["return_delay_seconds"] = int(value)
            self.hass.config_entries.async_update_entry(self.entry, options=options)


class FrameArtModeSyncCooldownNumber(FrameArtModeSyncEntity, NumberEntity):
    """Number entity for cooldown."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: FrameArtModeSyncManager,
    ) -> None:
        """Initialize number entity."""
        super().__init__(hass, entry, manager, "cooldown")
        self._attr_name = "Cooldown"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 300
        self._attr_native_step = 1
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:timer-outline"
        self._attr_native_unit_of_measurement = "s"

    @property
    def native_value(self) -> float | None:
        """Return current value."""
        if not self.controller:
            return None
        options = {**self.entry.data, **self.entry.options}
        return float(options.get("cooldown_seconds", DEFAULT_COOLDOWN_SECONDS))

    async def async_set_native_value(self, value: float) -> None:
        """Set value."""
        if self.controller:
            options = dict(self.entry.options)
            options["cooldown_seconds"] = int(value)
            self.controller.config["cooldown_seconds"] = int(value)
            self.hass.config_entries.async_update_entry(self.entry, options=options)


class FrameArtModeSyncATVDebounceNumber(FrameArtModeSyncEntity, NumberEntity):
    """Number entity for ATV debounce."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: FrameArtModeSyncManager,
    ) -> None:
        """Initialize number entity."""
        super().__init__(hass, entry, manager, "atv_debounce")
        self._attr_name = "ATV Debounce"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 60
        self._attr_native_step = 1
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:timer-outline"
        self._attr_native_unit_of_measurement = "s"

    @property
    def native_value(self) -> float | None:
        """Return current value."""
        if not self.controller:
            return None
        options = {**self.entry.data, **self.entry.options}
        return float(options.get("atv_debounce_seconds", DEFAULT_ATV_DEBOUNCE_SECONDS))

    async def async_set_native_value(self, value: float) -> None:
        """Set value."""
        if self.controller:
            options = dict(self.entry.options)
            options["atv_debounce_seconds"] = int(value)
            self.controller.config["atv_debounce_seconds"] = int(value)
            self.hass.config_entries.async_update_entry(self.entry, options=options)

