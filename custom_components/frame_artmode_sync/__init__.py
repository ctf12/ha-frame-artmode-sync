"""Frame Art Mode Sync integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .manager import FrameArtModeSyncManager
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.TIME,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Frame Art Mode Sync from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    # Migrate base_pairing_name from old default "HaCasaArt" to new default "FrameArtSync"
    # Only migrate if stored value exactly matches the old default; preserve user custom values
    old_default = "HaCasaArt"
    new_default = "FrameArtSync"
    updated = False
    new_data = dict(entry.data)
    new_options = dict(entry.options)
    
    if new_data.get("base_pairing_name") == old_default:
        new_data["base_pairing_name"] = new_default
        updated = True
    if new_options.get("base_pairing_name") == old_default:
        new_options["base_pairing_name"] = new_default
        updated = True
    
    if updated:
        hass.config_entries.async_update_entry(entry, data=new_data, options=new_options)
        _LOGGER.info("Migrated base_pairing_name from %s to %s for entry %s", old_default, new_default, entry.entry_id)
    
    # Set up services once
    if DOMAIN not in hass.data.get("_frame_artmode_sync_services_setup", set()):
        await async_setup_services(hass)
        hass.data.setdefault("_frame_artmode_sync_services_setup", set()).add(DOMAIN)
    
    manager = FrameArtModeSyncManager(hass, entry)
    await manager.async_setup()
    hass.data[DOMAIN][entry.entry_id] = manager

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if entry.entry_id in hass.data[DOMAIN]:
        manager = hass.data[DOMAIN][entry.entry_id]
        await manager.async_cleanup()
        hass.data[DOMAIN].pop(entry.entry_id)

    # Clean up services if last entry
    if not hass.data.get(DOMAIN):
        await async_unload_services(hass)
        hass.data.pop("_frame_artmode_sync_services_setup", None)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)

