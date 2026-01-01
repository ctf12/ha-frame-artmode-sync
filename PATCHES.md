# Code Patches for Critical Issues

## PATCH 1: Fix pyatv deprecated loop parameter (BLOCKER #1)

### File: `custom_components/frame_artmode_sync/atv_client.py`

**Lines 62-65, 74:** Remove `loop=` parameter from scan and connect calls.

```python
# OLD:
if self.identifier:
    results = await scan(loop=asyncio.get_event_loop(), identifier=self.identifier)
else:
    results = await scan(loop=asyncio.get_event_loop(), hosts=[self.host])

# NEW:
if self.identifier:
    results = await scan(identifier=self.identifier)
else:
    results = await scan(hosts=[self.host])

# OLD:
self.atv = await connect(config, loop=asyncio.get_event_loop())

# NEW:
self.atv = await connect(config)
```

### File: `custom_components/frame_artmode_sync/config_flow.py`

**Line 57:** Remove `loop=` parameter.

```python
# OLD:
results = await scan(loop=asyncio.get_event_loop())

# NEW:
results = await scan()
```

---

## PATCH 2: Fix return-to-art delay logic bug (BLOCKER #4)

### File: `custom_components/frame_artmode_sync/pair_controller.py`

**Lines 117-120:** Add previous desired mode tracking.

```python
# Add after line 120:
self._previous_desired_mode: str | None = None
```

**Lines 351-375:** Fix the return-to-art logic.

```python
# REPLACE lines 351-375:
            self._desired_mode = desired

            # Check if we should enforce
            if self._manual_override_until and datetime.now() < self._manual_override_until:
                if self._desired_mode == MODE_ATV:
                    # ATV became active, clear override
                    self._manual_override_until = None
                    self._log_event(
                        EVENT_TYPE_OVERRIDE_CLEARED,
                        ACTION_RESULT_SUCCESS,
                        "Override cleared: ATV activated",
                    )
                else:
                    # Still in override
                    self._phase = PHASE_MANUAL_OVERRIDE
                    await self._fire_event()
                    return

            # Handle return-to-art delay
            # Check if transitioning from ATV to ART (not ATV active)
            previous_was_atv = self._previous_desired_mode == MODE_ATV
            if desired == MODE_ART and not self._atv_active and previous_was_atv:
                # ATV just turned off, schedule delayed return
                await self._schedule_return_to_art()
                self._previous_desired_mode = desired
                return

            # Store current as previous for next iteration
            self._previous_desired_mode = desired

            # Enforce
            await self._enforce_desired_mode(desired)
```

---

## PATCH 3: Implement manual override activation (BLOCKER #2)

### File: `custom_components/frame_artmode_sync/pair_controller.py`

**Lines 143-144:** Add override tracking.

```python
# Add after line 144:
self._last_drift_at: datetime | None = None
self._consecutive_drifts = 0
```

**Lines 610-618:** Add manual override activation logic.

```python
# REPLACE lines 610-618:
        if drift:
            # Track consecutive drifts (likely manual user action)
            now = datetime.now()
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
            # Only enforce if not in override
            if not self._manual_override_until or datetime.now() >= self._manual_override_until:
                await self._enforce_desired_mode(desired)
```

---

## PATCH 4: Call services cleanup on unload (BLOCKER #5)

### File: `custom_components/frame_artmode_sync/__init__.py`

**Lines 45-53:** Add services cleanup.

```python
# REPLACE async_unload_entry:
async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if entry.entry_id in hass.data[DOMAIN]:
        manager = hass.data[DOMAIN][entry.entry_id]
        await manager.async_cleanup()
        hass.data[DOMAIN].pop(entry.entry_id)

    # Clean up services if last entry
    if not hass.data.get(DOMAIN):
        await async_unload_services(hass)
        hass.data.pop("_frame_artmode_sync_services_setup", None)

    return unload_ok
```

---

## PATCH 5: Implement WOL support (BLOCKER #3)

### File: `custom_components/frame_artmode_sync/manifest.json`

**Line 8-11:** Add wakeonlan dependency.

```json
  "requirements": [
    "pyatv>=0.14.0",
    "samsungtvws>=2.6.0",
    "wakeonlan>=3.0.0"
  ],
```

### File: `custom_components/frame_artmode_sync/frame_client.py`

**Top of file:** Add import.

```python
# Add after line 9:
from wakeonlan import send_magic_packet
```

**After __init__ method:** Add WOL method.

```python
# Add after line 42:
    async def async_wake(self, mac: str) -> bool:
        """Send Wake-on-LAN packet."""
        try:
            await asyncio.to_thread(send_magic_packet, mac)
            _LOGGER.info("Sent WOL packet to %s", mac)
            return True
        except Exception as ex:
            _LOGGER.warning("Failed to send WOL packet: %s", ex)
            return False
```

### File: `custom_components/frame_artmode_sync/pair_controller.py`

**Lines 405-428:** Add WOL before connection attempts in `_enforce_desired_mode`.

```python
# REPLACE lines 405-428:
    async def _enforce_desired_mode(self, desired: str) -> None:
        """Enforce desired mode with safety checks."""
        if not self._enabled:
            return

        if self.config.get("dry_run", False):
            self._phase = PHASE_DRY_RUN
            self._log_event(EVENT_TYPE_MANUAL, ACTION_RESULT_SUCCESS, f"DRY RUN: Would set {desired}")
            await self._fire_event()
            return

        # Check breaker
        if self._breaker_open:
            self._phase = PHASE_BREAKER_OPEN
            await self._fire_event()
            return

        # Check connection backoff
        if (
            self._connection_backoff_until
            and datetime.now() < self._connection_backoff_until
        ):
            return

        # Try WOL if needed and enabled
        wol_attempts = 0
        max_wake_attempts = self.config.get("max_wake_attempts", 2)
        wol_enabled = self.config.get("wol_enabled", False) and self.frame_mac
        wake_retry_delay = self.config.get("wake_retry_delay_seconds", DEFAULT_WAKE_RETRY_DELAY_SECONDS)

        # Read actual state (may trigger connection)
        actual_artmode = await self.frame_client.async_get_artmode()
        
        # If connection failed and WOL enabled, try waking
        if actual_artmode is None and wol_enabled and wol_attempts < max_wake_attempts:
            _LOGGER.info("Connection failed, attempting WOL wake")
            if await self.frame_client.async_wake(self.frame_mac):
                self._last_action = ACTION_WOL
                wol_attempts += 1
                await asyncio.sleep(wake_retry_delay)
                # Retry connection after wake
                actual_artmode = await self.frame_client.async_get_artmode()

        self._actual_artmode = actual_artmode
```

---

## PATCH 6: Track and cancel ATV listener tasks (HIGH #6)

### File: `custom_components/frame_artmode_sync/atv_client.py`

**Lines 48-56:** Add task tracking.

```python
# Add after line 56:
        self._listener_tasks: set[asyncio.Task] = set()
```

**Lines 226-240:** Track tasks in listener.

```python
# REPLACE ATVPushListener class:
class ATVPushListener(PushListener, PowerListener):
    """Listener for push updates."""

    def __init__(self, client: ATVClient) -> None:
        """Initialize listener."""
        self.client = client

    def playstatus_update(self, updater: PushUpdater, playstatus: Playing) -> None:
        """Handle playback status update."""
        playback_state = self.client._playback_state_from_playing(playstatus)
        active = self.client._compute_active()
        task = asyncio.create_task(self.client._set_state(active, playback_state))
        self.client._listener_tasks.add(task)
        task.add_done_callback(self.client._listener_tasks.discard)

    def playstatus_error(self, updater: PushUpdater, exception: Exception) -> None:
        """Handle playback status error."""
        _LOGGER.debug("Playback status error: %s", exception)

    def powerstate_update(self, old_state: PowerState, new_state: PowerState) -> None:
        """Handle power state update."""
        self.client._power_state = new_state
        active = self.client._compute_active()
        task = asyncio.create_task(self.client._set_state(active, self.client._playback_state))
        self.client._listener_tasks.add(task)
        task.add_done_callback(self.client._listener_tasks.discard)
```

**Lines 96-114:** Cancel tasks in disconnect.

```python
# ADD after line 100 in _handle_disconnect:
        # Cancel all listener tasks
        for task in list(self._listener_tasks):
            task.cancel()
        self._listener_tasks.clear()
```

---

## PATCH 7: Set cooldown after enforcement (HIGH #7)

### File: `custom_components/frame_artmode_sync/pair_controller.py`

**Lines 484-492:** Add cooldown after successful enforcement.

```python
# REPLACE lines 484-492:
        self._last_action_ts = datetime.now()
        self._record_command()

        if self._last_action_result == ACTION_RESULT_FAIL:
            await self._handle_command_failure()
        else:
            self._connection_backoff_delay = BACKOFF_INITIAL
            # Set cooldown after successful enforcement (not for manual services)
            if self._last_trigger != EVENT_TYPE_MANUAL:
                cooldown_seconds = self.config.get("cooldown_seconds", DEFAULT_COOLDOWN_SECONDS)
                self._cooldown_until = datetime.now() + timedelta(seconds=cooldown_seconds)

        await self._fire_event()
```

---

## PATCH 8: Auto-close circuit breaker (HIGH #8)

### File: `custom_components/frame_artmode_sync/pair_controller.py`

**Lines 546-551:** Add breaker auto-close check in resync timer.

```python
# ADD at start of _async_resync_timer (before line 548):
    async def _async_resync_timer(self, now: datetime) -> None:
        """Periodic resync timer."""
        # Check if breaker should auto-close
        if self._breaker_open and self._breaker_open_until:
            if datetime.now() >= self._breaker_open_until:
                self._breaker_open = False
                self._breaker_open_until = None
                self._pair_health = HEALTH_OK
                self._log_event(
                    EVENT_TYPE_BREAKER_CLOSED,
                    ACTION_RESULT_SUCCESS,
                    "Circuit breaker auto-closed",
                )

        if self._resync_task and not self._resync_task.done():
            return  # Previous resync still running

        self._resync_task = asyncio.create_task(self._async_resync())
```

---

## PATCH 9: Fix night_behavior do_nothing enforcement (MEDIUM #12)

### File: `custom_components/frame_artmode_sync/pair_controller.py`

**Lines 377-378:** Skip enforcement for do_nothing.

```python
# REPLACE lines 377-378:
            # Enforce (unless night_behavior is do_nothing and outside active hours)
            if not (not self._in_active_hours and self.config.get("night_behavior") == NIGHT_BEHAVIOR_DO_NOTHING):
                await self._enforce_desired_mode(desired)
            else:
                # Just update status, don't enforce
                self._phase = PHASE_IDLE
                await self._fire_event()
```

---

## PATCH 10: Add timeouts to service calls (HIGH #16)

### File: `custom_components/frame_artmode_sync/services.py`

**Top of file:** Add timeout constant.

```python
# Add after imports:
SERVICE_TIMEOUT = 30.0  # seconds
```

**Lines 66-82:** Wrap service calls in timeout.

```python
# REPLACE lines 66-82:
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
```

