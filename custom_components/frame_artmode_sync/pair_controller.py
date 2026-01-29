"""Pair controller coordinating Apple TV and Frame TV."""

from __future__ import annotations

import asyncio
import logging
import socket
from collections import deque
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval, async_track_state_change_event
from homeassistant.util import dt as dt_util

from .atv_client import ATVClient
from .const import (
    ACTION_INPUT_SWITCH,
    ACTION_NONE,
    ACTION_REMOTE_WAKE,
    ACTION_RESYNC,
    ACTION_RESULT_FAIL,
    ACTION_RESULT_SUCCESS,
    ACTION_SET_ART_OFF,
    ACTION_SET_ART_ON,
    ACTION_TV_OFF,
    ACTION_WOL,
    ATV_ACTIVE_MODE_PLAYING_OR_PAUSED,
    BACKOFF_INITIAL,
    BACKOFF_MAX,
    BACKOFF_MULTIPLIER,
    DEFAULT_ATV_DEBOUNCE_SECONDS,
    DEFAULT_ATV_GRACE_SECONDS_ON_DISCONNECT,
    DEFAULT_REMOTE_WAKE_DELAY_SECONDS,
    DEFAULT_REMOTE_WAKE_RETRIES,
    DEFAULT_WAKE_STARTUP_GRACE_SECONDS,
    DEFAULT_WOL_BROADCAST,
    DEFAULT_WOL_DELAY_SECONDS,
    DEFAULT_WOL_RETRIES,
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_DRIFT_CORRECTION_COOLDOWN_MINUTES,
    DEFAULT_MAX_COMMANDS_PER_5MIN,
    DEFAULT_MAX_DRIFT_CORRECTIONS_PER_HOUR,
    DEFAULT_OVERRIDE_MINUTES,
    DEFAULT_RESYNC_INTERVAL_MINUTES,
    DEFAULT_RETURN_DELAY_SECONDS,
    DEFAULT_STARTUP_GRACE_SECONDS,
    DEFAULT_WAKE_RETRY_DELAY_SECONDS,
    EVENT_TYPE_ATV_OFF,
    EVENT_TYPE_ATV_ON,
    EVENT_TYPE_BREAKER_CLOSED,
    EVENT_TYPE_BREAKER_OPENED,
    EVENT_TYPE_DEGRADED,
    EVENT_TYPE_DRIFT_DETECTED,
    EVENT_TYPE_MANUAL,
    EVENT_TYPE_OVERRIDE_ACTIVATED,
    EVENT_TYPE_OVERRIDE_CLEARED,
    EVENT_TYPE_PRESENCE_CHANGE,
    EVENT_TYPE_RESYNC,
    EVENT_TYPE_STARTUP,
    EVENT_TYPE_TIME_WINDOW_CHANGE,
    HEALTH_BREAKER_OPEN,
    HEALTH_DEGRADED,
    HEALTH_OK,
    INPUT_MODE_HDMI1,
    INPUT_MODE_NONE,
    MAX_RECENT_EVENTS,
    MAX_WAKE_ATTEMPTS,
    MODE_ART,
    MODE_ATV,
    MODE_OFF,
    NIGHT_BEHAVIOR_DO_NOTHING,
    PHASE_BREAKER_OPEN,
    PHASE_DEGRADED,
    PHASE_DRY_RUN,
    PHASE_IDLE,
    PHASE_MANUAL_OVERRIDE,
    PHASE_RETURNING_TO_ART,
    PHASE_SWITCHING_TO_ATV,
)
from .decision import compute_desired_mode, is_time_in_window, parse_time_string
from .entity_helpers import ensure_isoformat, normalize_datetime
from .frame_client import FrameClient
from .storage import async_load_token, async_save_token

_LOGGER = logging.getLogger(__name__)


class PairController:
    """Controller for one Frame/Apple TV pair."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        pair_name: str,
        frame_host: str,
        frame_port: int,
        frame_mac: str | None,
        apple_tv_host: str,
        apple_tv_identifier: str | None,
        tag: str,
        config: dict[str, Any],
    ) -> None:
        """Initialize pair controller."""
        self.hass = hass
        self.entry_id = entry_id
        self.pair_name = pair_name
        self.tag = tag
        self.config = config

        # Clients
        base_pairing_name = config.get("base_pairing_name", "FrameArtSync")
        client_name = f"{base_pairing_name}-{tag}"[:18]
        self.frame_client = FrameClient(frame_host, frame_port, None, client_name)
        
        # Get entry for credential loading
        entries = [
            e
            for e in self.hass.config_entries.async_entries("frame_artmode_sync")
            if e.entry_id == self.entry_id
        ]
        entry = entries[0] if entries else None
        
        self.atv_client = ATVClient(
            apple_tv_host,
            apple_tv_identifier,
            config.get("atv_active_mode", ATV_ACTIVE_MODE_PLAYING_OR_PAUSED),
            config.get("atv_debounce_seconds", DEFAULT_ATV_DEBOUNCE_SECONDS),
            config.get("atv_grace_seconds_on_disconnect", DEFAULT_ATV_GRACE_SECONDS_ON_DISCONNECT),
            self._on_atv_state_changed,
            hass=self.hass,
            entry=entry,
        )

        self.frame_mac = frame_mac
        self.fallback_media_player = config.get("fallback_ha_media_player_entity")
        
        # TV state source and wake configuration
        self.tv_state_source_entity_id = config.get("tv_state_source_entity_id")
        self.wake_remote_entity_id = config.get("wake_remote_entity_id")
        self.enable_remote_wake = config.get("enable_remote_wake", True)
        self.enable_wol_fallback = config.get("enable_wol_fallback", False)
        self.remote_wake_retries = config.get("remote_wake_retries", DEFAULT_REMOTE_WAKE_RETRIES)
        self.remote_wake_delay = config.get("remote_wake_delay_secs", DEFAULT_REMOTE_WAKE_DELAY_SECONDS)
        self.wol_retries = config.get("wol_retries", DEFAULT_WOL_RETRIES)
        self.wol_delay = config.get("wol_delay_secs", DEFAULT_WOL_DELAY_SECONDS)
        self.wol_broadcast = config.get("wol_broadcast", DEFAULT_WOL_BROADCAST)
        self.wake_startup_grace = config.get("startup_grace_secs", DEFAULT_WAKE_STARTUP_GRACE_SECONDS)
        
        # Rate limiting for degraded/unreachable logs
        self._last_degraded_log_time: float | None = None
        self._degraded_log_interval = 300.0  # 5 minutes
        
        # Track startup time for grace period (timezone-aware)
        self._startup_time = dt_util.utcnow()

        # State
        self._enabled = config.get("enabled", True)
        self._atv_active = False
        self._atv_playback_state = "unknown"
        self._desired_mode: str | None = None
        self._previous_desired_mode: str | None = None
        self._actual_artmode: bool | None = None
        self._in_active_hours = False
        self._home_ok: bool | None = None
        self._phase = PHASE_IDLE
        self._manual_override_until: datetime | None = None
        self._last_trigger = EVENT_TYPE_STARTUP
        self._last_action = ACTION_NONE
        self._last_action_result = ACTION_RESULT_SUCCESS
        self._last_action_ts: datetime | None = None
        self._last_error: str | None = None
        self._pair_health = HEALTH_OK

        # Safety
        self._lock = asyncio.Lock()
        self._cooldown_until: datetime | None = None
        self._cooldown_until_monotonic: float | None = None  # Monotonic time for duration
        self._command_times: deque[datetime] = deque()
        self._breaker_open = False
        self._breaker_open_until: datetime | None = None
        self._breaker_open_until_monotonic: float | None = None  # Monotonic time for duration
        self._connection_backoff_until: datetime | None = None
        self._connection_backoff_until_monotonic: float | None = None  # Monotonic time for duration
        self._connection_backoff_delay = BACKOFF_INITIAL
        self._manual_override_until_monotonic: float | None = None  # Monotonic time for duration
        self._last_backoff_log_time: float | None = None  # Prevent event spam
        self._last_service_call_time: float | None = None  # Service rate limiting

        # Drift correction
        self._drift_corrections_this_hour: deque[datetime] = deque()
        self._last_drift_correction: datetime | None = None
        self._last_drift_at: datetime | None = None
        self._consecutive_drifts = 0

        # Tasks
        self._return_to_art_task: asyncio.Task | None = None
        self._resync_task: asyncio.Task | None = None
        self._startup_grace_task: asyncio.Task | None = None

        # Events log
        self._recent_events: deque[dict[str, Any]] = deque(maxlen=MAX_RECENT_EVENTS)

        # Statistics
        self._connect_fail_count = 0
        self._command_fail_count = 0
        self._verify_fail_count = 0
        self._connection_failures = 0

        # Trackers
        self._presence_entity_id: str | None = config.get("presence_entity_id")
        self._presence_tracker: Any = None
        self._resync_unsub: Any = None

    async def async_setup(self) -> None:
        """Set up the pair controller."""
        # Load Frame token
        from homeassistant.config_entries import ConfigEntry

        # Find entry
        entries = [
            e
            for e in self.hass.config_entries.async_entries("frame_artmode_sync")
            if e.entry_id == self.entry_id
        ]
        entry = entries[0] if entries else None
        
        # Backwards compatibility: if TV state source not configured, auto-discover
        if not self.tv_state_source_entity_id:
            # Try to discover a Samsung media_player entity matching the frame host or pair name
            # Look for entities with host in name/attributes or matching pair_name
            frame_host_short = self.frame_client.host.split('.')[-1] if '.' in self.frame_client.host else self.frame_client.host
            for state in self.hass.states.async_all("media_player"):
                entity_id = state.entity_id
                entity_name = state.attributes.get("friendly_name", "").lower()
                if (
                    "samsung" in entity_name.lower()
                    or "frame" in entity_name.lower()
                    or frame_host_short.lower() in entity_name.lower()
                    or self.pair_name.lower() in entity_name.lower()
                ):
                    self.tv_state_source_entity_id = entity_id
                    _LOGGER.info("Auto-discovered TV state source entity: %s", entity_id)
                    # Update config to persist this choice
                    if entry:
                        new_options = dict(entry.options)
                        new_options["tv_state_source_entity_id"] = entity_id
                        self.hass.config_entries.async_update_entry(entry, options=new_options)
                    break
        
        # Backwards compatibility: migrate old wake_method setting to new toggles
        old_wake_method = self.config.get("wake_method")
        needs_migration = False
        new_options = dict(entry.options) if entry else {}
        
        if old_wake_method:
            # Migrate from old single wake_method to new toggles
            if old_wake_method == "remote_key_power":
                if not new_options.get("enable_remote_wake"):
                    self.enable_remote_wake = True
                    new_options["enable_remote_wake"] = True
                    needs_migration = True
            elif old_wake_method == "wol":
                # WOL was primary before, now make it fallback
                if not new_options.get("enable_wol_fallback"):
                    self.enable_wol_fallback = True
                    new_options["enable_wol_fallback"] = True
                    needs_migration = True
            # Remove old wake_method setting
            if "wake_method" in new_options:
                del new_options["wake_method"]
                needs_migration = True
        
        # Set defaults if not configured
        if "enable_remote_wake" not in new_options:
            # Default to enabled if remote entity is available
            self.enable_remote_wake = bool(self.wake_remote_entity_id)
            new_options["enable_remote_wake"] = self.enable_remote_wake
            needs_migration = True
        
        if "enable_wol_fallback" not in new_options:
            # Default to disabled (WOL is last-resort only)
            self.enable_wol_fallback = False
            new_options["enable_wol_fallback"] = False
            needs_migration = True
        
        # Migrate old retry settings to new names
        if "wake_retries" in new_options and "remote_wake_retries" not in new_options:
            new_options["remote_wake_retries"] = new_options["wake_retries"]
            needs_migration = True
        if "wake_retry_delay_seconds" in new_options and "remote_wake_delay_secs" not in new_options:
            new_options["remote_wake_delay_secs"] = new_options["wake_retry_delay_seconds"]
            needs_migration = True
        if "wake_startup_grace_seconds" in new_options and "startup_grace_secs" not in new_options:
            new_options["startup_grace_secs"] = new_options["wake_startup_grace_seconds"]
            needs_migration = True
        
        # Apply migrated options
        if needs_migration and entry:
            self.hass.config_entries.async_update_entry(entry, options=new_options)
            _LOGGER.info("Migrated wake configuration: remote_wake=%s, wol_fallback=%s", 
                        self.enable_remote_wake, self.enable_wol_fallback)
        
        if entry:
            token = await async_load_token(self.hass, entry)
            if token:
                self.frame_client.token = token
                _LOGGER.info("Loaded saved Frame TV token for %s", self.frame_client.host)
            else:
                _LOGGER.info("No saved Frame TV token found for %s - will pair on first connection", self.frame_client.host)

        # Connect clients with timeouts
        async def token_save_callback(token: str) -> None:
            if entry:
                await async_save_token(self.hass, entry, token)
        
        # Connect Frame TV (with timeout)
        try:
            await asyncio.wait_for(
                self.frame_client.async_connect(token_callback=token_save_callback),
                timeout=20.0
            )
        except asyncio.TimeoutError:
            _LOGGER.warning("Frame TV connection timed out")
        except Exception as ex:
            _LOGGER.warning("Frame TV connection failed: %s", ex)
        
        # Connect Apple TV (with timeout)
        # Increased timeout to 35s to allow for:
        # - Targeted scan: 10s
        # - Network-wide scan fallback: 15s
        # - Connection establishment: ~5s
        # - Buffer: ~5s
        try:
            await asyncio.wait_for(
                self.atv_client.async_connect(),
                timeout=35.0
            )
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Apple TV connection timed out after 35s. "
                "Device may be sleeping or unreachable. "
                "Will continue to retry in background."
            )
        except Exception as ex:
            _LOGGER.warning("Apple TV connection failed: %s", ex)

        # Startup grace
        grace_seconds = self.config.get("startup_grace_seconds", DEFAULT_STARTUP_GRACE_SECONDS)
        if grace_seconds > 0:
            self._startup_grace_task = asyncio.create_task(
                self._async_startup_grace(grace_seconds)
            )

        # Setup presence tracking
        if self._presence_entity_id:
            self._presence_tracker = async_track_state_change_event(
                self.hass,
                [self._presence_entity_id],
                self._on_presence_changed,
            )

        # Setup resync timer
        resync_interval = self.config.get("resync_interval_minutes", DEFAULT_RESYNC_INTERVAL_MINUTES)
        if resync_interval > 0:
            self._resync_unsub = async_track_time_interval(
                self.hass,
                self._async_resync_timer,
                timedelta(minutes=resync_interval),
            )

        # Initial state update (all within lock via _compute_and_enforce)
        await self._compute_and_enforce()

    async def _async_startup_grace(self, seconds: int) -> None:
        """Wait for startup grace period."""
        await asyncio.sleep(seconds)
        await self._compute_and_enforce()

    async def async_cleanup(self) -> None:
        """Clean up resources."""
        # Cancel and await all tasks
        tasks_to_cancel = []
        if self._return_to_art_task:
            self._return_to_art_task.cancel()
            tasks_to_cancel.append(self._return_to_art_task)
            self._return_to_art_task = None
        if self._resync_task:
            self._resync_task.cancel()
            tasks_to_cancel.append(self._resync_task)
            self._resync_task = None
        if self._startup_grace_task:
            self._startup_grace_task.cancel()
            tasks_to_cancel.append(self._startup_grace_task)
            self._startup_grace_task = None
        
        # Await all cancelled tasks to handle CancelledError
        for task in tasks_to_cancel:
            try:
                await task
            except asyncio.CancelledError:
                pass  # Expected
        
        if self._presence_tracker:
            self._presence_tracker()
        if self._resync_unsub:
            self._resync_unsub()

        await self.atv_client.async_disconnect()
        await self.frame_client.async_disconnect()

    @callback
    def _on_atv_state_changed(self, active: bool, playback_state: str) -> None:
        """Handle Apple TV state change."""
        self.hass.async_create_task(self._handle_atv_state_change(active, playback_state))

    async def _handle_atv_state_change(self, active: bool, playback_state: str) -> None:
        """Handle Apple TV state change (async)."""
        old_active = self._atv_active
        self._atv_active = active
        self._atv_playback_state = playback_state

        _LOGGER.info("[atv_state_change] ATV state changed: active=%s -> %s, playback=%s", 
                    old_active, active, playback_state)

        if old_active != active:
            # Cancel return-to-art timer if ATV became active
            # Cancel without awaiting to avoid deadlock if task is waiting for lock
            if active and self._return_to_art_task:
                _LOGGER.debug("[atv_state_change] ATV became active, cancelling return-to-art timer")
                self._return_to_art_task.cancel()
                self._return_to_art_task = None

            trigger = EVENT_TYPE_ATV_ON if active else EVENT_TYPE_ATV_OFF
            self._last_trigger = trigger
            self._log_event(trigger, ACTION_RESULT_SUCCESS, f"ATV {'activated' if active else 'deactivated'}")
            _LOGGER.info("[atv_state_change] Triggering enforcement due to ATV state change")
            await self._compute_and_enforce()
        else:
            _LOGGER.debug("[atv_state_change] ATV active state unchanged (%s), skipping enforcement", active)

    @callback
    def _on_presence_changed(self, event: Event) -> None:
        """Handle presence state change."""
        # Schedule through compute_and_enforce which acquires lock
        self.hass.async_create_task(self._compute_and_enforce(trigger=EVENT_TYPE_PRESENCE_CHANGE))

    async def _update_active_hours(self) -> None:
        """Update active hours state."""
        # Parse time strings from config (use normalize_time for safety)
        from .entity_helpers import normalize_time
        start_str = self.config.get("active_start", "06:00:00")
        end_str = self.config.get("active_end", "22:00:00")
        
        start_time = normalize_time(start_str) or parse_time_string(start_str)
        end_time = normalize_time(end_str) or parse_time_string(end_str)

        now = dt_util.utcnow()
        was_in_hours = self._in_active_hours
        self._in_active_hours = is_time_in_window(now, start_time, end_time)

        _LOGGER.debug("Active hours check: now=%s, window=%s-%s, in_active_hours=%s", 
                     now.strftime("%H:%M:%S"), start_time, end_time, self._in_active_hours)

        if was_in_hours != self._in_active_hours:
            _LOGGER.info("Active hours changed: %s -> %s (window: %s-%s)", 
                        was_in_hours, self._in_active_hours, start_time, end_time)
            self._last_trigger = EVENT_TYPE_TIME_WINDOW_CHANGE
            self._log_event(
                EVENT_TYPE_TIME_WINDOW_CHANGE,
                ACTION_RESULT_SUCCESS,
                f"Active hours: {'started' if self._in_active_hours else 'ended'}",
            )

    async def _update_presence(self, trigger: str | None = None) -> None:
        """Update presence state (must be called within lock context)."""
        if not self._presence_entity_id:
            self._home_ok = None
            _LOGGER.debug("No presence entity configured, home_ok=None")
            return

        try:
            old_home_ok = self._home_ok
            state_obj = self.hass.states.get(self._presence_entity_id)
            if not state_obj:
                _LOGGER.debug("Presence entity %s not found or unavailable", self._presence_entity_id)
                self._home_ok = None
                # Trigger if state changed from known to unknown
                # Use locked version since we're called from within lock
                if old_home_ok is not None and trigger:
                    _LOGGER.info("Presence changed: %s -> None (entity unavailable)", old_home_ok)
                    await self._compute_and_enforce_locked(trigger=trigger)
                return

            state = state_obj.state.lower()
            _LOGGER.debug("Presence entity %s state: %s", self._presence_entity_id, state_obj.state)
            home_states = [
                s.strip().lower()
                for s in self.config.get("home_states", "home,on,true,True").split(",")
            ]
            away_states = [
                s.strip().lower()
                for s in self.config.get("away_states", "not_home,away,off,false,False").split(",")
            ]

            if state in home_states:
                self._home_ok = True
                if old_home_ok != self._home_ok:
                    _LOGGER.info("Presence changed: %s -> True (home) via entity %s", old_home_ok, self._presence_entity_id)
                if old_home_ok != self._home_ok and trigger:
                    await self._compute_and_enforce_locked(trigger=trigger)
            elif state in away_states:
                self._home_ok = False
                if old_home_ok != self._home_ok:
                    _LOGGER.info("Presence changed: %s -> False (away) via entity %s", old_home_ok, self._presence_entity_id)
                if old_home_ok != self._home_ok and trigger:
                    await self._compute_and_enforce_locked(trigger=trigger)
            else:
                # Unknown state
                unknown_behavior = self.config.get("unknown_behavior", "ignore")
                _LOGGER.debug("Presence entity %s has unknown state '%s', behavior=%s", 
                            self._presence_entity_id, state_obj.state, unknown_behavior)
                if unknown_behavior == "treat_as_home":
                    self._home_ok = True
                    if old_home_ok != self._home_ok:
                        _LOGGER.info("Presence changed: %s -> True (treat_as_home) via entity %s", old_home_ok, self._presence_entity_id)
                    if old_home_ok != self._home_ok and trigger:
                        await self._compute_and_enforce_locked(trigger=trigger)
                elif unknown_behavior == "treat_as_away":
                    self._home_ok = False
                    if old_home_ok != self._home_ok:
                        _LOGGER.info("Presence changed: %s -> False (treat_as_away) via entity %s", old_home_ok, self._presence_entity_id)
                    if old_home_ok != self._home_ok and trigger:
                        await self._compute_and_enforce_locked(trigger=trigger)
                else:
                    # ignore - set to None
                    self._home_ok = None
                    if old_home_ok != self._home_ok:
                        _LOGGER.info("Presence changed: %s -> None (ignore unknown) via entity %s", old_home_ok, self._presence_entity_id)
                    # Trigger if state changed from known to unknown
                    if old_home_ok is not None and trigger:
                        await self._compute_and_enforce_locked(trigger=trigger)

        except Exception as ex:
            _LOGGER.error("Error updating presence: %s", ex)
            old_home_ok = self._home_ok
            self._home_ok = None
            if old_home_ok is not None and trigger:
                await self._compute_and_enforce_locked(trigger=trigger)

    async def _compute_and_enforce(
        self, trigger: str | None = None, force: bool = False
    ) -> None:
        """Compute desired mode and enforce if needed (public entrypoint, acquires lock)."""
        async with self._lock:
            await self._compute_and_enforce_locked(trigger=trigger, force=force)

    async def _compute_and_enforce_locked(
        self, trigger: str | None = None, force: bool = False
    ) -> None:
        """Compute desired mode and enforce if needed (expects lock to be held)."""
        if not force and not self._should_enforce():
            return
        
        # Convert monotonic time checks to wall-clock for status display
        # But use monotonic for actual enforcement decisions

        # Update active hours (doesn't trigger enforcement, just updates state)
        await self._update_active_hours()

        if trigger:
            self._last_trigger = trigger

        # Compute desired mode
        desired = compute_desired_mode(
            atv_active=self._atv_active,
            in_active_hours=self._in_active_hours,
            night_behavior=self.config.get("night_behavior", "force_off"),
            presence_mode=self.config.get("presence_mode", "disabled"),
            home_ok=self._home_ok,
            away_policy=self.config.get("away_policy", "disabled"),
            unknown_behavior=self.config.get("unknown_behavior", "ignore"),
        )

        if desired != self._desired_mode:
            _LOGGER.info("Desired mode changed: %s -> %s (atv_active=%s, in_active_hours=%s, home_ok=%s, trigger=%s)", 
                        self._desired_mode, desired, self._atv_active, self._in_active_hours, self._home_ok, trigger)
        else:
            _LOGGER.debug("Desired mode unchanged: %s (atv_active=%s, in_active_hours=%s, home_ok=%s)", 
                         desired, self._atv_active, self._in_active_hours, self._home_ok)

        self._desired_mode = desired

        # Check if we should enforce (use monotonic time for duration)
        now_monotonic = asyncio.get_running_loop().time()
        now_utc = dt_util.utcnow()
        override_until = normalize_datetime(self._manual_override_until)
        if self._manual_override_until_monotonic is not None:
            if now_monotonic < self._manual_override_until_monotonic:
                # Still in override (monotonic), but check if wall-clock expired for display
                if override_until and now_utc < override_until:
                    pass  # Both agree, still active
                else:
                    # Wall-clock expired but monotonic didn't (clock jumped backward), use wall-clock
                    self._manual_override_until = None
                    self._manual_override_until_monotonic = None
            else:
                # Monotonic expired, clear override
                self._manual_override_until = None
                self._manual_override_until_monotonic = None
        
        # Check override state (use wall-clock as primary check, monotonic as fallback)
        # Note: now_utc is defined above, use it here
        if override_until and now_utc < override_until:
            # Still in override
            if self._desired_mode == MODE_ATV:
                # ATV became active, clear override
                self._manual_override_until = None
                self._manual_override_until_monotonic = None
                self._log_event(
                    EVENT_TYPE_OVERRIDE_CLEARED,
                    ACTION_RESULT_SUCCESS,
                    "Override cleared: ATV activated",
                )
            else:
                # Still in override, don't enforce
                self._phase = PHASE_MANUAL_OVERRIDE
                await self._fire_event()
                return

        # Handle return-to-art delay
        # Check if transitioning from ATV to ART (not ATV active)
        previous_was_atv = self._previous_desired_mode == MODE_ATV
        if desired == MODE_ART and not self._atv_active and previous_was_atv:
            # ATV just turned off, schedule delayed return
            _LOGGER.info("[enforce] ATV turned off, scheduling delayed return to Art Mode")
            await self._schedule_return_to_art()
            self._previous_desired_mode = desired
            return

        # Store current as previous for next iteration
        self._previous_desired_mode = desired

        # Enforce (unless night_behavior is do_nothing and outside active hours)
        if not (not self._in_active_hours and self.config.get("night_behavior") == NIGHT_BEHAVIOR_DO_NOTHING):
            await self._enforce_desired_mode(desired)
        else:
            # Just update status, don't enforce
            self._phase = PHASE_IDLE
            await self._fire_event()

    def _should_enforce(self) -> bool:
        """Check if we should enforce (cooldown, startup grace, etc.)."""
        if self._startup_grace_task and not self._startup_grace_task.done():
            _LOGGER.debug("[enforce] Enforcement blocked: still in startup grace period")
            return False  # Still in startup grace

        # Use monotonic time for cooldown check (resilient to clock changes)
        if self._cooldown_until_monotonic is not None:
            loop = asyncio.get_running_loop()
            if loop.time() < self._cooldown_until_monotonic:
                remaining = int(self._cooldown_until_monotonic - loop.time())
                _LOGGER.debug("[enforce] Enforcement blocked: cooldown active (%ds remaining)", remaining)
                return False  # In cooldown
            # Cooldown expired, clear it
            _LOGGER.debug("[enforce] Cooldown expired, clearing")
            self._cooldown_until_monotonic = None
            self._cooldown_until = None

        return True

    async def _schedule_return_to_art(self) -> None:
        """Schedule delayed return to Art Mode (must be called within lock)."""
        if self._return_to_art_task:
            self._return_to_art_task.cancel()
            # Don't await here - we're holding lock and task might be waiting for it
            self._return_to_art_task = None

        delay = self.config.get("return_delay_seconds", DEFAULT_RETURN_DELAY_SECONDS)

        async def _return_task():
            try:
                await asyncio.sleep(delay)
                # Re-acquire lock and check state
                async with self._lock:
                    # Check if ATV is still inactive and desired is still ART
                    if not self._atv_active and self._desired_mode == MODE_ART:
                        await self._enforce_desired_mode(MODE_ART)
            except asyncio.CancelledError:
                pass  # Expected when cancelled

        self._return_to_art_task = asyncio.create_task(_return_task())

    async def _enforce_desired_mode(self, desired: str) -> None:
        """Enforce desired mode with safety checks (must be called within lock)."""
        _LOGGER.debug("[enforce] _enforce_desired_mode called with desired=%s", desired)
        
        if not self._enabled:
            _LOGGER.info("[enforce] Enforcement blocked: integration disabled")
            self._phase = PHASE_IDLE
            await self._fire_event()
            return

        if self.config.get("dry_run", False):
            _LOGGER.info("[enforce] DRY RUN: Would set %s (no actual command sent)", desired)
            self._phase = PHASE_DRY_RUN
            self._log_event(EVENT_TYPE_MANUAL, ACTION_RESULT_SUCCESS, f"DRY RUN: Would set {desired}")
            await self._fire_event()
            return

        # Check breaker (manual services bypass this, but they call enforce_desired_mode directly)
        if self._breaker_open:
            _LOGGER.warning("[enforce] Enforcement blocked: circuit breaker open")
            self._phase = PHASE_BREAKER_OPEN
            self._log_event(EVENT_TYPE_MANUAL, ACTION_RESULT_FAIL, "Enforcement blocked: circuit breaker open")
            await self._fire_event()
            return

        # Check connection backoff (use monotonic time for duration)
        loop = asyncio.get_running_loop()
        now_monotonic = loop.time()
        if self._connection_backoff_until_monotonic is not None:
            if now_monotonic < self._connection_backoff_until_monotonic:
                remaining = int(self._connection_backoff_until_monotonic - now_monotonic)
                # Rate-limit: only log this event once per backoff period (check if already logged)
                if self._last_backoff_log_time != self._connection_backoff_until_monotonic:
                    _LOGGER.info("[enforce] Enforcement blocked: connection backoff active (%ds remaining)", remaining)
                    self._log_event(EVENT_TYPE_MANUAL, ACTION_RESULT_FAIL, f"Enforcement blocked: connection backoff active ({remaining}s remaining)")
                    self._last_backoff_log_time = self._connection_backoff_until_monotonic
                await self._fire_event()
                return
            else:
                # Backoff expired, clear it
                _LOGGER.debug("[enforce] Connection backoff expired, clearing")
                self._connection_backoff_until_monotonic = None
                self._connection_backoff_until = None
                self._last_backoff_log_time = None

        # Check TV reachability and state
        _LOGGER.debug("Checking TV reachability and state...")
        tv_reachable = await self._check_tv_reachable()
        tv_state = await self._get_tv_state()
        _LOGGER.info("TV state check: reachable=%s, entity_state=%s", tv_reachable, tv_state)
        
        # Read actual state (may trigger connection)
        _LOGGER.debug("Reading actual Art Mode state from TV...")
        actual_artmode = await self.frame_client.async_get_artmode()
        _LOGGER.info("Actual Art Mode state: %s (desired=%s)", 
                    "ON" if actual_artmode is True else ("OFF" if actual_artmode is False else "UNKNOWN"), 
                    desired)
        
        # Wake sequence: Try remote wake first, then WOL fallback only if remote fails AND TV is unreachable
        wake_attempted = False
        remote_wake_succeeded = False
        wol_fallback_attempted = False
        
        # If TV is unreachable or appears off, attempt wake
        if actual_artmode is None and not tv_reachable:
            # Step 1: Try remote wake first (primary method)
            if self.enable_remote_wake:
                remote_wake_succeeded = await self._attempt_remote_wake()
                wake_attempted = True
                
                # After remote wake, wait and re-check reachability
                if remote_wake_succeeded:
                    await asyncio.sleep(self.remote_wake_delay)
                    tv_reachable = await self._check_tv_reachable()
                    if tv_reachable:
                        actual_artmode = await self.frame_client.async_get_artmode()
            
            # Step 2: Only try WOL fallback if remote wake failed/not configured AND TV is still unreachable
            if not remote_wake_succeeded and not tv_reachable and self.enable_wol_fallback:
                wol_fallback_attempted = await self._attempt_wol_fallback()
                wake_attempted = wake_attempted or wol_fallback_attempted
                
                # After WOL, wait and re-check reachability
                if wol_fallback_attempted:
                    await asyncio.sleep(self.wol_delay)
                    tv_reachable = await self._check_tv_reachable()
                    if tv_reachable:
                        actual_artmode = await self.frame_client.async_get_artmode()
        
        # Determine if we should set degraded state
        # Only set degraded if TV is truly unreachable AND outside startup grace period
        is_in_startup_grace = False
        if self.wake_startup_grace > 0:
            now_utc = dt_util.utcnow()
            startup_elapsed = (now_utc - self._startup_time).total_seconds()
            is_in_startup_grace = startup_elapsed < self.wake_startup_grace
        
        # Check if we should mark degraded (rate-limited logging)
        should_mark_degraded = (
            actual_artmode is None 
            and not tv_reachable 
            and not is_in_startup_grace
        )
        
        if should_mark_degraded:
            # Rate-limit degraded log messages (avoid spam)
            loop = asyncio.get_running_loop()
            now_monotonic = loop.time()
            should_log_degraded = True
            
            if self._last_degraded_log_time:
                time_since_last = now_monotonic - self._last_degraded_log_time
                if time_since_last < self._degraded_log_interval:
                    should_log_degraded = False
            
            if self._pair_health == HEALTH_OK or should_log_degraded:
                self._pair_health = HEALTH_DEGRADED
                self._phase = PHASE_DEGRADED
                wake_summary = []
                if remote_wake_succeeded:
                    wake_summary.append("remote=success")
                elif self.enable_remote_wake:
                    wake_summary.append("remote=failed")
                if wol_fallback_attempted:
                    wake_summary.append("wol=attempted")
                wake_info = f" (wake: {', '.join(wake_summary)})" if wake_summary else ""
                self._log_event(EVENT_TYPE_DEGRADED, ACTION_RESULT_FAIL, 
                              f"[degraded] TV unreachable after wake attempts{wake_info}")
                if should_log_degraded:
                    self._last_degraded_log_time = now_monotonic
            await self._handle_command_failure()
            return
        elif actual_artmode is None and not tv_reachable and is_in_startup_grace:
            # TV unreachable but in startup grace - don't degrade yet
            now_utc = dt_util.utcnow()
            _LOGGER.debug("TV unreachable but in startup grace period (%d seconds remaining)", 
                         int(self.wake_startup_grace - (now_utc - self._startup_time).total_seconds()))
            await self._handle_command_failure()
            return
        
        # If we got here, either TV is reachable or state was retrieved
        if actual_artmode is not None:
            self._actual_artmode = actual_artmode
        elif tv_state is not None:
            # Use TV state from entity if websocket failed but entity reports state
            # Map media_player states to artmode: "off" -> False (artmode off), "on"/"playing"/"idle" -> True (artmode on) or None (unknown)
            if tv_state in ("off", "unavailable"):
                self._actual_artmode = False
            elif tv_state in ("on", "playing", "idle", "paused"):
                # Can't determine artmode from state alone, but TV is on
                # Try to get actual artmode from websocket, or assume unknown
                self._actual_artmode = None  # Will be determined by drift correction
            else:
                self._actual_artmode = None
        else:
            self._actual_artmode = None

        # Idempotency check
        if desired == MODE_ART and actual_artmode is True:
            # Already correct
            _LOGGER.info("No action needed: desired=ART, actual=ON (already in Art Mode)")
            self._phase = PHASE_IDLE
            self._last_action = ACTION_NONE
            await self._fire_event()
            return

        if desired == MODE_OFF and actual_artmode is False:
            # Check if TV is actually off (best effort)
            _LOGGER.info("No action needed: desired=OFF, actual=OFF (TV already off)")
            self._phase = PHASE_IDLE
            self._last_action = ACTION_NONE
            await self._fire_event()
            return

        if desired == MODE_ATV and actual_artmode is False:
            # TV is on, Art Mode is off - check if we need to switch input
            _LOGGER.info("TV already on (Art Mode OFF), checking if input switch needed (desired=ATV)")
            self._phase = PHASE_IDLE
            self._last_action = ACTION_NONE
            # Still try to switch input if needed
            await self._switch_to_atv_input()
            await self._fire_event()
            return

        # Need to change state
        _LOGGER.info("State change required: desired=%s, actual=%s -> sending command", 
                    desired, "ON" if actual_artmode is True else ("OFF" if actual_artmode is False else "UNKNOWN"))
        if desired == MODE_ART:
            self._phase = PHASE_RETURNING_TO_ART
            _LOGGER.info("Enforcing ART mode: calling async_force_art_on()")
            success, action = await self.frame_client.async_force_art_on()
            _LOGGER.info("Art Mode ON command result: success=%s, action=%s", success, action)
            self._last_action = ACTION_SET_ART_ON if success else action
            self._last_action_result = ACTION_RESULT_SUCCESS if success else ACTION_RESULT_FAIL
            if not success:
                self._last_error = f"Failed to set Art Mode on: {action}"
                self._command_fail_count += 1
                _LOGGER.warning("Failed to set Art Mode ON: %s", action)
            else:
                _LOGGER.info("Art Mode ON command succeeded, verifying state...")

        elif desired == MODE_OFF:
            self._phase = PHASE_IDLE
            _LOGGER.info("Enforcing OFF mode: calling async_set_artmode(False)")
            success = await self.frame_client.async_set_artmode(False)
            _LOGGER.info("Art Mode OFF command result: success=%s", success)
            if success:
                # Try to turn TV off (best effort)
                _LOGGER.debug("Art Mode OFF succeeded, attempting power toggle to turn TV off")
                await self.frame_client.async_power_toggle()
            self._last_action = ACTION_TV_OFF
            self._last_action_result = ACTION_RESULT_SUCCESS if success else ACTION_RESULT_FAIL
            if not success:
                _LOGGER.warning("Failed to set Art Mode OFF")

        elif desired == MODE_ATV:
            self._phase = PHASE_SWITCHING_TO_ATV
            _LOGGER.info("Enforcing ATV mode: calling async_force_art_off()")
            success, action = await self.frame_client.async_force_art_off()
            _LOGGER.info("Art Mode OFF command result (for ATV): success=%s, action=%s", success, action)
            if success:
                _LOGGER.debug("Art Mode OFF succeeded, switching to ATV input")
                await self._switch_to_atv_input()
            self._last_action = ACTION_SET_ART_OFF if success else action
            self._last_action_result = ACTION_RESULT_SUCCESS if success else ACTION_RESULT_FAIL
            if not success:
                _LOGGER.warning("Failed to set Art Mode OFF (for ATV mode): %s", action)

        self._last_action_ts = dt_util.utcnow()
        self._record_command()

        if self._last_action_result == ACTION_RESULT_FAIL:
            _LOGGER.warning("[enforce] Command failed: action=%s, error=%s", self._last_action, self._last_error)
            await self._handle_command_failure()
        else:
            _LOGGER.info("[enforce] Command succeeded: action=%s, desired=%s", self._last_action, desired)
            self._connection_backoff_delay = BACKOFF_INITIAL
            self._connection_backoff_until_monotonic = None
            self._connection_backoff_until = None
            self._last_backoff_log_time = None
            # Set cooldown after successful enforcement (not for manual services)
            # Use both monotonic (for duration) and wall-clock (for display)
            if self._last_trigger != EVENT_TYPE_MANUAL:
                cooldown_seconds = self.config.get("cooldown_seconds", DEFAULT_COOLDOWN_SECONDS)
                loop = asyncio.get_running_loop()
                self._cooldown_until_monotonic = loop.time() + cooldown_seconds
                self._cooldown_until = dt_util.utcnow() + timedelta(seconds=cooldown_seconds)
                _LOGGER.debug("[enforce] Cooldown set for %d seconds", cooldown_seconds)

        await self._fire_event()

    async def _switch_to_atv_input(self) -> None:
        """Switch to Apple TV input (best effort)."""
        input_mode = self.config.get("input_mode", INPUT_MODE_HDMI1)
        if input_mode == INPUT_MODE_NONE:
            _LOGGER.debug("Input switching disabled (input_mode=none)")
            return

        if input_mode in ("hdmi1", "hdmi2", "hdmi3"):
            _LOGGER.info("Switching TV input to %s for ATV", input_mode.upper())
            success = await self.frame_client.async_set_source(input_mode)
            if success:
                _LOGGER.info("TV input switched to %s successfully", input_mode.upper())
            else:
                _LOGGER.warning("Failed to switch TV input to %s", input_mode.upper())

    async def _handle_command_failure(self) -> None:
        """Handle command failure with backoff and breaker."""
        self._command_fail_count += 1
        self._connection_failures += 1

        # Exponential backoff (use both monotonic and wall-clock)
        loop = asyncio.get_running_loop()
        backoff_duration = self._connection_backoff_delay
        self._connection_backoff_until_monotonic = loop.time() + backoff_duration
        self._connection_backoff_until = dt_util.utcnow() + timedelta(seconds=backoff_duration)
        self._connection_backoff_delay = min(
            self._connection_backoff_delay * BACKOFF_MULTIPLIER, BACKOFF_MAX
        )

        # Update health
        if self._pair_health == HEALTH_OK:
            self._pair_health = HEALTH_DEGRADED
            self._phase = PHASE_DEGRADED
            self._log_event(EVENT_TYPE_DEGRADED, ACTION_RESULT_FAIL, "Connection issues detected")

    def _record_command(self) -> None:
        """Record command for rate limiting."""
        now = dt_util.utcnow()
        self._command_times.append(now)

        # Clean old commands (older than 5 minutes)
        # Normalize items before comparing (handle legacy naive datetimes)
        cutoff = now - timedelta(minutes=5)
        while self._command_times:
            first = self._command_times[0]
            if first is None:
                self._command_times.popleft()
                continue
            # Normalize: if naive, assume UTC; if aware, convert to UTC
            first_normalized = dt_util.as_utc(first) if first.tzinfo is None else dt_util.as_utc(first)
            if first_normalized < cutoff:
                self._command_times.popleft()
            else:
                break

        # Check breaker
        max_commands = self.config.get("max_commands_per_5min", DEFAULT_MAX_COMMANDS_PER_5MIN)
        if len(self._command_times) > max_commands:
            cooldown_minutes = self.config.get("breaker_cooldown_minutes", DEFAULT_BREAKER_COOLDOWN_MINUTES)
            self._breaker_open = True
            loop = asyncio.get_running_loop()
            breaker_duration_seconds = cooldown_minutes * 60
            self._breaker_open_until_monotonic = loop.time() + breaker_duration_seconds
            self._breaker_open_until = dt_util.utcnow() + timedelta(minutes=cooldown_minutes)
            self._pair_health = HEALTH_BREAKER_OPEN
            self._phase = PHASE_BREAKER_OPEN
            self._log_event(
                EVENT_TYPE_BREAKER_OPENED,
                ACTION_RESULT_FAIL,
                f"Circuit breaker opened: too many commands",
            )

    async def _async_resync_timer(self, now: datetime) -> None:
        """Periodic resync timer."""
        # Acquire lock for state checks and resync scheduling
        async with self._lock:
            # Ensure now is timezone-aware (normalize if naive)
            now_utc = dt_util.as_utc(now) if now.tzinfo is None else dt_util.as_utc(now)
            
            # Prune old command timestamps (even if no commands sent recently)
            # This prevents memory leak if no commands for long periods
            if self._command_times:
                cutoff = now_utc - timedelta(minutes=5)
                # Normalize items before comparing (handle legacy naive datetimes)
                while self._command_times:
                    first = self._command_times[0]
                    if first is None:
                        self._command_times.popleft()
                        continue
                    # Normalize: if naive, assume UTC; if aware, convert to UTC
                    first_normalized = dt_util.as_utc(first) if first.tzinfo is None else dt_util.as_utc(first)
                    if first_normalized < cutoff:
                        self._command_times.popleft()
                    else:
                        break
            
            # Prune old drift corrections (even if resync disabled or interval long)
            if self._drift_corrections_this_hour:
                cutoff = now_utc - timedelta(hours=1)
                # Normalize items before comparing (handle legacy naive datetimes)
                while self._drift_corrections_this_hour:
                    first = self._drift_corrections_this_hour[0]
                    if first is None:
                        # Skip None entries
                        self._drift_corrections_this_hour.popleft()
                        continue
                    # Normalize: if naive, assume UTC; if aware, convert to UTC
                    first_normalized = dt_util.as_utc(first) if first.tzinfo is None else dt_util.as_utc(first)
                    if first_normalized < cutoff:
                        self._drift_corrections_this_hour.popleft()
                    else:
                        break

            # Check if breaker should auto-close (use monotonic time)
            if self._breaker_open and self._breaker_open_until_monotonic is not None:
                loop = asyncio.get_running_loop()
                if loop.time() >= self._breaker_open_until_monotonic:
                    self._breaker_open = False
                    self._breaker_open_until = None
                    self._breaker_open_until_monotonic = None
                    self._pair_health = HEALTH_OK
                    self._log_event(
                        EVENT_TYPE_BREAKER_CLOSED,
                        ACTION_RESULT_SUCCESS,
                        "Circuit breaker auto-closed",
                    )

            if self._resync_task and not self._resync_task.done():
                return  # Previous resync still running

            # Create task to run resync (we're already holding lock, so create task and release)
            # The task will acquire lock when it runs
            async def _resync_with_lock():
                async with self._lock:
                    await self._async_resync()
            
            self._resync_task = asyncio.create_task(_resync_with_lock())
            # Release lock here so timer callback returns quickly
            # Task will acquire its own lock when it runs

    async def _check_tv_reachable(self) -> bool:
        """
        Check if TV is reachable using multiple methods.
        
        TV is considered reachable if:
        - TV state entity is not "unavailable" (even if "off" is OK), OR
        - TCP connection to TV ports succeeds, OR
        - Websocket connection succeeds
        
        Important: "off" state is NOT treated as unreachable.
        """
        _LOGGER.debug("Checking TV reachability...")
        # Method 1: Check TV state source entity (most reliable if configured)
        if self.tv_state_source_entity_id:
            state = self.hass.states.get(self.tv_state_source_entity_id)
            if state:
                # If entity exists and is not "unavailable", TV is reachable
                # Even if state is "off", the TV is reachable (just powered off)
                if state.state != "unavailable":
                    _LOGGER.debug("TV reachable via entity %s (state=%s)", self.tv_state_source_entity_id, state.state)
                    return True
                else:
                    _LOGGER.debug("TV entity %s reports unavailable", self.tv_state_source_entity_id)
        
        # Method 2: Try TCP connection to TV ports (fast check)
        try:
            # Try port 8002 first (default), then 8001
            for port in [self.frame_client.port, 8001]:
                sock = None
                try:
                    _LOGGER.debug("Trying TCP connection to %s:%d", self.frame_client.host, port)
                    # Use asyncio.wait_for with short timeout to avoid blocking
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1.0)  # 1 second timeout
                    result = await asyncio.wait_for(
                        asyncio.to_thread(sock.connect, (self.frame_client.host, port)),
                        timeout=1.0
                    )
                    sock.close()
                    _LOGGER.debug("TV reachable via TCP connection to %s:%d", self.frame_client.host, port)
                    return True
                except (socket.error, asyncio.TimeoutError, OSError) as ex:
                    _LOGGER.debug("TCP connection to %s:%d failed: %s", self.frame_client.host, port, ex)
                    if sock:
                        try:
                            sock.close()
                        except Exception:
                            pass  # Ignore errors closing socket
                    continue
        except Exception as ex:
            _LOGGER.debug("TCP reachability check failed: %s", ex)
        
        # Method 3: Fallback to websocket connection (slower but definitive)
        try:
            _LOGGER.debug("Trying websocket connection to verify TV reachability...")
            artmode = await asyncio.wait_for(
                self.frame_client.async_get_artmode(),
                timeout=3.0  # 3 second timeout
            )
            reachable = artmode is not None
            _LOGGER.debug("TV reachable via websocket: %s (artmode=%s)", reachable, artmode)
            return reachable
        except (asyncio.TimeoutError, Exception) as ex:
            _LOGGER.debug("Websocket reachability check failed: %s", ex)
            return False
    
    async def _get_tv_state(self) -> str | None:
        """Get TV state from configured state source entity."""
        if self.tv_state_source_entity_id:
            state = self.hass.states.get(self.tv_state_source_entity_id)
            if state:
                _LOGGER.debug("TV state from entity %s: %s", self.tv_state_source_entity_id, state.state)
                return state.state
            else:
                _LOGGER.debug("TV state entity %s not found or unavailable", self.tv_state_source_entity_id)
        else:
            _LOGGER.debug("No TV state source entity configured")
        return None
    
    async def _attempt_remote_wake(self) -> bool:
        """
        Attempt to wake TV using remote KEY_POWER command.
        Returns True if wake was attempted successfully, False if not configured or failed.
        """
        if not self.enable_remote_wake:
            return False
        
        if not self.wake_remote_entity_id:
            _LOGGER.debug("Remote wake enabled but no wake_remote_entity_id configured")
            return False
        
        wake_attempts = 0
        max_attempts = self.remote_wake_retries
        
        while wake_attempts < max_attempts:
            wake_attempts += 1
            
            try:
                _LOGGER.info("[wake_remote_attempt] Attempting to wake TV via remote %s (attempt %d/%d)", 
                            self.wake_remote_entity_id, wake_attempts, max_attempts)
                self._log_event(EVENT_TYPE_MANUAL, ACTION_REMOTE_WAKE, 
                              f"[wake_remote_attempt] Remote wake attempt {wake_attempts}/{max_attempts}")
                
                await asyncio.wait_for(
                    self.hass.services.async_call(
                        domain="remote",
                        service="send_command",
                        service_data={
                            "entity_id": self.wake_remote_entity_id,
                            "command": "KEY_POWER",
                            "num_repeats": 1,
                            "delay_secs": 0.4,
                        },
                        blocking=True,
                    ),
                    timeout=5.0  # 5 second timeout for service call
                )
                
                self._last_action = ACTION_REMOTE_WAKE
                _LOGGER.info("Sent KEY_POWER command to remote %s", self.wake_remote_entity_id)
                
                # Wait before checking if wake succeeded
                if wake_attempts < max_attempts:
                    await asyncio.sleep(self.remote_wake_delay)
                else:
                    # Last attempt, wait a bit for TV to respond
                    await asyncio.sleep(self.remote_wake_delay)
                
                return True  # Wake command sent successfully
                
            except asyncio.TimeoutError:
                _LOGGER.warning("[wake_remote_fail] Remote wake service call timed out (attempt %d/%d)", 
                              wake_attempts, max_attempts)
                self._log_event(EVENT_TYPE_MANUAL, ACTION_RESULT_FAIL,
                              f"[wake_remote_fail] Remote wake timeout (attempt {wake_attempts}/{max_attempts})")
                if wake_attempts < max_attempts:
                    await asyncio.sleep(self.remote_wake_delay)
                continue
            except Exception as ex:
                _LOGGER.warning("[wake_remote_fail] Failed to send wake command via remote %s: %s (attempt %d/%d)", 
                              self.wake_remote_entity_id, ex, wake_attempts, max_attempts)
                self._log_event(EVENT_TYPE_MANUAL, ACTION_RESULT_FAIL,
                              f"[wake_remote_fail] Remote wake error: {ex}")
                if wake_attempts < max_attempts:
                    await asyncio.sleep(self.remote_wake_delay)
                continue
        
        return False  # All remote wake attempts failed
    
    async def _attempt_wol_fallback(self) -> bool:
        """
        Attempt to wake TV using WOL as a last-resort fallback.
        Returns True if WOL was attempted, False if not configured or failed.
        """
        if not self.enable_wol_fallback:
            return False
        
        if not self.frame_mac:
            _LOGGER.debug("WOL fallback enabled but no MAC address configured")
            return False
        
        wol_attempts = 0
        max_attempts = self.wol_retries
        
        while wol_attempts < max_attempts:
            wol_attempts += 1
            
            try:
                _LOGGER.info("[wol_fallback_attempt] Attempting to wake TV via WOL (attempt %d/%d)", 
                            wol_attempts, max_attempts)
                self._log_event(EVENT_TYPE_MANUAL, ACTION_WOL,
                              f"[wol_fallback_attempt] WOL fallback attempt {wol_attempts}/{max_attempts}")
                
                # Use broadcast address if configured
                success = await self.frame_client.async_wake(self.frame_mac, self.wol_broadcast)
                
                if success:
                    self._last_action = ACTION_WOL
                    _LOGGER.info("Sent WOL packet to %s (broadcast: %s)", self.frame_mac, self.wol_broadcast)
                    await asyncio.sleep(self.wol_delay)
                    return True  # WOL packet sent successfully
                else:
                    _LOGGER.warning("[wol_fallback_fail] Failed to send WOL packet to %s (attempt %d/%d)", 
                                  self.frame_mac, wol_attempts, max_attempts)
                    self._log_event(EVENT_TYPE_MANUAL, ACTION_RESULT_FAIL,
                                  f"[wol_fallback_fail] WOL send failed (attempt {wol_attempts}/{max_attempts})")
                    if wol_attempts < max_attempts:
                        await asyncio.sleep(self.wol_delay)
                    continue
                    
            except Exception as ex:
                _LOGGER.warning("[wol_fallback_fail] WOL error: %s (attempt %d/%d)", 
                              ex, wol_attempts, max_attempts)
                self._log_event(EVENT_TYPE_MANUAL, ACTION_RESULT_FAIL,
                              f"[wol_fallback_fail] WOL error: {ex}")
                if wol_attempts < max_attempts:
                    await asyncio.sleep(self.wol_delay)
                continue
        
        return False  # All WOL attempts failed

    async def _async_resync(self) -> None:
        """Perform resync and drift correction."""
        # Note: This method is called from within a lock (either from timer via service or from _compute_and_enforce)
        # Check limits
        now = dt_util.utcnow()
        max_per_hour = self.config.get(
            "max_drift_corrections_per_hour", DEFAULT_MAX_DRIFT_CORRECTIONS_PER_HOUR
        )
        cooldown_minutes = self.config.get(
            "drift_correction_cooldown_minutes", DEFAULT_DRIFT_CORRECTION_COOLDOWN_MINUTES
        )

        # Clean old corrections (normalize all items for safe comparison)
        cutoff = now - timedelta(hours=1)
        # Normalize items before comparing (handle legacy naive datetimes)
        while self._drift_corrections_this_hour:
            first = self._drift_corrections_this_hour[0]
            if first is None:
                # Skip None entries
                self._drift_corrections_this_hour.popleft()
                continue
            # Normalize: if naive, assume UTC; if aware, convert to UTC
            first_normalized = dt_util.as_utc(first) if first.tzinfo is None else dt_util.as_utc(first)
            if first_normalized < cutoff:
                self._drift_corrections_this_hour.popleft()
            else:
                break

        # Check cooldown
        last_drift_correction = normalize_datetime(self._last_drift_correction)
        if last_drift_correction:
            try:
                delta = now - last_drift_correction
                if isinstance(delta, timedelta) and delta.total_seconds() < cooldown_minutes * 60:
                    return
            except (AttributeError, TypeError) as e:
                _LOGGER.warning("Error checking drift correction cooldown: %s", e)

        # Check limit
        if len(self._drift_corrections_this_hour) >= max_per_hour:
            return

        # Check override (re-check since we're in lock)
        override_until = normalize_datetime(self._manual_override_until)
        if override_until and now < override_until:
            return

        # Read actual state
        _LOGGER.debug("[resync] Reading actual Art Mode state...")
        actual = await self.frame_client.async_get_artmode()
        self._actual_artmode = actual
        _LOGGER.info("[resync] Actual Art Mode state: %s", 
                    "ON" if actual is True else ("OFF" if actual is False else "UNKNOWN"))

        # Recompute desired (update helper methods, don't trigger enforcement recursively)
        await self._update_active_hours()
        await self._update_presence(trigger=None)  # Don't trigger recursive enforcement
        desired = compute_desired_mode(
            atv_active=self._atv_active,
            in_active_hours=self._in_active_hours,
            night_behavior=self.config.get("night_behavior", "force_off"),
            presence_mode=self.config.get("presence_mode", "disabled"),
            home_ok=self._home_ok,
            away_policy=self.config.get("away_policy", "disabled"),
            unknown_behavior=self.config.get("unknown_behavior", "ignore"),
        )
        _LOGGER.info("[resync] Desired mode: %s (atv_active=%s, in_active_hours=%s)", 
                    desired, self._atv_active, self._in_active_hours)

        # Check drift
        drift = False
        if desired == MODE_ART and actual is not True:
            drift = True
            _LOGGER.warning("[resync] DRIFT DETECTED: desired=ART, actual=%s", 
                          "ON" if actual is True else ("OFF" if actual is False else "UNKNOWN"))
        elif desired == MODE_ATV and actual is True:
            drift = True
            _LOGGER.warning("[resync] DRIFT DETECTED: desired=ATV, actual=ON (should be OFF)")
        elif desired == MODE_OFF and actual is not False:
            drift = True
            _LOGGER.warning("[resync] DRIFT DETECTED: desired=OFF, actual=%s", 
                          "ON" if actual is True else ("OFF" if actual is False else "UNKNOWN"))
        else:
            _LOGGER.debug("[resync] No drift: desired=%s matches actual=%s", desired, actual)

        if drift:
            # Track consecutive drifts (likely manual user action)
            last_drift_at = normalize_datetime(self._last_drift_at)
            if last_drift_at:
                try:
                    delta = now - last_drift_at
                    if isinstance(delta, timedelta) and delta.total_seconds() < 300:  # 5 min window
                        self._consecutive_drifts += 1
                    else:
                        self._consecutive_drifts = 1
                except (AttributeError, TypeError) as e:
                    _LOGGER.warning("Error tracking consecutive drifts: %s", e)
                    self._consecutive_drifts = 1
            else:
                self._consecutive_drifts = 1
            self._last_drift_at = now

            # Activate manual override if 3+ consecutive drifts in 5 min window
            override_minutes = self.config.get("override_minutes", DEFAULT_OVERRIDE_MINUTES)
            if self._consecutive_drifts >= 3 and not self._manual_override_until:
                override_until = now + timedelta(minutes=override_minutes)
                self._manual_override_until = override_until
                loop = asyncio.get_running_loop()
                override_duration_seconds = override_minutes * 60
                self._manual_override_until_monotonic = loop.time() + override_duration_seconds
                self._log_event(
                    EVENT_TYPE_OVERRIDE_ACTIVATED,
                    ACTION_RESULT_SUCCESS,
                    f"Manual override activated: {self._consecutive_drifts} consecutive drifts detected",
                )

            self._last_drift_correction = now
            self._drift_corrections_this_hour.append(now)
            wake_info_parts = []
            if self.enable_remote_wake:
                wake_info_parts.append("remote_wake=enabled")
            if self.enable_wol_fallback:
                wake_info_parts.append("wol_fallback=enabled")
            wake_info = f", wake: {', '.join(wake_info_parts)}" if wake_info_parts else ""
            self._log_event(
                EVENT_TYPE_DRIFT_DETECTED,
                ACTION_RESULT_SUCCESS,
                f"Drift detected: desired={desired}, actual={'on' if actual else 'off'}{wake_info}",
            )
            # Only enforce if not in override (use 'now' variable for consistency)
            override_until_check = normalize_datetime(self._manual_override_until)
            if not override_until_check or now >= override_until_check:
                _LOGGER.info("[resync] Enforcing desired mode %s due to drift", desired)
                await self._enforce_desired_mode(desired)
            else:
                _LOGGER.info("[resync] Drift detected but override active, skipping enforcement")
        else:
            _LOGGER.debug("[resync] No drift detected, state matches desired")
            self._last_action = ACTION_RESYNC
            self._last_action_result = ACTION_RESULT_SUCCESS
            await self._fire_event()

    async def _fire_event(self) -> None:
        """Fire Home Assistant event."""
        event_data = {
            "entry_id": self.entry_id,
            "pair_name": self.pair_name,
            "event_type": self._last_trigger,
            "result": self._last_action_result,
            "message": self._last_error or "",
            "timestamp": dt_util.utcnow().isoformat(),
            "desired_mode": self._desired_mode or "unknown",
            "atv_active": self._atv_active,
            "home_ok": self._home_ok,
            "breaker_open": self._breaker_open,
        }

        self.hass.bus.async_fire("frame_artmode_sync_event", event_data)

    def _log_event(
        self, event_type: str, result: str, message: str, action: str | None = None
    ) -> None:
        """Log event to recent events."""
        event = {
            "timestamp": dt_util.utcnow().isoformat(),
            "type": event_type,
            "result": result,
            "message": message,
            "action": action or self._last_action,
        }
        self._recent_events.append(event)

    # Service methods
    async def async_force_art_on(self) -> None:
        """Force Art Mode on (service)."""
        # Rate limit service calls (prevent spam)
        loop = asyncio.get_running_loop()
        now_monotonic = loop.time()
        if self._last_service_call_time is not None:
            time_since_last = now_monotonic - self._last_service_call_time
            if time_since_last < 2.0:  # 2 second minimum between service calls
                _LOGGER.warning("Service call rate limited (last call %.1fs ago)", time_since_last)
                return
        self._last_service_call_time = now_monotonic
        
        async with self._lock:
            self._last_trigger = EVENT_TYPE_MANUAL
            # Cancel return-to-art timer since we're forcing state
            if self._return_to_art_task:
                self._return_to_art_task.cancel()
                self._return_to_art_task = None
            await self._enforce_desired_mode(MODE_ART)

    async def async_force_art_off(self) -> None:
        """Force Art Mode off (service)."""
        # Rate limit service calls
        loop = asyncio.get_running_loop()
        now_monotonic = loop.time()
        if self._last_service_call_time is not None:
            time_since_last = now_monotonic - self._last_service_call_time
            if time_since_last < 2.0:
                _LOGGER.warning("Service call rate limited (last call %.1fs ago)", time_since_last)
                return
        self._last_service_call_time = now_monotonic
        
        async with self._lock:
            self._last_trigger = EVENT_TYPE_MANUAL
            if self._return_to_art_task:
                self._return_to_art_task.cancel()
                self._return_to_art_task = None
            await self._enforce_desired_mode(MODE_ATV)

    async def async_force_tv_off(self) -> None:
        """Force TV off (service)."""
        # Rate limit service calls
        loop = asyncio.get_running_loop()
        now_monotonic = loop.time()
        if self._last_service_call_time is not None:
            time_since_last = now_monotonic - self._last_service_call_time
            if time_since_last < 2.0:
                _LOGGER.warning("Service call rate limited (last call %.1fs ago)", time_since_last)
                return
        self._last_service_call_time = now_monotonic
        
        async with self._lock:
            self._last_trigger = EVENT_TYPE_MANUAL
            if self._return_to_art_task:
                self._return_to_art_task.cancel()
                self._return_to_art_task = None
            await self._enforce_desired_mode(MODE_OFF)

    async def async_resync(self) -> None:
        """Manual resync (service)."""
        async with self._lock:
            self._last_trigger = EVENT_TYPE_RESYNC
            await self._async_resync()

    async def async_clear_override(self) -> None:
        """Clear manual override (service)."""
        async with self._lock:
            self._manual_override_until = None
            self._manual_override_until_monotonic = None
            self._log_event(EVENT_TYPE_OVERRIDE_CLEARED, ACTION_RESULT_SUCCESS, "Override cleared manually")
            # Trigger recompute through main flow (use locked version since we hold lock)
            await self._compute_and_enforce_locked(trigger=EVENT_TYPE_MANUAL, force=True)

    async def async_clear_breaker(self) -> None:
        """Clear circuit breaker (service)."""
        async with self._lock:
            self._breaker_open = False
            self._breaker_open_until = None
            self._pair_health = HEALTH_OK
            self._log_event(EVENT_TYPE_BREAKER_CLOSED, ACTION_RESULT_SUCCESS, "Breaker cleared manually")
            await self._fire_event()

    # Property getters for entities
    @property
    def status_attributes(self) -> dict[str, Any]:
        """Get status sensor attributes."""
        now_utc = dt_util.utcnow()
        cooldown_remaining = 0
        cooldown_until = normalize_datetime(self._cooldown_until)
        if cooldown_until and cooldown_until > now_utc:
            try:
                delta = cooldown_until - now_utc
                cooldown_remaining = int(delta.total_seconds()) if isinstance(delta, timedelta) else 0
            except (AttributeError, TypeError) as e:
                _LOGGER.warning("Error calculating cooldown remaining: %s", e)
                cooldown_remaining = 0

        override_remaining = 0
        override_until = normalize_datetime(self._manual_override_until)
        if override_until and override_until > now_utc:
            try:
                delta = override_until - now_utc
                override_remaining = int(delta.total_seconds()) if isinstance(delta, timedelta) else 0
            except (AttributeError, TypeError) as e:
                _LOGGER.warning("Error calculating override remaining: %s", e)
                override_remaining = 0

        breaker_remaining = 0
        breaker_until = normalize_datetime(self._breaker_open_until)
        if breaker_until and breaker_until > now_utc:
            try:
                delta = breaker_until - now_utc
                breaker_remaining = int(delta.total_seconds()) if isinstance(delta, timedelta) else 0
            except (AttributeError, TypeError) as e:
                _LOGGER.warning("Error calculating breaker remaining: %s", e)
                breaker_remaining = 0

        return {
            "phase": self._phase,
            "desired_mode": self._desired_mode or "unknown",
            "actual_artmode_state": "on" if self._actual_artmode is True else ("off" if self._actual_artmode is False else "unknown"),
            "atv_active": self._atv_active,
            "atv_playback_state": self._atv_playback_state,
            "in_active_hours": self._in_active_hours,
            "presence_mode": self.config.get("presence_mode", "disabled"),
            "home_ok": self._home_ok,
            "manual_override_active": override_until is not None and now_utc < override_until if override_until else False,
            "manual_override_remaining_s": override_remaining,
            "breaker_open": self._breaker_open,
            "breaker_remaining_s": breaker_remaining,
            "cooldown_remaining_s": cooldown_remaining,
            "last_trigger": self._last_trigger,
            "last_action": self._last_action,
            "last_action_result": self._last_action_result,
            "last_action_ts": ensure_isoformat(self._last_action_ts),
            "last_error": self._last_error,
            "command_count_5min": len(self._command_times),
            "connect_fail_count": self._connect_fail_count,
            "command_fail_count": self._command_fail_count,
            "verify_fail_count": self._verify_fail_count,
        }

    @property
    def status_state(self) -> str:
        """Get status sensor state (human-readable)."""
        if self._phase == PHASE_BREAKER_OPEN:
            return f"Circuit breaker open ({self._desired_mode})"
        if self._phase == PHASE_DEGRADED:
            return f"Degraded: {self._last_error or 'Connection issues'}"
        if self._phase == PHASE_MANUAL_OVERRIDE:
            return f"Manual override active ({self._desired_mode})"
        if self._phase == PHASE_DRY_RUN:
            return f"DRY RUN: {self._desired_mode}"
        return f"{self._phase.replace('_', ' ').title()}: {self._desired_mode or 'unknown'}"

    @property
    def recent_events_text(self) -> str:
        """Get recent events as formatted text."""
        if not self._recent_events:
            return "No events yet"

        lines = []
        for event in self._recent_events:
            ts = event["timestamp"][:19].replace("T", " ")
            lines.append(
                f"{ts} [{event['type']}] {event['result']}: {event['message']}"
            )
        return "\n".join(reversed(lines))

