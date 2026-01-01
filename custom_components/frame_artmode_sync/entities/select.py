"""Select entities for Frame Art Mode Sync."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..const import (
    ATV_ACTIVE_MODE_PLAYING_OR_PAUSED,
    AWAY_POLICY_DISABLED,
    INPUT_MODE_HDMI1,
    NIGHT_BEHAVIOR_FORCE_OFF,
    PRESENCE_MODE_DISABLED,
)
from ..entity_helpers import FrameArtModeSyncEntity
from ..manager import FrameArtModeSyncManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select entities."""
    manager: FrameArtModeSyncManager = hass.data["frame_artmode_sync"][entry.entry_id]
    async_add_entities([
        FrameArtModeSyncNightBehaviorSelect(hass, entry, manager),
        FrameArtModeSyncPresenceModeSelect(hass, entry, manager),
        FrameArtModeSyncAwayPolicySelect(hass, entry, manager),
        FrameArtModeSyncInputModeSelect(hass, entry, manager),
        FrameArtModeSyncATVActiveModeSelect(hass, entry, manager),
    ])


class FrameArtModeSyncNightBehaviorSelect(FrameArtModeSyncEntity, SelectEntity):
    """Select entity for night behavior."""

    _attr_options = ["do_nothing", "force_off", "force_art"]
    _attr_icon = "mdi:weather-night"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: FrameArtModeSyncManager,
    ) -> None:
        """Initialize select entity."""
        super().__init__(hass, entry, manager, "night_behavior")
        self._attr_name = "Night Behavior"

    @property
    def current_option(self) -> str | None:
        """Return current option."""
        if not self.controller:
            return None
        options = {**self.entry.data, **self.entry.options}
        return options.get("night_behavior", NIGHT_BEHAVIOR_FORCE_OFF)

    async def async_select_option(self, option: str) -> None:
        """Set option."""
        if self.controller:
            options = dict(self.entry.options)
            options["night_behavior"] = option
            self.controller.config["night_behavior"] = option
            self.hass.config_entries.async_update_entry(self.entry, options=options)
            await self.controller._compute_and_enforce(force=True)


class FrameArtModeSyncPresenceModeSelect(FrameArtModeSyncEntity, SelectEntity):
    """Select entity for presence mode."""

    _attr_options = ["disabled", "entity"]
    _attr_icon = "mdi:account"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: FrameArtModeSyncManager,
    ) -> None:
        """Initialize select entity."""
        super().__init__(hass, entry, manager, "presence_mode")
        self._attr_name = "Presence Mode"

    @property
    def current_option(self) -> str | None:
        """Return current option."""
        if not self.controller:
            return None
        options = {**self.entry.data, **self.entry.options}
        return options.get("presence_mode", PRESENCE_MODE_DISABLED)

    async def async_select_option(self, option: str) -> None:
        """Set option."""
        if self.controller:
            options = dict(self.entry.options)
            options["presence_mode"] = option
            self.controller.config["presence_mode"] = option
            self.hass.config_entries.async_update_entry(self.entry, options=options)
            await self.controller._update_presence()
            await self.controller._compute_and_enforce(force=True)


class FrameArtModeSyncAwayPolicySelect(FrameArtModeSyncEntity, SelectEntity):
    """Select entity for away policy."""

    _attr_options = ["disabled", "turn_tv_off", "keep_art_on"]
    _attr_icon = "mdi:shield-home"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: FrameArtModeSyncManager,
    ) -> None:
        """Initialize select entity."""
        super().__init__(hass, entry, manager, "away_policy")
        self._attr_name = "Away Policy"

    @property
    def current_option(self) -> str | None:
        """Return current option."""
        if not self.controller:
            return None
        options = {**self.entry.data, **self.entry.options}
        return options.get("away_policy", AWAY_POLICY_DISABLED)

    async def async_select_option(self, option: str) -> None:
        """Set option."""
        if self.controller:
            options = dict(self.entry.options)
            options["away_policy"] = option
            self.controller.config["away_policy"] = option
            self.hass.config_entries.async_update_entry(self.entry, options=options)
            await self.controller._compute_and_enforce(force=True)


class FrameArtModeSyncInputModeSelect(FrameArtModeSyncEntity, SelectEntity):
    """Select entity for input mode."""

    _attr_options = ["none", "hdmi1", "hdmi2", "hdmi3", "last_used"]
    _attr_icon = "mdi:input-hdmi"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: FrameArtModeSyncManager,
    ) -> None:
        """Initialize select entity."""
        super().__init__(hass, entry, manager, "input_mode")
        self._attr_name = "Input Mode"

    @property
    def current_option(self) -> str | None:
        """Return current option."""
        if not self.controller:
            return None
        options = {**self.entry.data, **self.entry.options}
        return options.get("input_mode", INPUT_MODE_HDMI1)

    async def async_select_option(self, option: str) -> None:
        """Set option."""
        if self.controller:
            options = dict(self.entry.options)
            options["input_mode"] = option
            self.controller.config["input_mode"] = option
            self.hass.config_entries.async_update_entry(self.entry, options=options)


class FrameArtModeSyncATVActiveModeSelect(FrameArtModeSyncEntity, SelectEntity):
    """Select entity for ATV active mode."""

    _attr_options = ["playing_only", "playing_or_paused", "power_on"]
    _attr_icon = "mdi:apple"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: FrameArtModeSyncManager,
    ) -> None:
        """Initialize select entity."""
        super().__init__(hass, entry, manager, "atv_active_mode")
        self._attr_name = "ATV Active Mode"

    @property
    def current_option(self) -> str | None:
        """Return current option."""
        if not self.controller:
            return None
        options = {**self.entry.data, **self.entry.options}
        return options.get("atv_active_mode", ATV_ACTIVE_MODE_PLAYING_OR_PAUSED)

    async def async_select_option(self, option: str) -> None:
        """Set option."""
        if self.controller:
            options = dict(self.entry.options)
            options["atv_active_mode"] = option
            self.controller.config["atv_active_mode"] = option
            # Update ATV client
            self.controller.atv_client.active_mode = option
            self.hass.config_entries.async_update_entry(self.entry, options=options)

