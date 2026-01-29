"""Services for Frame Art Mode Sync."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr

from .const import (
    DOMAIN,
    SERVICE_CLEAR_BREAKER,
    SERVICE_CLEAR_OVERRIDE,
    SERVICE_DELETE_ENTRY,
    SERVICE_FORCE_ART_OFF,
    SERVICE_FORCE_ART_ON,
    SERVICE_FORCE_TV_OFF,
    SERVICE_FORCE_TV_ON,
    SERVICE_REPAIR_APPLE_TV,
    SERVICE_REPAIR_SAMSUNG_TV,
    SERVICE_RESYNC,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_TIMEOUT = 30.0  # seconds


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services."""

    async def async_handle_service(service_call: ServiceCall) -> None:
        """Handle service call."""
        device_registry = dr.async_get(hass)
        entry_ids = set()

        service = service_call.service
        
        # Special handling for delete_entry service
        if service == SERVICE_DELETE_ENTRY:
            entry_id = service_call.data.get("entry_id")
            if not entry_id:
                _LOGGER.error("delete_entry service requires entry_id")
                return
            
            _LOGGER.info("Force deleting entry %s", entry_id)
            try:
                # Try to unload first if loaded
                if DOMAIN in hass.data and entry_id in hass.data[DOMAIN]:
                    from . import async_unload_entry
                    entries = hass.config_entries.async_entries(DOMAIN)
                    entry = next((e for e in entries if e.entry_id == entry_id), None)
                    if entry:
                        try:
                            await async_unload_entry(hass, entry)
                        except Exception as ex:
                            _LOGGER.warning("Error unloading entry %s: %s, proceeding with deletion", entry_id, ex)
                        # Remove from data
                        hass.data[DOMAIN].pop(entry_id, None)
                
                # Force delete the entry
                entries = hass.config_entries.async_entries(DOMAIN)
                entry = next((e for e in entries if e.entry_id == entry_id), None)
                if entry:
                    await hass.config_entries.async_remove(entry_id)
                    _LOGGER.info("Successfully deleted entry %s", entry_id)
                else:
                    _LOGGER.warning("Entry %s not found in config entries", entry_id)
            except Exception as ex:
                _LOGGER.error("Error deleting entry %s: %s", entry_id, ex)
            return

        # Resolve targets for other services
        if "device_id" in service_call.data:
            device_id = service_call.data["device_id"]
            device = device_registry.async_get(device_id)
            if device:
                for config_entry_id in device.config_entries:
                    if config_entry_id in hass.data.get(DOMAIN, {}):
                        entry_ids.add(config_entry_id)
        elif "entry_id" in service_call.data:
            entry_id = service_call.data["entry_id"]
            if entry_id in hass.data.get(DOMAIN, {}):
                entry_ids.add(entry_id)
        else:
            # No target specified, use all entries
            entry_ids = set(hass.data.get(DOMAIN, {}).keys())

        if not entry_ids:
            _LOGGER.warning("No matching entries found for service call")
            return

        # Call service on each entry
        for entry_id in entry_ids:
            manager = hass.data[DOMAIN][entry_id]
            if not manager or not manager.controller:
                continue

            controller = manager.controller

            try:
                if service == SERVICE_FORCE_ART_ON:
                    await asyncio.wait_for(controller.async_force_art_on(), timeout=SERVICE_TIMEOUT)
                elif service == SERVICE_FORCE_ART_OFF:
                    await asyncio.wait_for(controller.async_force_art_off(), timeout=SERVICE_TIMEOUT)
                elif service == SERVICE_FORCE_TV_ON:
                    await asyncio.wait_for(controller.async_force_art_off(), timeout=SERVICE_TIMEOUT)  # TV on = Art Mode off
                elif service == SERVICE_FORCE_TV_OFF:
                    await asyncio.wait_for(controller.async_force_tv_off(), timeout=SERVICE_TIMEOUT)
                elif service == SERVICE_RESYNC:
                    await asyncio.wait_for(controller.async_resync(), timeout=SERVICE_TIMEOUT)
                elif service == SERVICE_CLEAR_OVERRIDE:
                    await asyncio.wait_for(controller.async_clear_override(), timeout=SERVICE_TIMEOUT)
                elif service == SERVICE_CLEAR_BREAKER:
                    await asyncio.wait_for(controller.async_clear_breaker(), timeout=SERVICE_TIMEOUT)
                elif service == SERVICE_REPAIR_APPLE_TV:
                    await asyncio.wait_for(controller.async_repair_apple_tv(), timeout=60.0)  # Longer timeout for pairing
                elif service == SERVICE_REPAIR_SAMSUNG_TV:
                    await asyncio.wait_for(controller.async_repair_samsung_tv(), timeout=60.0)  # Longer timeout for pairing
            except asyncio.TimeoutError:
                _LOGGER.error("Service %s on %s timed out after %d seconds", service, entry_id, SERVICE_TIMEOUT)
            except Exception as ex:
                _LOGGER.error("Error executing service %s on %s: %s", service, entry_id, ex)

    # Register services
    hass.services.async_register(
        DOMAIN,
        SERVICE_FORCE_ART_ON,
        async_handle_service,
        schema=vol.Schema({
            vol.Optional("device_id"): str,
            vol.Optional("entry_id"): str,
        }),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_FORCE_ART_OFF,
        async_handle_service,
        schema=vol.Schema({
            vol.Optional("device_id"): str,
            vol.Optional("entry_id"): str,
        }),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_FORCE_TV_ON,
        async_handle_service,
        schema=vol.Schema({
            vol.Optional("device_id"): str,
            vol.Optional("entry_id"): str,
        }),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_FORCE_TV_OFF,
        async_handle_service,
        schema=vol.Schema({
            vol.Optional("device_id"): str,
            vol.Optional("entry_id"): str,
        }),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESYNC,
        async_handle_service,
        schema=vol.Schema({
            vol.Optional("device_id"): str,
            vol.Optional("entry_id"): str,
        }),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_OVERRIDE,
        async_handle_service,
        schema=vol.Schema({
            vol.Optional("device_id"): str,
            vol.Optional("entry_id"): str,
        }),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_BREAKER,
        async_handle_service,
        schema=vol.Schema({
            vol.Optional("device_id"): str,
            vol.Optional("entry_id"): str,
        }),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REPAIR_APPLE_TV,
        async_handle_service,
        schema=vol.Schema({
            vol.Optional("device_id"): str,
            vol.Optional("entry_id"): str,
        }),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REPAIR_SAMSUNG_TV,
        async_handle_service,
        schema=vol.Schema({
            vol.Optional("device_id"): str,
            vol.Optional("entry_id"): str,
        }),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_ENTRY,
        async_handle_service,
        schema=vol.Schema({
            vol.Required("entry_id"): str,
        }),
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload services."""
    hass.services.async_remove(DOMAIN, SERVICE_FORCE_ART_ON)
    hass.services.async_remove(DOMAIN, SERVICE_FORCE_ART_OFF)
    hass.services.async_remove(DOMAIN, SERVICE_FORCE_TV_ON)
    hass.services.async_remove(DOMAIN, SERVICE_FORCE_TV_OFF)
    hass.services.async_remove(DOMAIN, SERVICE_RESYNC)
    hass.services.async_remove(DOMAIN, SERVICE_CLEAR_OVERRIDE)
    hass.services.async_remove(DOMAIN, SERVICE_CLEAR_BREAKER)
    hass.services.async_remove(DOMAIN, SERVICE_REPAIR_APPLE_TV)
    hass.services.async_remove(DOMAIN, SERVICE_REPAIR_SAMSUNG_TV)
    hass.services.async_remove(DOMAIN, SERVICE_DELETE_ENTRY)

