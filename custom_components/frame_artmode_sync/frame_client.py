"""Samsung Frame TV client using samsungtvws."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from samsungtvws import SamsungTVWS
from samsungtvws.exceptions import UnauthorizedError
from wakeonlan import send_magic_packet

from .const import (
    COMMAND_TIMEOUT,
    CONNECTION_TIMEOUT,
    POWER_TOGGLE_TIMEOUT,
    STORAGE_KEY_TOKEN,
    VERIFY_TIMEOUT_TOTAL,
)

_LOGGER = logging.getLogger(__name__)


class FrameClient:
    """Samsung Frame TV client."""

    def __init__(
        self,
        host: str,
        port: int = 8002,
        token: str | None = None,
        client_name: str = "FrameArtSync",
    ) -> None:
        """Initialize Frame client."""
        self.host = host
        self.port = port
        self.token = token
        self.client_name = client_name[:18]  # Truncate to 18 chars

        self._tv: SamsungTVWS | None = None
        self._lock = asyncio.Lock()
        self._connection_failures = 0

    async def async_connect(self, token_callback: Any | None = None) -> bool:
        """Connect to Frame TV."""
        async with self._lock:
            try:
                _LOGGER.info("Connecting to Frame TV at %s:%d", self.host, self.port)
                self._tv = SamsungTVWS(
                    host=self.host,
                    port=self.port,
                    token=self.token,
                    name=self.client_name,
                    timeout=CONNECTION_TIMEOUT,
                )

                # Try to connect
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(self._tv.start_listening),
                        timeout=CONNECTION_TIMEOUT,
                    )
                except UnauthorizedError:
                    _LOGGER.info("Pairing required for Frame TV")
                    if token_callback:
                        # Get token (blocking operation)
                        token = await asyncio.wait_for(
                            asyncio.to_thread(self._get_token),
                            timeout=30.0,
                        )
                        if token:
                            self.token = token
                            # Save token via callback (assume it's async)
                            if token_callback:
                                try:
                                    if asyncio.iscoroutinefunction(token_callback):
                                        await token_callback(token)
                                    else:
                                        # Sync callback, run in executor
                                        await asyncio.to_thread(token_callback, token)
                                except Exception as ex:
                                    _LOGGER.warning("Error saving token: %s", ex)
                            # Reconnect with token
                            self._tv = SamsungTVWS(
                                host=self.host,
                                port=self.port,
                                token=self.token,
                                name=self.client_name,
                                timeout=CONNECTION_TIMEOUT,
                            )
                            await asyncio.wait_for(
                                asyncio.to_thread(self._tv.start_listening),
                                timeout=CONNECTION_TIMEOUT,
                            )
                    else:
                        raise

                self._connection_failures = 0
                _LOGGER.info("Connected to Frame TV")
                return True

            except asyncio.TimeoutError:
                _LOGGER.warning("Connection timeout to Frame TV")
                self._connection_failures += 1
                return False
            except Exception as ex:
                _LOGGER.warning("Failed to connect to Frame TV: %s", ex)
                self._connection_failures += 1
                return False

    def _get_token(self) -> str | None:
        """Get token from TV (blocking)."""
        try:
            tv = SamsungTVWS(
                host=self.host,
                port=self.port,
                token=None,
                name=self.client_name,
                timeout=CONNECTION_TIMEOUT,
            )
            tv.start_listening()
            return tv.token
        except Exception as ex:
            _LOGGER.error("Failed to get token: %s", ex)
            return None

    async def async_disconnect(self) -> None:
        """Disconnect from Frame TV."""
        async with self._lock:
            if self._tv:
                try:
                    self._tv.close()
                except Exception:
                    pass
                self._tv = None

    async def async_get_artmode(self) -> bool | None:
        """Get current Art Mode state."""
        if not self._tv:
            if not await self.async_connect():
                return None

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._tv.rest_device_info),
                timeout=COMMAND_TIMEOUT,
            )
            if result and "ArtModeStatus" in result:
                status = result["ArtModeStatus"]
                _LOGGER.debug("Art Mode status: %s", status)
                return status == "on"
        except Exception as ex:
            _LOGGER.debug("Failed to get Art Mode: %s", ex)
            self._connection_failures += 1
            return None

        return None

    async def async_set_artmode(self, on: bool) -> bool:
        """Set Art Mode on or off."""
        if not self._tv:
            if not await self.async_connect():
                return False

        try:
            if on:
                await asyncio.wait_for(
                    asyncio.to_thread(self._tv.artmode, True),
                    timeout=COMMAND_TIMEOUT,
                )
            else:
                await asyncio.wait_for(
                    asyncio.to_thread(self._tv.artmode, False),
                    timeout=COMMAND_TIMEOUT,
                )
            _LOGGER.info("Set Art Mode: %s", on)
            return True
        except Exception as ex:
            _LOGGER.warning("Failed to set Art Mode: %s", ex)
            self._connection_failures += 1
            return False

    async def async_power_toggle(self) -> bool:
        """Toggle TV power."""
        if not self._tv:
            if not await self.async_connect():
                return False

        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._tv.send_key, "KEY_POWER"),
                timeout=POWER_TOGGLE_TIMEOUT,
            )
            _LOGGER.info("Power toggle sent")
            return True
        except Exception as ex:
            _LOGGER.warning("Failed to power toggle: %s", ex)
            self._connection_failures += 1
            return False

    async def async_set_source(self, source: str) -> bool:
        """Set input source (best effort)."""
        if not self._tv:
            if not await self.async_connect():
                return False

        try:
            key_map = {
                "hdmi1": "KEY_HDMI1",
                "hdmi2": "KEY_HDMI2",
                "hdmi3": "KEY_HDMI3",
            }
            if source in key_map:
                await asyncio.wait_for(
                    asyncio.to_thread(self._tv.send_key, key_map[source]),
                    timeout=COMMAND_TIMEOUT,
                )
                _LOGGER.info("Set source: %s", source)
                return True
        except Exception as ex:
            _LOGGER.debug("Failed to set source (best effort): %s", ex)

        return False

    async def async_force_art_on(self) -> tuple[bool, str]:
        """Force Art Mode on with fallback strategy."""
        # Try 1: Set Art Mode on
        if await self.async_set_artmode(True):
            if await self.async_verify_artmode(True):
                return True, "set_art_on"

        # Try 2: Power toggle then set
        _LOGGER.info("Attempting power toggle fallback")
        if await self.async_power_toggle():
            await asyncio.sleep(2)
            if await self.async_set_artmode(True):
                if await self.async_verify_artmode(True):
                    return True, "power_toggle_set_art_on"

        # Try 3: Power twice fallback
        _LOGGER.info("Attempting power twice fallback")
        if await self.async_power_toggle():
            await asyncio.sleep(2)
        if await self.async_power_toggle():
            await asyncio.sleep(2)
        if await self.async_set_artmode(True):
            if await self.async_verify_artmode(True):
                return True, "power_twice_set_art_on"

        return False, "all_strategies_failed"

    async def async_force_art_off(self) -> tuple[bool, str]:
        """Force Art Mode off."""
        if await self.async_set_artmode(False):
            if await self.async_verify_artmode(False):
                return True, "set_art_off"

        # Power toggle fallback
        if await self.async_power_toggle():
            await asyncio.sleep(2)
            if await self.async_verify_artmode(False):
                return True, "power_toggle_set_art_off"

        return False, "failed"

    async def async_verify_artmode(self, expected: bool, max_time: float = VERIFY_TIMEOUT_TOTAL) -> bool:
        """Verify Art Mode state with bounded retries."""
        start = asyncio.get_running_loop().time()
        attempts = 0
        max_attempts = 10
        sleep_duration = 0.8

        while attempts < max_attempts:
            # Check timeout BEFORE making the call
            elapsed = asyncio.get_running_loop().time() - start
            if elapsed >= max_time:
                break
            
            state = await self.async_get_artmode()
            if state == expected:
                return True
            attempts += 1
            
            # Only sleep if we have time remaining
            remaining_time = max_time - elapsed
            if remaining_time > sleep_duration:
                await asyncio.sleep(sleep_duration)
            elif remaining_time > 0:
                await asyncio.sleep(remaining_time)
            else:
                break

        return False

    async def async_wake(self, mac: str, broadcast: str = "255.255.255.255") -> bool:
        """Send Wake-on-LAN packet."""
        try:
            await asyncio.to_thread(send_magic_packet, mac, ip_address=broadcast)
            _LOGGER.info("Sent WOL packet to %s (broadcast: %s)", mac, broadcast)
            return True
        except Exception as ex:
            _LOGGER.warning("Failed to send WOL packet to %s (broadcast: %s): %s", mac, broadcast, ex)
            return False

    @property
    def connection_failures(self) -> int:
        """Return connection failure count."""
        return self._connection_failures

