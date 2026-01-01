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
    SERVICE_FORCE_ART_OFF,
    SERVICE_FORCE_ART_ON,
    SERVICE_FORCE_TV_OFF,
    SERVICE_FORCE_TV_ON,
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

        # Resolve targets
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
            service = service_call.service

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


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload services."""
    hass.services.async_remove(DOMAIN, SERVICE_FORCE_ART_ON)
    hass.services.async_remove(DOMAIN, SERVICE_FORCE_ART_OFF)
    hass.services.async_remove(DOMAIN, SERVICE_FORCE_TV_ON)
    hass.services.async_remove(DOMAIN, SERVICE_FORCE_TV_OFF)
    hass.services.async_remove(DOMAIN, SERVICE_RESYNC)
    hass.services.async_remove(DOMAIN, SERVICE_CLEAR_OVERRIDE)
    hass.services.async_remove(DOMAIN, SERVICE_CLEAR_BREAKER)

