"""Apple TV client using pyatv."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from pyatv import connect, scan
from pyatv.const import DeviceState, PowerState, Protocol
from pyatv.core import PushUpdater
try:
    from pyatv.exceptions import AuthenticationError, NotPairedError, PairingError
    PYATV_EXCEPTIONS_AVAILABLE = True
except ImportError:
    # Fallback for pyatv versions that don't have these exceptions
    AuthenticationError = Exception  # type: ignore[assignment, misc]
    NotPairedError = Exception  # type: ignore[assignment, misc]
    PairingError = Exception  # type: ignore[assignment, misc]
    PYATV_EXCEPTIONS_AVAILABLE = False
from pyatv.interface import AppleTV, Playing, PowerListener, PushListener

from homeassistant.util import dt as dt_util

from .const import (
    ATV_ACTIVE_MODE_PLAYING_ONLY,
    ATV_ACTIVE_MODE_PLAYING_OR_PAUSED,
    ATV_ACTIVE_MODE_POWER_ON,
    CONF_ATV_CREDENTIALS,
    DEFAULT_ATV_DEBOUNCE_SECONDS,
    DEFAULT_ATV_GRACE_SECONDS_ON_DISCONNECT,
)

_LOGGER = logging.getLogger(__name__)


async def async_get_atv_config(loop: asyncio.AbstractEventLoop, identifier: str | None, host: str) -> Any | None:
    """Build pyatv config via scan using identifier (preferred) or host."""
    results = None
    try:
        if identifier:
            try:
                results = await scan(loop=loop, identifier=identifier, timeout=10)
            except TypeError:
                results = await scan(identifier=identifier, timeout=10)
        else:
            try:
                results = await scan(loop=loop, hosts=[host], timeout=10)
            except TypeError:
                results = await scan(hosts=[host], timeout=10)
    except Exception as ex:  # noqa: BLE001
        _LOGGER.debug("pyatv scan failed: %s", ex)
        results = None

    if not results:
        try:
            try:
                results = await scan(loop=loop, timeout=12)
            except TypeError:
                results = await scan(timeout=12)
            if results:
                identifier_str = str(identifier).strip() if identifier else ""
                identifier_lower = identifier_str.lower()
                host_str = str(host).strip()

                def _match(cfg) -> bool:
                    try:
                        if identifier_str:
                            if str(getattr(cfg, "identifier", "")) == identifier_str:
                                return True
                            # Users sometimes store the *name* instead of identifier; support that.
                            if str(getattr(cfg, "name", "")).strip().lower() == identifier_lower:
                                return True
                        if host_str and str(getattr(cfg, "address", "")) == host_str:
                            return True
                    except Exception:  # noqa: BLE001
                        return False
                    return False

                results = [cfg for cfg in results if _match(cfg)]
        except Exception as ex:  # noqa: BLE001
            _LOGGER.debug("fallback network scan failed: %s", ex)
            results = None

    return results[0] if results else None


class ATVClient:
    """Apple TV client with push updates."""

    def __init__(
        self,
        host: str,
        identifier: str | None = None,
        active_mode: str = ATV_ACTIVE_MODE_PLAYING_OR_PAUSED,
        debounce_seconds: int = DEFAULT_ATV_DEBOUNCE_SECONDS,
        grace_seconds: int = DEFAULT_ATV_GRACE_SECONDS_ON_DISCONNECT,
        state_callback: Callable[[bool, str], None] | None = None,
        hass: Any | None = None,
        entry: Any | None = None,
    ) -> None:
        """Initialize Apple TV client."""
        self.host = host
        self.identifier = identifier
        self.active_mode = active_mode
        self.debounce_seconds = debounce_seconds
        self.grace_seconds = grace_seconds
        self.state_callback = state_callback
        self.hass = hass
        self.entry = entry

        self.atv: AppleTV | None = None
        self.push_updater: PushUpdater | None = None
        self._listener: ATVPushListener | None = None

        self._current_state: bool = False
        self._playback_state: str = "unknown"
        self._power_state: PowerState = PowerState.Unknown
        self._last_update: datetime | None = None
        self._grace_until: datetime | None = None
        self._debounce_task: asyncio.Task | None = None
        self._listener_tasks: set[asyncio.Task] = set()
        self._lock = asyncio.Lock()
        self._reconnect_task: asyncio.Task | None = None
        self._reconnect_backoff = 10.0  # Start with 10s
        self._should_reconnect = True

    async def async_connect(self) -> bool:
        """Connect to Apple TV."""
        async with self._lock:
            try:
                loop = asyncio.get_running_loop()
                _LOGGER.info("Scanning for Apple TV at %s (identifier=%s)", self.host, self.identifier)
                config = await async_get_atv_config(loop, self.identifier, self.host)
                if not config:
                    _LOGGER.warning(
                        "No Apple TV found at %s (identifier=%s). Will retry.",
                        self.host,
                        self.identifier,
                    )
                    return False

                companion_cred = self._get_companion_credential()
                if companion_cred:
                    self._apply_companion_credential(config, companion_cred)
                else:
                    _LOGGER.info(
                        "No stored Companion credentials for Apple TV at %s; pairing is required",
                        self.host,
                    )

                try:
                    self.atv = await self._connect_companion(config, loop)
                except (AuthenticationError, NotPairedError) as exc:
                    _LOGGER.warning(
                        "Apple TV not paired for Companion (or credentials invalid). "
                        "Reconfigure/re-pair the integration to restore push updates. (%s)",
                        type(exc).__name__,
                    )
                    # Not recoverable automatically: stop background reconnect loop until user re-pairs.
                    self._should_reconnect = False
                    await self._handle_disconnect()
                    await self._set_state(False, "not_paired")
                    return False
                except PairingError as exc:
                    _LOGGER.warning("Apple TV pairing error: %s", exc)
                    await self._handle_disconnect()
                    return False

                self.push_updater = getattr(self.atv, "push_updater", None)
                if self.push_updater:
                    self._listener = ATVPushListener(self)
                    self.push_updater.listener = self._listener
                    self.push_updater.start()
                else:
                    _LOGGER.warning("pyatv push updater unavailable; push updates disabled")

                await self._update_state()
                _LOGGER.info("Connected to Apple TV via Companion, active=%s", self._current_state)
                self._reconnect_backoff = 10.0
                return True
            except Exception as ex:
                error_type = type(ex).__name__
                error_msg = str(ex)
                _LOGGER.warning(
                    "Failed to connect to Apple TV at %s: %s (%s).",
                    self.host,
                    error_msg,
                    error_type,
                )
                _LOGGER.debug("Full connection error traceback:", exc_info=True)
                await self._handle_disconnect()
                if self._should_reconnect:
                    self._schedule_reconnect()
                return False

    async def async_disconnect(self) -> None:
        """Disconnect from Apple TV."""
        async with self._lock:
            self._should_reconnect = False
            if self._reconnect_task:
                self._reconnect_task.cancel()
                try:
                    await self._reconnect_task
                except asyncio.CancelledError:
                    pass
                self._reconnect_task = None
            await self._handle_disconnect()

    async def _handle_disconnect(self) -> None:
        """Handle disconnection with grace period."""
        if self._debounce_task:
            self._debounce_task.cancel()
            self._debounce_task = None

        # Cancel all listener tasks
        for task in list(self._listener_tasks):
            task.cancel()
        self._listener_tasks.clear()

        if self.push_updater:
            try:
                self.push_updater.stop()
            except Exception:
                pass
            self.push_updater = None

        if self.atv:
            try:
                close_result = self.atv.close()
                if asyncio.iscoroutine(close_result):
                    await close_result
            except Exception:
                pass
            self.atv = None

        self._listener = None
        self._power_state = PowerState.Unknown
        self._playback_state = "unknown"

        # Start grace period (timezone-aware)
        if self._current_state and self.grace_seconds > 0:
            self._grace_until = dt_util.utcnow() + timedelta(seconds=self.grace_seconds)
            _LOGGER.info("Disconnected, holding state for %d seconds", self.grace_seconds)
        else:
            self._grace_until = None
            await self._set_state(False, "disconnected")

    def _get_companion_credential(self) -> str | None:
        """Fetch Companion credential from config entry data/options."""
        if not self.entry:
            return None

        creds = self.entry.data.get(CONF_ATV_CREDENTIALS) or self.entry.options.get(CONF_ATV_CREDENTIALS)
        if not creds:
            return None

        # If keys are Protocol objects or strings, normalize to lower-case comparison
        if isinstance(creds, dict):
            for key, value in creds.items():
                if not value:
                    continue
                if getattr(key, "name", "").lower() == "companion":
                    return value
                key_str = str(key).lower()
                if key_str == "companion":
                    return value
                if Protocol is not None and str(getattr(Protocol.Companion, "value", "")).lower() == key_str:
                    return value

        candidates = (
            "companion",
            "Companion",
            getattr(Protocol.Companion, "name", "companion"),
            str(getattr(Protocol.Companion, "value", "companion")),
            str(Protocol.Companion),
        )
        for candidate in candidates:
            if candidate in creds:
                return creds[candidate]
            if str(candidate).lower() in creds:
                return creds[str(candidate).lower()]

        return None

    def _apply_companion_credential(self, config: Any, credential: str) -> None:
        """Apply Companion credential to pyatv config."""
        try:
            if hasattr(config, "set_credentials"):
                config.set_credentials(Protocol.Companion, credential)
                _LOGGER.debug("Applied Companion credential via set_credentials")
                return
        except Exception as ex:  # noqa: BLE001
            _LOGGER.debug("set_credentials failed: %s", ex)

        try:
            creds = getattr(config, "credentials", None)
            if isinstance(creds, dict):
                creds[Protocol.Companion] = credential
                config.credentials = creds
                _LOGGER.debug("Applied Companion credential via credentials mapping")
        except Exception as ex:  # noqa: BLE001
            _LOGGER.debug("Fallback credential application failed: %s", ex)

    async def _connect_companion(self, config: Any, loop: asyncio.AbstractEventLoop):
        """Connect using Companion protocol with pyatv compatibility fallbacks."""
        try:
            return await connect(config, protocol=Protocol.Companion, loop=loop)
        except TypeError:
            # Fallback for versions that don't accept loop parameter. Do NOT fall back
            # to protocol-less connect as that can connect via AirPlay/MRP and break
            # Companion-only push updates.
            return await connect(config, protocol=Protocol.Companion)
    
    def _schedule_reconnect(self) -> None:
        """Schedule a reconnection attempt with exponential backoff."""
        if self._reconnect_task:
            return  # Already scheduled
        
        async def _reconnect_loop() -> None:
            reconnect_attempts = 0
            last_log_time = None
            while self._should_reconnect:
                try:
                    await asyncio.sleep(self._reconnect_backoff)
                    if not self._should_reconnect:
                        break
                    
                    reconnect_attempts += 1
                    # Log reconnect attempts, but rate-limit to avoid spam (log every 5 attempts or every 5 minutes)
                    should_log = False
                    if reconnect_attempts == 1 or reconnect_attempts % 5 == 0:
                        should_log = True
                    elif last_log_time:
                        loop = asyncio.get_running_loop()
                        if loop.time() - last_log_time > 300:  # 5 minutes
                            should_log = True
                    
                    if should_log:
                        _LOGGER.info("Attempting to reconnect to Apple TV (attempt %d)...", reconnect_attempts)
                        last_log_time = asyncio.get_running_loop().time()
                    
                    success = await self.async_connect()
                    if success:
                        if reconnect_attempts > 1:
                            _LOGGER.info("Successfully reconnected to Apple TV after %d attempts", reconnect_attempts)
                        self._reconnect_backoff = 10.0  # Reset on success
                        break  # Connected, exit loop
                    else:
                        # Exponential backoff: 10s -> 30s -> 60s (max)
                        self._reconnect_backoff = min(self._reconnect_backoff * 3, 60.0)
                        if should_log:
                            _LOGGER.debug("Reconnect failed, next attempt in %.0fs", self._reconnect_backoff)
                except asyncio.CancelledError:
                    break
                except Exception as ex:
                    _LOGGER.warning("Error in reconnect loop: %s", ex)
                    self._reconnect_backoff = min(self._reconnect_backoff * 3, 60.0)
            
            self._reconnect_task = None
        
        self._reconnect_task = asyncio.create_task(_reconnect_loop())

    async def _update_state(self) -> None:
        """Update state from Apple TV."""
        if not self.atv:
            _LOGGER.debug("Cannot update ATV state: not connected")
            return

        try:
            _LOGGER.debug("Updating ATV state from device at %s", self.host)
            power = getattr(self.atv, 'power', None)
            # Try to get playing interface - may not be available on all pyatv versions
            playing = getattr(self.atv, 'playing', None)
            # Metadata is more broadly available and can provide playing info in some cases.
            # Ref: pyatv public interface exposes AppleTV.metadata.playing ([pyatv.interface](https://pyatv.dev/api/interface/#pyatv.interface)).

            old_power_state = self._power_state
            old_playback_state = self._playback_state
            
            if power:
                try:
                    self._power_state = await power.power_state
                    if self._power_state != old_power_state:
                        _LOGGER.info("ATV power state changed: %s -> %s", old_power_state, self._power_state)
                except Exception as ex:
                    _LOGGER.debug("Error getting power state: %s", ex)

            if playing:
                try:
                    playing_info = await playing.get_playing()
                    self._playback_state = self._playback_state_from_playing(playing_info)
                    if self._playback_state != old_playback_state:
                        _LOGGER.info("ATV playback state changed: %s -> %s", old_playback_state, self._playback_state)
                except Exception as ex:
                    _LOGGER.debug("Error getting playing state: %s", ex)
            else:
                # If playing interface is not available, state will come from push updates
                _LOGGER.debug("Playing interface not available, will rely on push updates for playback state")

            # If playback is still unknown, try metadata.playing as a secondary source.
            if self._playback_state in ("unknown",) or not self._playback_state:
                try:
                    meta_playing = await self._safe_get_playing(self.atv)
                    if meta_playing is not None:
                        meta_state = self._playback_state_from_playing(meta_playing)
                        if meta_state and meta_state != self._playback_state:
                            _LOGGER.debug(
                                "ATV playback state inferred via metadata: %s -> %s",
                                self._playback_state,
                                meta_state,
                            )
                            self._playback_state = meta_state
                except Exception:  # noqa: BLE001
                    pass

            old_active = self._current_state
            active = self._compute_active()
            _LOGGER.debug("ATV active computation: power=%s, playback=%s, active_mode=%s -> active=%s", 
                         self._power_state, self._playback_state, self.active_mode, active)
            
            if active != self._current_state:
                _LOGGER.info("ATV active state changed: %s -> %s (playback=%s, power=%s)", 
                           old_active, active, self._playback_state, self._power_state)
                await self._set_state(active, self._playback_state)
            else:
                self._last_update = dt_util.utcnow()

        except Exception as ex:
            _LOGGER.warning("Error updating ATV state: %s", ex)

    async def _safe_get_playing(self, atv: Any) -> Playing | None:
        """Safely read metadata.playing across pyatv versions (best effort).

        Some versions expose metadata.playing as:
        - a property returning Playing
        - a coroutine function
        - an awaitable
        """
        md = getattr(atv, "metadata", None)
        if not md:
            return None

        playing_attr = getattr(md, "playing", None)
        if playing_attr is None:
            return None

        try:
            if callable(playing_attr):
                return await playing_attr()
            # If it's awaitable, try awaiting it; otherwise treat as value.
            if asyncio.iscoroutine(playing_attr):
                return await playing_attr
            return playing_attr
        except TypeError:
            # Some variants require awaiting the attribute
            try:
                return await playing_attr  # type: ignore[misc]
            except Exception:  # noqa: BLE001
                return None
        except Exception:  # noqa: BLE001
            return None

    def _playback_state_from_playing(self, playing: Playing | None) -> str:
        """Get playback state string from Playing object."""
        if not playing:
            return "idle"
        state = getattr(playing, "device_state", None)
        if state == DeviceState.Playing:
            return "playing"
        if state == DeviceState.Paused:
            return "paused"
        # Treat Loading/Seeking as "playing" for activity detection (high-signal).
        if state == DeviceState.Loading:
            return "playing"
        if hasattr(DeviceState, "Seeking") and state == getattr(DeviceState, "Seeking"):
            return "playing"
        return "idle"

    def _compute_active(self) -> bool:
        """Compute if Apple TV should be considered active."""
        # Check grace period first
        if self._grace_until and dt_util.utcnow() < self._grace_until:
            return self._current_state  # Hold last state

        if self.active_mode == ATV_ACTIVE_MODE_POWER_ON:
            return self._power_state == PowerState.On

        if self.active_mode == ATV_ACTIVE_MODE_PLAYING_ONLY:
            return self._playback_state == "playing"

        # playing_or_paused (default)
        return self._playback_state in ("playing", "paused")

    async def _set_state(self, active: bool, playback_state: str) -> None:
        """Set state with debouncing."""
        # Early return if disconnected
        if not self.atv and not self._grace_until:
            return
        
        if self._debounce_task:
            self._debounce_task.cancel()
            try:
                await self._debounce_task
            except asyncio.CancelledError:
                pass
            self._debounce_task = None

        async def _debounced_set():
            try:
                await asyncio.sleep(self.debounce_seconds)
                if not self.atv and not self._grace_until:
                    return  # Disconnected and grace expired

                old_state = self._current_state
                self._current_state = active
                self._playback_state = playback_state
                self._last_update = dt_util.utcnow()

                if old_state != active:
                    _LOGGER.info("ATV state transition: %s -> %s (playback=%s, power=%s)", 
                               old_state, active, playback_state, self._power_state)
                else:
                    _LOGGER.debug("ATV state unchanged: active=%s, playback=%s", active, playback_state)

                if self.state_callback:
                    _LOGGER.debug("Calling state callback with active=%s, playback=%s", active, playback_state)
                    self.state_callback(active, playback_state)
            except asyncio.CancelledError:
                pass  # Expected when cancelled

        self._debounce_task = asyncio.create_task(_debounced_set())

    @property
    def is_active(self) -> bool:
        """Return if Apple TV is active."""
        if self._grace_until and dt_util.utcnow() < self._grace_until:
            return self._current_state
        return self._current_state

    @property
    def playback_state(self) -> str:
        """Return playback state."""
        return self._playback_state

    @property
    def is_connected(self) -> bool:
        """Return if connected."""
        return self.atv is not None


class ATVPushListener(PushListener, PowerListener):
    """Listener for push updates."""

    def __init__(self, client: ATVClient) -> None:
        """Initialize listener."""
        self.client = client

    def playstatus_update(self, updater: PushUpdater, playstatus: Playing) -> None:
        """Handle playback status update."""
        # Check if client is still connected before creating task
        if not self.client.atv:
            return
        
        playback_state = self.client._playback_state_from_playing(playstatus)
        # Compute active using the NEW playback_state (not the stale cached one)
        # to avoid lag/incorrect transitions for playing_only/playing_or_paused modes.
        if self.client._grace_until and dt_util.utcnow() < self.client._grace_until:
            active = self.client._current_state
        elif self.client.active_mode == ATV_ACTIVE_MODE_POWER_ON:
            active = self.client._power_state == PowerState.On
        elif self.client.active_mode == ATV_ACTIVE_MODE_PLAYING_ONLY:
            active = playback_state == "playing"
        else:  # playing_or_paused
            active = playback_state in ("playing", "paused")
        
        # Create task and add to set atomically
        task = asyncio.create_task(self.client._set_state(active, playback_state))
        self.client._listener_tasks.add(task)
        task.add_done_callback(self.client._listener_tasks.discard)

    def playstatus_error(self, updater: PushUpdater, exception: Exception) -> None:
        """Handle playback status error."""
        _LOGGER.debug("Playback status error: %s", exception)

    def powerstate_update(self, old_state: PowerState, new_state: PowerState) -> None:
        """Handle power state update."""
        # Check if client is still connected before creating task
        if not self.client.atv:
            return
        
        self.client._power_state = new_state
        active = self.client._compute_active()
        
        task = asyncio.create_task(self.client._set_state(active, self.client._playback_state))
        self.client._listener_tasks.add(task)
        task.add_done_callback(self.client._listener_tasks.discard)
