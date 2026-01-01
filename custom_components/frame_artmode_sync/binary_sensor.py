"""Binary sensor platform for Frame Art Mode Sync."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entities.binary_sensor import async_setup_entry as async_setup_binary_sensor_platform

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor platform."""
    await async_setup_binary_sensor_platform(hass, entry, async_add_entities)

