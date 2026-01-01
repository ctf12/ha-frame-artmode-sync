"""Switch entities for Frame Art Mode Sync."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..entity_helpers import FrameArtModeSyncEntity
from ..manager import FrameArtModeSyncManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch entities."""
    manager: FrameArtModeSyncManager = hass.data["frame_artmode_sync"][entry.entry_id]
    async_add_entities([FrameArtModeSyncEnabledSwitch(hass, entry, manager)])


class FrameArtModeSyncEnabledSwitch(FrameArtModeSyncEntity, SwitchEntity):
    """Switch to enable/disable command sending."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: FrameArtModeSyncManager,
    ) -> None:
        """Initialize switch."""
        super().__init__(hass, entry, manager, "enabled")
        self._attr_name = "Enabled"
        self._attr_icon = "mdi:toggle-switch"

    @property
    def is_on(self) -> bool:
        """Return if enabled."""
        return self.controller._enabled if self.controller else False

    async def async_turn_on(self, **kwargs) -> None:
        """Enable."""
        if self.controller:
            self.controller._enabled = True
            # Update config entry options
            options = dict(self.entry.options)
            options["enabled"] = True
            self.hass.config_entries.async_update_entry(self.entry, options=options)
            await self.controller._compute_and_enforce(force=True)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable."""
        if self.controller:
            self.controller._enabled = False
            options = dict(self.entry.options)
            options["enabled"] = False
            self.hass.config_entries.async_update_entry(self.entry, options=options)

    async def async_update(self) -> None:
        """Update state."""
        # State is managed by controller
        pass

