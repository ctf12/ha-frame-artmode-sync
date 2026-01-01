# Regression Guard Report - Part A

## PHASE 1 - DEADLOCK / LOCK REGRESSION CHECK

### Call Graph Analysis

**Methods that acquire `self._lock` (pair_controller):**
1. `_compute_and_enforce()` - acquires lock → calls `_compute_and_enforce_locked()` (expects lock) ✅
2. `_async_resync_timer()` - acquires lock → creates task that acquires lock (OK, async) ✅
3. `async_force_art_on()` - acquires lock → calls `_enforce_desired_mode()` (expects lock) ✅
4. `async_force_art_off()` - acquires lock → calls `_enforce_desired_mode()` (expects lock) ✅
5. `async_force_tv_off()` - acquires lock → calls `_enforce_desired_mode()` (expects lock) ✅
6. `async_resync()` - acquires lock → calls `_async_resync()` (expects lock) ✅
7. `async_clear_override()` - acquires lock → calls `_compute_and_enforce_locked()` (expects lock) ✅
8. `async_clear_breaker()` - acquires lock (no nested calls) ✅

**Methods that expect lock:**
- `_compute_and_enforce_locked()` - expects lock → calls `_enforce_desired_mode()` (expects lock) ✅
- `_enforce_desired_mode()` - expects lock, no nested lock acquisition ✅
- `_async_resync()` - expects lock, no nested lock acquisition ✅

**Verdict**: ✅ NO DEADLOCK RISKS - All nested calls use `_locked` versions that expect lock.

### Cancellation + Await Analysis

**Task cancellation locations:**
- `async_cleanup()` - cancels tasks, awaits them OUTSIDE lock context ✅
- Service methods - cancel `_return_to_art_task` WITHOUT awaiting (safe, task acquires own lock) ✅
- `_handle_atv_state_change()` - cancels without awaiting (safe, not holding lock) ✅
- `_schedule_return_to_art()` - cancels without awaiting (safe, called within lock but task acquires own lock) ✅

**Verdict**: ✅ NO DEADLOCK RISKS - No cancellation+await while holding lock.

## PHASE 2 - ENFORCEMENT ENTRYPOINT CONSISTENCY

**All call sites of `_enforce_desired_mode()`:**
1. `_compute_and_enforce_locked()` line 456 - ✅ called within lock
2. Return-to-art task line 494 - ✅ acquires lock before calling
3. `_async_resync()` line 841 - ✅ called within lock

**All call sites of `_compute_and_enforce()`:**
1. `async_setup()` line 227 - ✅ public entrypoint
2. `_async_startup_grace()` line 232 - ✅ public entrypoint
3. `_handle_atv_state_change()` line 287 - ✅ public entrypoint
4. `_on_presence_changed()` line 290 - ✅ public entrypoint (schedules task)

**All call sites of `_compute_and_enforce_locked()`:**
1. `_compute_and_enforce()` line 379 - ✅ within lock
2. `_update_presence()` multiple lines - ✅ within lock (from _compute_and_enforce_locked)
3. `async_clear_override()` line 949 - ✅ within lock

**Verdict**: ✅ ALL ENFORCEMENT PATHS PROPERLY GUARDED

## PHASE 3 - TASK / TIMER LIFECYCLE REGRESSION

**All `asyncio.create_task` call sites:**
1. `_startup_grace_task` line 205 - ✅ stored in field, cancelled in cleanup
2. `_return_to_art_task` line 498 - ✅ stored in field, cancelled in cleanup
3. `_resync_task` line 748 - ✅ stored in field, cancelled in cleanup
4. `_reconnect_task` (atv_client) - ✅ stored in field, cancelled in disconnect
5. Listener tasks (atv_client) - ✅ stored in set with done_callback, cancelled in disconnect

**HA subscriptions:**
1. `_presence_tracker` (async_track_state_change_event) - ✅ stored, unsubscribed in cleanup
2. `_resync_unsub` (async_track_time_interval) - ✅ stored, unsubscribed in cleanup
3. Entity update tasks (binary_sensor, sensor) - ✅ stored, unsubscribed via async_on_remove

**Verdict**: ✅ ALL TASKS AND SUBSCRIPTIONS PROPERLY CLEANED UP

## PHASE 4 - TIME & MEMORY SAFETY

**Duration-based logic using monotonic time:**
- `_cooldown_until_monotonic` - ✅ used in `_should_enforce()`
- `_breaker_open_until_monotonic` - ✅ used in resync timer
- `_connection_backoff_until_monotonic` - ✅ used in `_enforce_desired_mode()`
- `_manual_override_until_monotonic` - ✅ used in `_compute_and_enforce_locked()`
- Active hours - ✅ uses wall-clock (correct for user-facing time)

**Deque pruning:**
- `_command_times` - ✅ pruned in resync timer (line 714-717)
- `_drift_corrections_this_hour` - ✅ pruned in resync timer (line 720-723)
- `_recent_events` - ✅ capped with maxlen=20

**Verdict**: ✅ TIME SAFE, MEMORY BOUNDED

## PHASE 5 - PYATV RECONNECT & STOPPING SAFETY

**Reconnect loop:**
- Single instance (`_reconnect_task`) - ✅ checked before scheduling
- Exponential backoff (10s → 30s → 60s max) - ✅ implemented
- Cancelled on unload (`async_disconnect()`) - ✅ sets `_should_reconnect = False`, cancels task

**Push listener callbacks:**
- Check `if not self.client.atv:` before creating tasks - ✅ prevents tasks after disconnect
- Tasks added to `_listener_tasks` set - ✅ tracked and cancelled in disconnect

**Verdict**: ✅ RECONNECT SAFE, NO POST-DISCONNECT TASKS

## PHASE 6 - EDGE-CASE SCENARIOS

### A) ATV flaps quickly ✅
- Debounce in `_set_state()` prevents rapid state changes
- Lock protection ensures single enforcement path
- Cooldown prevents rapid command sequences

### B) ATV disconnects/reconnects ✅
- Grace period holds state (30s default)
- Reconnect loop with backoff attempts reconnection
- State updated on reconnect via push listener

### C) HA restart mid-ATV playback ✅
- Startup grace prevents immediate enforcement
- Initial state read from ATV after connection
- No enforcement until grace expires

### D) Presence unknown transitions ✅
- Triggers recompute when state changes
- Uses locked version to prevent deadlock
- Handles unknown_behavior correctly

### E) Active hours crossing midnight ✅
- Logic in `is_time_in_window()` handles crossover correctly
- Tested pattern: 22:00-06:00 works

### F) Samsung unreachable with WOL ✅
- WOL attempts bounded (MAX_WAKE_ATTEMPTS=2)
- Sets degraded state on failure
- Backoff prevents rapid retries

### G) Breaker opens then manual service ✅
- Manual services bypass breaker (by design)
- Clear breaker service available
- Status shows breaker state correctly

### H) Return-to-art scheduled then ATV active ✅
- Timer cancelled proactively when ATV activates
- Cancellation safe (no await while holding lock)
- Task handles CancelledError

### I) Drift correction during manual override ✅
- Override check in `_async_resync()` prevents enforcement
- Lock protection prevents race
- Override cleared when ATV becomes active

### J) Dry-run enabled ✅
- Early check in `_enforce_desired_mode()` prevents ALL Samsung commands
- No WOL, no artmode changes, no input switching
- Logs "DRY RUN: Would set X"

**Verdict**: ✅ ALL SCENARIOS HANDLED CORRECTLY

## REGRESSION FINDINGS

### BLOCKER - Fixed
1. **Indentation bug in manual override check** (line 426-440)
   - **Issue**: Incorrect indentation made logic unclear, potential incorrect override handling
   - **Fix**: Corrected indentation and clarified logic flow

### HIGH - None
All high-priority items verified clean.

### MEDIUM - None
All medium-priority items verified clean.

### LOW - None
No low-priority issues found.

## MINIMAL PATCHES APPLIED

**Patch 1: Fix manual override indentation**
- File: `pair_controller.py` lines 410-440
- Change: Corrected indentation and clarified override check logic
- Impact: Ensures manual override handling works correctly

## SCENARIO VERIFICATION A-J

All scenarios verified and working correctly. No regressions detected.

**Ready for Part B - Release Hardening**

