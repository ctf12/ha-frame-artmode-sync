"""Manager for Frame Art Mode Sync integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .pair_controller import PairController

_LOGGER = logging.getLogger(__name__)


class FrameArtModeSyncManager:
    """Manager for a Frame Art Mode Sync config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize manager."""
        self.hass = hass
        self.entry = entry
        self.controller: PairController | None = None
        self.device_id: str | None = None

    async def async_setup(self) -> None:
        """Set up the manager."""
        data = self.entry.data
        options = self.entry.options or {}

        # Merge data and options for config
        config = {**data, **options}

        self.controller = PairController(
            hass=self.hass,
            entry_id=self.entry.entry_id,
            pair_name=config["pair_name"],
            frame_host=config["frame_host"],
            frame_port=config.get("frame_port", 8002),
            frame_mac=config.get("frame_mac"),
            apple_tv_host=config["apple_tv_host"],
            apple_tv_identifier=config.get("apple_tv_identifier"),
            tag=config["tag"],
            config=config,
        )

        await self.controller.async_setup()

        # Create device
        device_registry = dr.async_get(self.hass)
        device = device_registry.async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=config["pair_name"],
            manufacturer="Samsung",
            model="The Frame",
            sw_version="Frame Art Mode Sync",
        )
        self.device_id = device.id

    async def async_cleanup(self) -> None:
        """Clean up the manager."""
        if self.controller:
            await self.controller.async_cleanup()

