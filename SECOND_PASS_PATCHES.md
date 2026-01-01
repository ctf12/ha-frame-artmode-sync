# Second-Pass Runtime Bug Fixes - Patches

## PATCH 1: Fix Service Methods Lock Race (BLOCKER #1)

### File: `custom_components/frame_artmode_sync/pair_controller.py`

**Lines 721-735:** Service methods must acquire lock or call through protected path.

```python
# REPLACE service methods section:
    # Service methods
    async def async_force_art_on(self) -> None:
        """Force Art Mode on (service)."""
        async with self._lock:
            self._last_trigger = EVENT_TYPE_MANUAL
            # Cancel return-to-art timer since we're forcing state
            if self._return_to_art_task:
                self._return_to_art_task.cancel()
                self._return_to_art_task = None
            await self._enforce_desired_mode(MODE_ART)

    async def async_force_art_off(self) -> None:
        """Force Art Mode off (service)."""
        async with self._lock:
            self._last_trigger = EVENT_TYPE_MANUAL
            if self._return_to_art_task:
                self._return_to_art_task.cancel()
                self._return_to_art_task = None
            await self._enforce_desired_mode(MODE_ATV)

    async def async_force_tv_off(self) -> None:
        """Force TV off (service)."""
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
            self._log_event(EVENT_TYPE_OVERRIDE_CLEARED, ACTION_RESULT_SUCCESS, "Override cleared manually")
            # Trigger recompute through main flow
            await self._compute_and_enforce(trigger=EVENT_TYPE_MANUAL, force=True)

    async def async_clear_breaker(self) -> None:
        """Clear circuit breaker (service)."""
        async with self._lock:
            self._breaker_open = False
            self._breaker_open_until = None
            self._pair_health = HEALTH_OK
            self._log_event(EVENT_TYPE_BREAKER_CLOSED, ACTION_RESULT_SUCCESS, "Breaker cleared manually")
            await self._fire_event()
```

---

## PATCH 2: Fix Return-to-Art Task Lock (BLOCKER #2)

### File: `custom_components/frame_artmode_sync/pair_controller.py`

**Lines 405-418:** Return task must acquire lock or schedule through main flow.

```python
# REPLACE _schedule_return_to_art:
    async def _schedule_return_to_art(self) -> None:
        """Schedule delayed return to Art Mode."""
        if self._return_to_art_task:
            self._return_to_art_task.cancel()
            try:
                await self._return_to_art_task
            except asyncio.CancelledError:
                pass
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
```

**Lines 250-260:** Cancel return-to-art when ATV becomes active.

```python
# ADD after line 254 in _handle_atv_state_change:
        if old_active != active:
            # Cancel return-to-art timer if ATV became active
            if active and self._return_to_art_task:
                self._return_to_art_task.cancel()
                try:
                    await self._return_to_art_task
                except asyncio.CancelledError:
                    pass
                self._return_to_art_task = None

            trigger = EVENT_TYPE_ATV_ON if active else EVENT_TYPE_ATV_OFF
            self._last_trigger = trigger
            self._log_event(trigger, ACTION_RESULT_SUCCESS, f"ATV {'activated' if active else 'deactivated'}")
            await self._compute_and_enforce()
```

---

## PATCH 3: Fix WOL Attempts Tracking (BLOCKER #3)

### File: `custom_components/frame_artmode_sync/pair_controller.py`

**Lines 444-461:** Fix WOL retry logic with proper attempt tracking.

```python
# REPLACE WOL section:
        # Try WOL if needed and enabled
        wol_attempts = 0
        max_wake_attempts = MAX_WAKE_ATTEMPTS
        wol_enabled = self.config.get("wol_enabled", False) and self.frame_mac
        wake_retry_delay = self.config.get("wake_retry_delay_seconds", DEFAULT_WAKE_RETRY_DELAY_SECONDS)

        # Read actual state (may trigger connection)
        actual_artmode = await self.frame_client.async_get_artmode()
        
        # If connection failed and WOL enabled, try waking (retry loop)
        while actual_artmode is None and wol_enabled and wol_attempts < max_wake_attempts:
            _LOGGER.info("Connection failed, attempting WOL wake (attempt %d/%d)", wol_attempts + 1, max_wake_attempts)
            wol_attempts += 1
            if await self.frame_client.async_wake(self.frame_mac):
                self._last_action = ACTION_WOL
                await asyncio.sleep(wake_retry_delay)
                # Retry connection after wake
                actual_artmode = await self.frame_client.async_get_artmode()
            else:
                # WOL send failed, don't retry immediately
                break

        self._actual_artmode = actual_artmode
```

---

## PATCH 4: Fix Resync Lock Protection (BLOCKER #4)

### File: `custom_components/frame_artmode_sync/pair_controller.py`

**Lines 601-689:** Wrap resync in lock or make it safe for concurrent execution.

**Option A: Add lock to resync (recommended):**

```python
# REPLACE _async_resync:
    async def _async_resync(self) -> None:
        """Perform resync and drift correction."""
        # Acquire lock to prevent race with enforcement
        async with self._lock:
            # Check limits
            now = datetime.now()
            max_per_hour = self.config.get(
                "max_drift_corrections_per_hour", DEFAULT_MAX_DRIFT_CORRECTIONS_PER_HOUR
            )
            cooldown_minutes = self.config.get(
                "drift_correction_cooldown_minutes", DEFAULT_DRIFT_CORRECTION_COOLDOWN_MINUTES
            )

            # Clean old corrections
            cutoff = now - timedelta(hours=1)
            while self._drift_corrections_this_hour and self._drift_corrections_this_hour[0] < cutoff:
                self._drift_corrections_this_hour.popleft()

            # Check cooldown
            if (
                self._last_drift_correction
                and (now - self._last_drift_correction).total_seconds() < cooldown_minutes * 60
            ):
                return

            # Check limit
            if len(self._drift_corrections_this_hour) >= max_per_hour:
                return

            # Check override (re-check since we're in lock)
            if self._manual_override_until and now < self._manual_override_until:
                return

            # Read actual state
            actual = await self.frame_client.async_get_artmode()
            self._actual_artmode = actual

            # Recompute desired
            await self._update_active_hours()
            await self._update_presence()
            desired = compute_desired_mode(
                atv_active=self._atv_active,
                in_active_hours=self._in_active_hours,
                night_behavior=self.config.get("night_behavior", "force_off"),
                presence_mode=self.config.get("presence_mode", "disabled"),
                home_ok=self._home_ok,
                away_policy=self.config.get("away_policy", "disabled"),
                unknown_behavior=self.config.get("unknown_behavior", "ignore"),
            )

            # Check drift
            drift = False
            if desired == MODE_ART and actual is not True:
                drift = True
            elif desired == MODE_ATV and actual is True:
                drift = True
            elif desired == MODE_OFF and actual is not False:
                drift = True

            if drift:
                # Track consecutive drifts (likely manual user action)
                if self._last_drift_at and (now - self._last_drift_at).total_seconds() < 300:  # 5 min window
                    self._consecutive_drifts += 1
                else:
                    self._consecutive_drifts = 1
                self._last_drift_at = now

                # Activate manual override if 3+ consecutive drifts in 5 min window
                override_minutes = self.config.get("override_minutes", DEFAULT_OVERRIDE_MINUTES)
                if self._consecutive_drifts >= 3 and not self._manual_override_until:
                    self._manual_override_until = datetime.now() + timedelta(minutes=override_minutes)
                    self._log_event(
                        EVENT_TYPE_OVERRIDE_ACTIVATED,
                        ACTION_RESULT_SUCCESS,
                        f"Manual override activated: {self._consecutive_drifts} consecutive drifts detected",
                    )

                self._last_drift_correction = now
                self._drift_corrections_this_hour.append(now)
                self._log_event(
                    EVENT_TYPE_DRIFT_DETECTED,
                    ACTION_RESULT_SUCCESS,
                    f"Drift detected: desired={desired}, actual={'on' if actual else 'off'}",
                )
                # Only enforce if not in override (re-check after setting)
                if not self._manual_override_until or datetime.now() >= self._manual_override_until:
                    await self._enforce_desired_mode(desired)
            else:
                self._last_action = ACTION_RESYNC
                self._last_action_result = ACTION_RESULT_SUCCESS
                await self._fire_event()
```

**Note**: This adds lock to resync, but `_enforce_desired_mode` is called inside lock. Since `_enforce_desired_mode` doesn't acquire lock itself, this is safe. However, we must ensure `_enforce_desired_mode` is always called from within a lock when called from resync.

---

## PATCH 5: Handle Task Cancellation Properly (HIGH #5)

### File: `custom_components/frame_artmode_sync/pair_controller.py`

**Lines 229-240:** Await cancelled tasks with exception handling.

```python
# REPLACE async_cleanup:
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
```

---

## PATCH 6: Fix Presence Unknown State Trigger (HIGH #8)

### File: `custom_components/frame_artmode_sync/pair_controller.py`

**Lines 286-330:** Track previous home_ok and trigger on unknown transitions.

```python
# REPLACE _update_presence:
    async def _update_presence(self, trigger: str | None = None) -> None:
        """Update presence state."""
        if not self._presence_entity_id:
            self._home_ok = None
            return

        try:
            old_home_ok = self._home_ok
            state_obj = self.hass.states.get(self._presence_entity_id)
            if not state_obj:
                self._home_ok = None
                # Trigger if state changed from known to unknown
                if old_home_ok is not None and trigger:
                    await self._compute_and_enforce(trigger)
                return

            state = state_obj.state.lower()
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
                if old_home_ok != self._home_ok and trigger:
                    await self._compute_and_enforce(trigger)
            elif state in away_states:
                self._home_ok = False
                if old_home_ok != self._home_ok and trigger:
                    await self._compute_and_enforce(trigger)
            else:
                # Unknown state
                unknown_behavior = self.config.get("unknown_behavior", "ignore")
                if unknown_behavior == "treat_as_home":
                    self._home_ok = True
                    if old_home_ok != self._home_ok and trigger:
                        await self._compute_and_enforce(trigger)
                elif unknown_behavior == "treat_as_away":
                    self._home_ok = False
                    if old_home_ok != self._home_ok and trigger:
                        await self._compute_and_enforce(trigger)
                else:
                    # ignore - set to None
                    self._home_ok = None
                    # Trigger if state changed from known to unknown
                    if old_home_ok is not None and trigger:
                        await self._compute_and_enforce(trigger)

        except Exception as ex:
            _LOGGER.error("Error updating presence: %s", ex)
            old_home_ok = self._home_ok
            self._home_ok = None
            if old_home_ok is not None and trigger:
                await self._compute_and_enforce(trigger)
```

---

## PATCH 7: Fix Verify Loop Timeout (MEDIUM #12)

### File: `custom_components/frame_artmode_sync/frame_client.py`

**Lines 266-279:** Check timeout before sleep to prevent exceeding max_time.

```python
# REPLACE async_verify_artmode:
    async def async_verify_artmode(self, expected: bool, max_time: float = VERIFY_TIMEOUT_TOTAL) -> bool:
        """Verify Art Mode state with bounded retries."""
        start = asyncio.get_event_loop().time()
        attempts = 0
        max_attempts = 10
        sleep_duration = 0.8

        while attempts < max_attempts:
            # Check timeout BEFORE making the call
            elapsed = asyncio.get_event_loop().time() - start
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
```

---

## PATCH 8: Fix ATV Listener Task Race (HIGH #9)

### File: `custom_components/frame_artmode_sync/atv_client.py`

**Lines 232-250:** Make task creation and tracking atomic relative to cleanup.

```python
# REPLACE ATVPushListener methods:
    def playstatus_update(self, updater: PushUpdater, playstatus: Playing) -> None:
        """Handle playback status update."""
        # Check if client is still connected before creating task
        if not self.client.atv:
            return
        
        playback_state = self.client._playback_state_from_playing(playstatus)
        active = self.client._compute_active()
        
        # Create task and add to set atomically (within client lock if possible)
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
```

**Also update _set_state to check connection:**

```python
# ADD check at start of _set_state (line 186):
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

                self._current_state = active
                self._playback_state = playback_state
                self._last_update = datetime.now()

                if self.state_callback:
                    self.state_callback(active, playback_state)

                _LOGGER.info("ATV state: active=%s, playback=%s", active, playback_state)
            except asyncio.CancelledError:
                pass  # Expected when cancelled

        self._debounce_task = asyncio.create_task(_debounced_set())
```

---

## PATCH 9: Add Fallback Media Player Support (MEDIUM #11)

### File: `custom_components/frame_artmode_sync/pair_controller.py`

**Add method to get ATV active from fallback:**

```python
# ADD after _update_presence method (around line 330):
    def _get_atv_active_fallback(self) -> bool | None:
        """Get ATV active state from fallback media_player entity."""
        if not self.fallback_media_player:
            return None
        
        try:
            state_obj = self.hass.states.get(self.fallback_media_player)
            if not state_obj:
                return None
            
            state = state_obj.state.lower()
            # Consider playing/playing_or_paused based on config
            active_mode = self.config.get("atv_active_mode", ATV_ACTIVE_MODE_PLAYING_OR_PAUSED)
            
            if active_mode == ATV_ACTIVE_MODE_POWER_ON:
                return state not in ("off", "standby", "unavailable", "unknown")
            elif active_mode == ATV_ACTIVE_MODE_PLAYING_ONLY:
                return state == "playing"
            else:  # playing_or_paused
                return state in ("playing", "paused")
        except Exception as ex:
            _LOGGER.debug("Error reading fallback media_player: %s", ex)
            return None
```

**Update _handle_atv_state_change to use fallback when pyatv disconnected:**

```python
# MODIFY _handle_atv_state_change (line 250):
    async def _handle_atv_state_change(self, active: bool, playback_state: str) -> None:
        """Handle Apple TV state change (async)."""
        old_active = self._atv_active
        
        # If pyatv disconnected, try fallback
        if not self.atv_client.is_connected:
            fallback_active = self._get_atv_active_fallback()
            if fallback_active is not None:
                active = fallback_active
                _LOGGER.debug("Using fallback media_player for ATV state: %s", active)
        
        self._atv_active = active
        self._atv_playback_state = playback_state

        if old_active != active:
            # Cancel return-to-art timer if ATV became active
            if active and self._return_to_art_task:
                self._return_to_art_task.cancel()
                try:
                    await self._return_to_art_task
                except asyncio.CancelledError:
                    pass
                self._return_to_art_task = None

            trigger = EVENT_TYPE_ATV_ON if active else EVENT_TYPE_ATV_OFF
            self._last_trigger = trigger
            self._log_event(trigger, ACTION_RESULT_SUCCESS, f"ATV {'activated' if active else 'deactivated'}")
            await self._compute_and_enforce()
```

**Update resync to use fallback:**

```python
# ADD in _async_resync before computing desired (around line 636):
            # Update ATV active from fallback if pyatv disconnected
            if not self.atv_client.is_connected:
                fallback_active = self._get_atv_active_fallback()
                if fallback_active is not None:
                    self._atv_active = fallback_active
                    _LOGGER.debug("Resync: Using fallback media_player for ATV state: %s", fallback_active)
```

---

## PATCH 10: Fix Manual Override Timing Race (MEDIUM #14)

### File: `custom_components/frame_artmode_sync/pair_controller.py`

**Lines 668-685:** Use same datetime.now() for consistency.

```python
# REPLACE override activation section in _async_resync:
            # Activate manual override if 3+ consecutive drifts in 5 min window
            override_minutes = self.config.get("override_minutes", DEFAULT_OVERRIDE_MINUTES)
            if self._consecutive_drifts >= 3 and not self._manual_override_until:
                override_until = now + timedelta(minutes=override_minutes)
                self._manual_override_until = override_until
                self._log_event(
                    EVENT_TYPE_OVERRIDE_ACTIVATED,
                    ACTION_RESULT_SUCCESS,
                    f"Manual override activated: {self._consecutive_drifts} consecutive drifts detected",
                )

            self._last_drift_correction = now
            self._drift_corrections_this_hour.append(now)
            self._log_event(
                EVENT_TYPE_DRIFT_DETECTED,
                ACTION_RESULT_SUCCESS,
                f"Drift detected: desired={desired}, actual={'on' if actual else 'off'}",
            )
            # Only enforce if not in override (use 'now' variable, not new datetime.now())
            if not self._manual_override_until or now >= self._manual_override_until:
                await self._enforce_desired_mode(desired)
```

---

## PATCH 11: Fix Diagnostics Controller Access (LOW #22)

### File: `custom_components/frame_artmode_sync/diagnostics.py`

**Lines 27-34:** Add proper checks.

```python
# REPLACE beginning of async_get_config_entry_diagnostics:
async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    if entry.entry_id not in hass.data.get(DOMAIN, {}):
        return {}

    manager = hass.data[DOMAIN][entry.entry_id]
    if not manager:
        return {}
    
    controller = manager.controller
    if not controller:
        return {}
```

