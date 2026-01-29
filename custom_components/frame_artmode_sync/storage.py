"""Storage helpers for Frame Art Mode Sync."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_load_token(
    hass: HomeAssistant, entry: ConfigEntry
) -> str | None:
    """Load stored token for Frame TV."""
    import logging
    _LOGGER = logging.getLogger(__name__)
    
    from homeassistant.helpers import storage
    storage_key = f"{entry.domain}_{entry.entry_id}"
    store = storage.Store(hass, entry.version, storage_key)
    stored = await store.async_load()
    if stored and "frame_token" in stored:
        token = stored["frame_token"]
        _LOGGER.debug("Loaded Frame TV token from storage for entry %s", entry.entry_id)
        return token
    _LOGGER.debug("No Frame TV token found in storage for entry %s", entry.entry_id)
    return None


async def async_save_token(
    hass: HomeAssistant, entry: ConfigEntry, token: str
) -> None:
    """Save token for Frame TV."""
    import logging
    _LOGGER = logging.getLogger(__name__)
    
    from homeassistant.helpers import storage
    storage_key = f"{entry.domain}_{entry.entry_id}"
    store = storage.Store(hass, entry.version, storage_key)
    data: dict[str, Any] = {}
    stored = await store.async_load()
    if stored:
        data = stored
    data["frame_token"] = token
    await store.async_save(data)
    _LOGGER.debug("Saved Frame TV token to storage for entry %s", entry.entry_id)


async def async_save_atv_credentials(
    hass: HomeAssistant, entry: ConfigEntry, config: Any
) -> None:
    """Save Apple TV credentials after pairing.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry
        config: pyatv config object with credentials
    """
    try:
        from homeassistant.helpers import storage
        storage_key = f"{entry.domain}_{entry.entry_id}"
        store = storage.Store(hass, entry.version, storage_key)
        data: dict[str, Any] = {}
        stored = await store.async_load()
        if stored:
            data = stored
        
        # Extract credentials from config object
        # pyatv stores credentials per protocol in the config
        atv_credentials: dict[str, Any] = {}
        
        # Get credentials for each protocol
        for protocol in config.protocols:
            protocol_name = protocol.name if hasattr(protocol, 'name') else str(protocol)
            try:
                # Get credentials for this protocol
                creds = config.get_credentials(protocol)
                if creds:
                    atv_credentials[protocol_name] = str(creds)
            except Exception as ex:
                # Protocol might not have credentials yet
                pass
        
        # Also store identifier for matching
        if hasattr(config, 'identifier'):
            atv_credentials["identifier"] = str(config.identifier)
        
        data["atv_credentials"] = atv_credentials
        await store.async_save(data)
    except Exception as ex:
        # Log but don't fail - credentials might be stored elsewhere
        import logging
        _LOGGER = logging.getLogger(__name__)
        _LOGGER.warning("Failed to save Apple TV credentials: %s", ex)


async def async_load_atv_credentials(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any] | None:
    """Load stored Apple TV credentials.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry
        
    Returns:
        Dictionary of credentials by protocol, or None if not found
    """
    try:
        from homeassistant.helpers import storage
        storage_key = f"{entry.domain}_{entry.entry_id}"
        store = storage.Store(hass, entry.version, storage_key)
        stored = await store.async_load()
        if stored and "atv_credentials" in stored:
            return stored["atv_credentials"]
    except Exception as ex:
        import logging
        _LOGGER = logging.getLogger(__name__)
        _LOGGER.warning("Failed to load Apple TV credentials: %s", ex)
    return None

