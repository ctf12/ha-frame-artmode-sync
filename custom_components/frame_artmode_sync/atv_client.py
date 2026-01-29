"""Apple TV client using pyatv."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable

from pyatv import connect, scan, pair
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
    DEFAULT_ATV_DEBOUNCE_SECONDS,
    DEFAULT_ATV_GRACE_SECONDS_ON_DISCONNECT,
)

_LOGGER = logging.getLogger(__name__)


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
                results = None
                
                _LOGGER.info("Scanning for Apple TV at %s (identifier=%s)", self.host, self.identifier)
                
                # Try targeted scan first (faster if device is awake)
                try:
                    if self.identifier:
                        _LOGGER.debug("Scanning by identifier: %s", self.identifier)
                        try:
                            results = await scan(loop=loop, identifier=self.identifier, timeout=10)
                        except TypeError:
                            results = await scan(identifier=self.identifier, timeout=10)
                    else:
                        _LOGGER.debug("Scanning by host: %s", self.host)
                        try:
                            results = await scan(loop=loop, hosts=[self.host], timeout=10)
                        except TypeError:
                            results = await scan(hosts=[self.host], timeout=10)
                except Exception as scan_ex:
                    _LOGGER.debug("Targeted scan failed: %s", scan_ex)
                    results = None

                # If targeted scan failed, try network-wide scan (device might be sleeping)
                if not results:
                    _LOGGER.info("Targeted scan found nothing, trying network-wide scan (device may be sleeping)...")
                    try:
                        try:
                            results = await scan(loop=loop, timeout=15)
                        except TypeError:
                            results = await scan(timeout=15)
                        
                        # Filter results to find our device
                        if results:
                            matching = []
                            for atv in results:
                                if self.identifier and str(atv.identifier) == self.identifier:
                                    matching.append(atv)
                                elif str(atv.address) == self.host:
                                    matching.append(atv)
                            
                            if matching:
                                results = matching
                                _LOGGER.info("Found Apple TV in network scan: %s at %s", 
                                           results[0].name, results[0].address)
                            else:
                                _LOGGER.debug("Network scan found %d devices, but none match %s/%s", 
                                            len(results), self.host, self.identifier)
                                results = None
                    except Exception as network_scan_ex:
                        _LOGGER.debug("Network-wide scan also failed: %s", network_scan_ex)
                        results = None

                if not results:
                    _LOGGER.warning(
                        "No Apple TV found at %s (identifier=%s). "
                        "Device may be sleeping or not responding to discovery. "
                        "Will retry automatically.",
                        self.host, self.identifier
                    )
                    return False

                config = results[0]
                _LOGGER.info("Found Apple TV: %s at %s (identifier: %s)", 
                           config.name, config.address, config.identifier)

                # CRITICAL: Load saved credentials and apply to config
                if self.hass and self.entry:
                    from .storage import async_load_atv_credentials
                    saved_creds = await async_load_atv_credentials(self.hass, self.entry)
                    if saved_creds:
                        _LOGGER.debug("Loading saved Apple TV credentials")
                        # Apply credentials to config for each protocol
                        for protocol in config.protocols:
                            protocol_name = protocol.name if hasattr(protocol, 'name') else str(protocol)
                            if protocol_name in saved_creds:
                                try:
                                    # Parse credential string back to credential object
                                    # pyatv credentials are typically strings that can be passed to set_credentials
                                    cred_str = saved_creds[protocol_name]
                                    if hasattr(config, 'set_credentials'):
                                        config.set_credentials(protocol, cred_str)
                                        _LOGGER.debug("Restored credentials for protocol %s", protocol_name)
                                except Exception as cred_ex:
                                    _LOGGER.warning("Failed to restore credentials for protocol %s: %s", protocol_name, cred_ex)

                # Try to connect (may require pairing)
                try:
                    # pyatv compatibility: some versions require loop parameter
                    try:
                        self.atv = await connect(config, loop=loop)
                    except TypeError:
                        # Fallback for versions that don't accept loop parameter
                        self.atv = await connect(config)
                except Exception as conn_ex:
                    # Check if it's an authentication/pairing error
                    is_auth_error = False
                    is_pairing_error = False
                    
                    if PYATV_EXCEPTIONS_AVAILABLE:
                        is_auth_error = isinstance(conn_ex, (AuthenticationError, NotPairedError))
                        is_pairing_error = isinstance(conn_ex, PairingError)
                    else:
                        # Fallback: check error message if exceptions not available
                        error_str = str(conn_ex).lower()
                        is_auth_error = "not paired" in error_str or "authentication" in error_str
                        is_pairing_error = "pairing" in error_str and not is_auth_error
                    
                    if is_auth_error:
                        _LOGGER.warning(
                            "Apple TV at %s requires pairing. "
                            "Please pair this device using the Home Assistant Apple TV integration first, "
                            "or use 'atvremote pair' command. Error: %s",
                            self.host, conn_ex
                        )
                        # Note: We could implement pairing here, but it's better to use HA's Apple TV integration
                        # or atvremote for initial pairing, then this integration can connect
                        return False
                    elif is_pairing_error:
                        _LOGGER.warning(
                            "Apple TV pairing error at %s: %s. "
                            "Device may need to be re-paired.",
                            self.host, conn_ex
                        )
                        return False
                    # If not an auth/pairing error, continue to general error handling below
                    raise conn_ex
                
                self.push_updater = self.atv.push_updater

                self._listener = ATVPushListener(self)
                self.push_updater.listener = self._listener
                self.push_updater.start()

                # Initial state
                await self._update_state()
                _LOGGER.info("Connected to Apple TV, initial state: active=%s", self._current_state)

                return True
            except Exception as ex:
                # Log more detailed error information
                error_type = type(ex).__name__
                error_msg = str(ex)
                _LOGGER.warning(
                    "Failed to connect to Apple TV at %s: %s (%s). "
                    "This may indicate the device needs pairing, is sleeping, or network issues.",
                    self.host, error_msg, error_type
                )
                # Log full exception for debugging
                _LOGGER.debug("Full connection error traceback:", exc_info=True)
                await self._handle_disconnect()
                # Schedule reconnect attempt if enabled
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
                self.atv.close()
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

    def _playback_state_from_playing(self, playing: Playing | None) -> str:
        """Get playback state string from Playing object."""
        if not playing:
            return "idle"
        if playing.device_state == DeviceState.Playing:
            return "playing"
        if playing.device_state == DeviceState.Paused:
            return "paused"
        if playing.device_state == DeviceState.Loading:
            return "loading"
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
        active = self.client._compute_active()
        
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

