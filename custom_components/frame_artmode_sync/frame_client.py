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
            _LOGGER.debug("No TV connection, attempting to connect...")
            if not await self.async_connect():
                _LOGGER.debug("Failed to connect to TV for art mode check")
                return None

        try:
            _LOGGER.debug("Reading Art Mode state from TV at %s:%d", self.host, self.port)
            result = await asyncio.wait_for(
                asyncio.to_thread(self._tv.rest_device_info),
                timeout=COMMAND_TIMEOUT,
            )
            if result and "ArtModeStatus" in result:
                status = result["ArtModeStatus"]
                artmode_on = status == "on"
                _LOGGER.info("Art Mode state read: %s (status='%s')", "ON" if artmode_on else "OFF", status)
                return artmode_on
            else:
                _LOGGER.warning("ArtModeStatus not found in device info response: %s", result)
        except Exception as ex:
            _LOGGER.warning("Failed to get Art Mode from TV at %s:%d: %s", self.host, self.port, ex)
            self._connection_failures += 1
            return None

        _LOGGER.debug("Art Mode state read returned None (no status in response)")
        return None

    async def async_set_artmode(self, on: bool) -> bool:
        """Set Art Mode on or off."""
        _LOGGER.info("Setting Art Mode to %s on TV at %s:%d", "ON" if on else "OFF", self.host, self.port)
        
        if not self._tv:
            _LOGGER.debug("No TV connection, attempting to connect...")
            if not await self.async_connect():
                _LOGGER.warning("Failed to connect to TV for art mode command")
                return False

        try:
            # Check if artmode method exists (may not be available in all samsungtvws versions)
            if hasattr(self._tv, 'artmode'):
                # Method exists, try to use it
                try:
                    _LOGGER.debug("Calling TV.artmode(%s)", on)
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
                    _LOGGER.info("Art Mode command sent successfully: %s", "ON" if on else "OFF")
                    return True
                except AttributeError as ex:
                    # Method exists but call failed (may be a property or different signature)
                    _LOGGER.warning(
                        "SamsungTVWS.artmode() call failed (method may not be callable): %s", ex
                    )
                    return False
            else:
                # Method doesn't exist - this version of samsungtvws doesn't support it
                _LOGGER.warning(
                    "SamsungTVWS.artmode() method not available in this library version. "
                    "Art mode control may not work correctly. "
                    "Please update samsungtvws library or use fallback methods."
                )
                return False
        except AttributeError as ex:
            # Method was removed or doesn't exist
            _LOGGER.warning("Art mode method not available: %s", ex)
            return False
        except Exception as ex:
            _LOGGER.warning("Failed to set Art Mode to %s: %s", "ON" if on else "OFF", ex)
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
        _LOGGER.info("[force_art_on] Starting force Art Mode ON with fallback strategy")
        # Try 1: Set Art Mode on
        _LOGGER.debug("[force_art_on] Strategy 1: Direct art mode ON")
        if await self.async_set_artmode(True):
            _LOGGER.debug("[force_art_on] Strategy 1: Command sent, verifying...")
            if await self.async_verify_artmode(True):
                _LOGGER.info("[force_art_on] Strategy 1 SUCCESS: Art Mode ON verified")
                return True, "set_art_on"
            else:
                _LOGGER.warning("[force_art_on] Strategy 1: Command sent but verification failed")

        # Try 2: Power toggle then set
        _LOGGER.info("[force_art_on] Strategy 1 failed, trying Strategy 2: Power toggle + Art Mode ON")
        if await self.async_power_toggle():
            await asyncio.sleep(2)
            if await self.async_set_artmode(True):
                if await self.async_verify_artmode(True):
                    _LOGGER.info("[force_art_on] Strategy 2 SUCCESS: Power toggle + Art Mode ON verified")
                    return True, "power_toggle_set_art_on"
                else:
                    _LOGGER.warning("[force_art_on] Strategy 2: Power toggle + command sent but verification failed")

        # Try 3: Power twice fallback
        _LOGGER.info("[force_art_on] Strategy 2 failed, trying Strategy 3: Power twice + Art Mode ON")
        if await self.async_power_toggle():
            await asyncio.sleep(2)
        if await self.async_power_toggle():
            await asyncio.sleep(2)
        if await self.async_set_artmode(True):
            if await self.async_verify_artmode(True):
                _LOGGER.info("[force_art_on] Strategy 3 SUCCESS: Power twice + Art Mode ON verified")
                return True, "power_twice_set_art_on"
            else:
                _LOGGER.warning("[force_art_on] Strategy 3: Power twice + command sent but verification failed")

        _LOGGER.warning("[force_art_on] ALL STRATEGIES FAILED: Could not set Art Mode ON")
        return False, "all_strategies_failed"

    async def async_force_art_off(self) -> tuple[bool, str]:
        """Force Art Mode off."""
        _LOGGER.info("[force_art_off] Starting force Art Mode OFF with fallback strategy")
        # Try 1: Set Art Mode off
        _LOGGER.debug("[force_art_off] Strategy 1: Direct art mode OFF")
        if await self.async_set_artmode(False):
            _LOGGER.debug("[force_art_off] Strategy 1: Command sent, verifying...")
            if await self.async_verify_artmode(False):
                _LOGGER.info("[force_art_off] Strategy 1 SUCCESS: Art Mode OFF verified")
                return True, "set_art_off"
            else:
                _LOGGER.warning("[force_art_off] Strategy 1: Command sent but verification failed")

        # Power toggle fallback
        _LOGGER.info("[force_art_off] Strategy 1 failed, trying Strategy 2: Power toggle + verify OFF")
        if await self.async_power_toggle():
            await asyncio.sleep(2)
            if await self.async_verify_artmode(False):
                _LOGGER.info("[force_art_off] Strategy 2 SUCCESS: Power toggle + Art Mode OFF verified")
                return True, "power_toggle_set_art_off"
            else:
                _LOGGER.warning("[force_art_off] Strategy 2: Power toggle + verify failed")

        _LOGGER.warning("[force_art_off] ALL STRATEGIES FAILED: Could not set Art Mode OFF")
        return False, "failed"

    async def async_verify_artmode(self, expected: bool, max_time: float = VERIFY_TIMEOUT_TOTAL) -> bool:
        """Verify Art Mode state with bounded retries."""
        _LOGGER.debug("Verifying Art Mode is %s (max_time=%.1fs)", "ON" if expected else "OFF", max_time)
        start = asyncio.get_running_loop().time()
        attempts = 0
        max_attempts = 10
        sleep_duration = 0.8

        while attempts < max_attempts:
            # Check timeout BEFORE making the call
            elapsed = asyncio.get_running_loop().time() - start
            if elapsed >= max_time:
                _LOGGER.warning("Art Mode verification timeout after %.1fs (expected=%s)", elapsed, expected)
                break
            
            state = await self.async_get_artmode()
            _LOGGER.debug("Verification attempt %d: state=%s, expected=%s", attempts + 1, state, expected)
            if state == expected:
                _LOGGER.info("Art Mode verification SUCCESS: state=%s matches expected=%s (took %.1fs)", 
                           state, expected, elapsed)
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

        _LOGGER.warning("Art Mode verification FAILED: state never matched expected=%s after %d attempts", 
                       expected, attempts)
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

