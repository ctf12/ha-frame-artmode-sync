"""Samsung Frame TV client using samsungtvws."""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
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

# Global per-TV connect locks to avoid multiple concurrent websocket sessions to the
# same TV (which can trigger repeated pairing prompts).
_GLOBAL_CONNECT_LOCKS: dict[str, asyncio.Lock] = {}


def _redact_tokens(obj: Any) -> Any:
    """Best-effort redaction for token-like fields in exception payloads."""
    try:
        if isinstance(obj, dict):
            data = deepcopy(obj)
            # Common keys that may include auth/token material
            for key in ("token", "Token", "auth", "Auth", "credentials", "credential"):
                if key in data:
                    data[key] = "***"
            # Also redact nested attributes.token if present
            attrs = data.get("data", {}).get("attributes") if isinstance(data.get("data"), dict) else None
            if isinstance(attrs, dict) and "token" in attrs:
                attrs = dict(attrs)
                attrs["token"] = "***"
                data["data"] = dict(data.get("data", {}))
                data["data"]["attributes"] = attrs
            return data
    except Exception:  # noqa: BLE001
        return "<redacted>"
    return obj


def _looks_like_ws_event(obj: Any) -> bool:
    """Return True if obj looks like a samsungtvws websocket event/timeOut payload."""
    if isinstance(obj, dict):
        event = obj.get("event")
        return isinstance(event, str) and event.startswith("ms.channel")
    if isinstance(obj, str):
        return "ms.channel" in obj
    return False


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
        tv_key = f"{self.host}:{self.port}"
        global_lock = _GLOBAL_CONNECT_LOCKS.setdefault(tv_key, asyncio.Lock())
        async with global_lock:
            async with self._lock:
                connect_start_time = asyncio.get_running_loop().time()
                try:
                    if self.token:
                        _LOGGER.info(
                            "Connecting to Frame TV at %s:%d with saved token (timeout=%ds)",
                            self.host,
                            self.port,
                            CONNECTION_TIMEOUT,
                        )
                    else:
                        _LOGGER.info(
                            "Connecting to Frame TV at %s:%d (no token - pairing may be required, timeout=%ds)",
                            self.host,
                            self.port,
                            CONNECTION_TIMEOUT,
                        )

                    _LOGGER.debug(
                        "Creating SamsungTVWS object: host=%s, port=%d, token_present=%s, timeout=%ds",
                        self.host,
                        self.port,
                        self.token is not None,
                        CONNECTION_TIMEOUT,
                    )
                    self._tv = SamsungTVWS(
                        host=self.host,
                        port=self.port,
                        token=self.token,
                        name=self.client_name,
                        timeout=CONNECTION_TIMEOUT,
                    )

                    # Try to connect
                    try:
                        _LOGGER.debug(
                            "Calling start_listening() on TV at %s:%d (timeout=%ds)",
                            self.host,
                            self.port,
                            CONNECTION_TIMEOUT,
                        )
                        listen_start_time = asyncio.get_running_loop().time()
                        await asyncio.wait_for(
                            asyncio.to_thread(self._tv.start_listening),
                            timeout=CONNECTION_TIMEOUT,
                        )
                        listen_elapsed = asyncio.get_running_loop().time() - listen_start_time
                        _LOGGER.debug("start_listening() completed successfully in %.2fs", listen_elapsed)
                    except UnauthorizedError:
                        if self.token:
                            _LOGGER.warning("Frame TV rejected saved token - may need to re-pair.")
                        else:
                            _LOGGER.info("Pairing required for Frame TV (no token available)")

                        if not token_callback:
                            raise

                        token = await asyncio.wait_for(
                            asyncio.to_thread(self._get_token),
                            timeout=30.0,
                        )
                        if token:
                            self.token = token
                            _LOGGER.info("Obtained new Frame TV token from TV; saving for future connections")
                            try:
                                if asyncio.iscoroutinefunction(token_callback):
                                    await token_callback(token)
                                else:
                                    await asyncio.to_thread(token_callback, token)
                                _LOGGER.info("Saved Frame TV token for future connections")
                            except Exception as ex:  # noqa: BLE001
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

                    # If the TV issued/rotated a token during connection (common on first pairing),
                    # persist it so we don't re-pair and generate a new token on every restart.
                    try:
                        tv_token = getattr(self._tv, "token", None) if self._tv else None
                        if tv_token and tv_token != self.token:
                            self.token = tv_token
                            if token_callback:
                                try:
                                    if asyncio.iscoroutinefunction(token_callback):
                                        await token_callback(tv_token)
                                    else:
                                        await asyncio.to_thread(token_callback, tv_token)
                                    _LOGGER.info("Saved Frame TV token for future connections")
                                except Exception as ex:  # noqa: BLE001
                                    _LOGGER.warning("Error saving token: %s", ex)
                    except Exception as ex:  # noqa: BLE001
                        _LOGGER.debug("Unable to persist Frame TV token after connect: %s", ex)

                    self._connection_failures = 0
                    connect_elapsed = asyncio.get_running_loop().time() - connect_start_time
                    _LOGGER.info(
                        "Connected to Frame TV at %s:%d (took %.2fs)",
                        self.host,
                        self.port,
                        connect_elapsed,
                    )
                    return True

                except asyncio.TimeoutError:
                    elapsed = asyncio.get_running_loop().time() - connect_start_time
                    _LOGGER.warning(
                        "Connection timeout to Frame TV at %s:%d after %.2fs (timeout=%ds). "
                        "TV may be off, unreachable, or not accepting connections. "
                        "Check TV power state and network connectivity.",
                        self.host,
                        self.port,
                        elapsed,
                        CONNECTION_TIMEOUT,
                    )
                    self._connection_failures += 1
                    return False
                except Exception as ex:
                    elapsed = asyncio.get_running_loop().time() - connect_start_time
                    _LOGGER.warning(
                        "Failed to connect to Frame TV at %s:%d after %.2fs: %s (%s)",
                        self.host,
                        self.port,
                        elapsed,
                        ex,
                        type(ex).__name__,
                    )
                    self._connection_failures += 1
                    return False

    def _get_token(self) -> str | None:
        """Get token from TV (blocking)."""
        tv: SamsungTVWS | None = None
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
        finally:
            # Ensure we always close the temp websocket connection.
            try:
                if tv:
                    tv.close()
            except Exception:
                pass

    async def async_disconnect(self) -> None:
        """Disconnect from Frame TV."""
        async with self._lock:
            if self._tv:
                try:
                    self._tv.close()
                except Exception:
                    pass
                self._tv = None

    async def _reconnect(self) -> bool:
        """Force reconnect to clear stale websocket sessions."""
        await self.async_disconnect()
        return await self.async_connect()

    async def async_get_artmode(self) -> bool | None:
        """Get current Art Mode state."""
        if not self._tv:
            _LOGGER.debug("No TV connection, attempting to connect...")
            if not await self.async_connect():
                _LOGGER.debug("Failed to connect to TV for art mode check")
                return None

        # Prefer samsungtvws Art API (stable across versions) if available.
        art_factory = getattr(self._tv, "art", None)
        if not callable(art_factory):
            _LOGGER.warning("SamsungTVWS.art() API not available; cannot read Art Mode state")
            return None

        async def _read_once() -> bool | None:
            art = art_factory()
            value = await asyncio.wait_for(
                asyncio.to_thread(art.get_artmode),
                timeout=COMMAND_TIMEOUT,
            )
            # samsungtvws typically returns "on"/"off" (string) but normalize broadly.
            if isinstance(value, bool):
                return value
            if isinstance(value, int):
                return value != 0
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in ("on", "true", "1"):
                    return True
                if normalized in ("off", "false", "0"):
                    return False
            # Some failure modes return event payloads instead of on/off.
            if _looks_like_ws_event(value):
                raise RuntimeError(_redact_tokens(value))
            return None

        try:
            state = await _read_once()
            if state is not None:
                _LOGGER.info("Art Mode state read via art API: %s", "ON" if state else "OFF")
            return state
        except Exception as ex:
            redacted = _redact_tokens(ex)
            _LOGGER.debug("Art API get_artmode failed: %s", redacted)
            # Common on 2024 models: stale websocket session. Reconnect once and retry.
            if _looks_like_ws_event(ex) or _looks_like_ws_event(getattr(ex, "args", None)):
                await self._reconnect()
                try:
                    state = await _read_once()
                    if state is not None:
                        _LOGGER.info("Art Mode state read via art API after reconnect: %s", "ON" if state else "OFF")
                    return state
                except Exception as ex2:  # noqa: BLE001
                    _LOGGER.debug("Art API get_artmode retry failed: %s", _redact_tokens(ex2))
            self._connection_failures += 1
            return None

    async def async_set_artmode(self, on: bool) -> bool:
        """Set Art Mode on or off."""
        _LOGGER.info("Setting Art Mode to %s on TV at %s:%d", "ON" if on else "OFF", self.host, self.port)
        
        if not self._tv:
            _LOGGER.debug("No TV connection, attempting to connect...")
            if not await self.async_connect():
                _LOGGER.warning("Failed to connect to TV for art mode command")
                return False

        art_factory = getattr(self._tv, "art", None)
        if not callable(art_factory):
            _LOGGER.warning(
                "SamsungTVWS.art() API not available in this samsungtvws version. "
                "Cannot control Art Mode; please upgrade samsungtvws."
            )
            return False

        async def _set_once() -> None:
            art = art_factory()
            # Pass string form for compatibility (some versions expect 'on'/'off').
            value = "on" if on else "off"
            result = await asyncio.wait_for(
                asyncio.to_thread(art.set_artmode, value),
                timeout=COMMAND_TIMEOUT,
            )
            # Some failure modes return event payloads instead of acknowledging.
            if _looks_like_ws_event(result):
                raise RuntimeError(_redact_tokens(result))

        try:
            await _set_once()
            _LOGGER.info("Art Mode command sent successfully via art API: %s", "ON" if on else "OFF")
            return True
        except Exception as ex:
            _LOGGER.warning(
                "Failed to set Art Mode to %s: %s",
                "ON" if on else "OFF",
                _redact_tokens(ex),
            )
            # Common on 2024 models: stale websocket session. Reconnect once and retry.
            if _looks_like_ws_event(ex) or _looks_like_ws_event(getattr(ex, "args", None)):
                await self._reconnect()
                try:
                    await _set_once()
                    _LOGGER.info(
                        "Art Mode command sent successfully via art API after reconnect: %s",
                        "ON" if on else "OFF",
                    )
                    return True
                except Exception as ex2:  # noqa: BLE001
                    _LOGGER.warning("Art Mode retry failed: %s", _redact_tokens(ex2))
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

    @property
    def is_connected(self) -> bool:
        """Return if websocket connection is established."""
        return self._tv is not None
