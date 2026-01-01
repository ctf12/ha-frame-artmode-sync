"""Storage helpers for Frame Art Mode Sync."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_load_token(
    hass: HomeAssistant, entry: ConfigEntry
) -> str | None:
    """Load stored token for Frame TV."""
    from homeassistant.helpers import storage
    storage_key = f"{entry.domain}_{entry.entry_id}"
    store = storage.Store(hass, entry.version, storage_key)
    stored = await store.async_load()
    if stored and "frame_token" in stored:
        return stored["frame_token"]
    return None


async def async_save_token(
    hass: HomeAssistant, entry: ConfigEntry, token: str
) -> None:
    """Save token for Frame TV."""
    from homeassistant.helpers import storage
    storage_key = f"{entry.domain}_{entry.entry_id}"
    store = storage.Store(hass, entry.version, storage_key)
    data: dict[str, Any] = {}
    stored = await store.async_load()
    if stored:
        data = stored
    data["frame_token"] = token
    await store.async_save(data)

