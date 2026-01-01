# Second-Pass Runtime Bug Audit - Findings

## A) BUG LIST (Prioritized)

### BLOCKERS (Will Break Runtime)

1. **Service Methods Bypass Lock - Race Condition with Enforcement**
   - **Location**: `pair_controller.py:722-735`
   - **Issue**: Service methods (`async_force_art_on`, `async_force_art_off`, `async_force_tv_off`) call `_enforce_desired_mode()` directly without acquiring `_lock`. This can race with `_compute_and_enforce()` which holds the lock. Can cause:
     - Concurrent Samsung command sends
     - Command budget double-counting
     - State corruption
   - **Evidence**: Line 336 shows `_compute_and_enforce` uses `async with self._lock:`, but service methods at 722-735 don't.

2. **Return-to-Art Task Bypasses Lock**
   - **Location**: `pair_controller.py:412-416`
   - **Issue**: `_return_task` calls `_enforce_desired_mode(MODE_ART)` without lock. This can race with `_compute_and_enforce()` and concurrent operations.
   - **Evidence**: Task callback at line 416 calls enforcement without lock.

3. **WOL Attempts Never Increment - Infinite Retry Loop**
   - **Location**: `pair_controller.py:444-461`
   - **Issue**: `wol_attempts` is initialized to 0, checked, but only incremented after successful WOL send. The increment happens but condition `wol_attempts < max_wake_attempts` is checked BEFORE increment, so it can loop indefinitely if WOL succeeds but connection still fails.
   - **Evidence**: Line 454 checks `wol_attempts < max_wake_attempts` but `wol_attempts` is never incremented if WOL fails. Also, `wol_attempts` is local variable, not instance variable, so it resets on each call.

4. **Resync Bypasses Lock - Race with Enforcement**
   - **Location**: `pair_controller.py:601-689`
   - **Issue**: `_async_resync()` and `async_resync()` service method are not protected by lock. Can run concurrently with `_compute_and_enforce()`, causing:
     - Concurrent drift corrections
     - Command budget violations
     - Override state races
   - **Evidence**: `_async_resync` has no lock, but it calls `_enforce_desired_mode` which may conflict with locked `_compute_and_enforce`.

### HIGH (Likely to Misbehave)

5. **Task Cancellation Not Awaited - CancelledError Warnings**
   - **Location**: `pair_controller.py:231-236`, `atv_client.py:104-105`
   - **Issue**: Tasks are cancelled but not awaited, causing `asyncio.CancelledError` to propagate and create log warnings. Should wrap in try/except or await with proper handling.
   - **Evidence**: Tasks cancelled but no exception handling.

6. **Return-to-Art Timer Not Cancelled When ATV Becomes Active**
   - **Location**: `pair_controller.py:377-382`, `250-260`
   - **Issue**: When ATV becomes active during return-to-art delay, the timer checks `if not self._atv_active` before enforcing, but doesn't cancel the task proactively. Timer continues running and may fire incorrectly.
   - **Evidence**: Timer cancellation only in `_schedule_return_to_art()` when rescheduling, not when ATV activates.

7. **Manual Override Race Condition**
   - **Location**: `pair_controller.py:360-373`, `668-669`
   - **Issue**: Override is checked in `_compute_and_enforce` (line 360) but can be set in `_async_resync` (line 669) without lock coordination. If resync sets override while enforcement is checking it, race can occur.
   - **Evidence**: Override set at 669, checked at 360, but resync not locked.

8. **Presence Unknown State Doesn't Trigger Recompute**
   - **Location**: `pair_controller.py:318-326`
   - **Issue**: When presence state becomes unknown (from known state), the code sets `home_ok = None` but doesn't trigger enforcement. If presence was previously home/away and affected desired mode, the mode won't update.
   - **Evidence**: Only home/away transitions trigger (lines 311, 316), unknown handling (line 326) doesn't check for state change.

9. **ATV Push Listener Tasks Can Race During Cleanup**
   - **Location**: `atv_client.py:236-238, 248-250`
   - **Issue**: When listener callbacks create tasks and add them to `_listener_tasks`, but cleanup cancels them (line 104-105), there's a race window where a task is created but not yet added to set before cleanup runs. Also, tasks may access `client._set_state` after client is cleaned up.
   - **Evidence**: Task creation and set addition are not atomic relative to cleanup.

10. **Active Hours Update Race on Midnight Crossover**
    - **Location**: `pair_controller.py:267-284`
    - **Issue**: `_update_active_hours()` uses `datetime.now()` which can have slight differences between calls. If called exactly at midnight boundary, multiple concurrent calls could get different "now" values, causing inconsistent state.
    - **Impact**: Low, but edge case at midnight could cause inconsistent behavior.

### MEDIUM (Edge Case Failures)

11. **Fallback Media Player Never Used**
    - **Location**: `pair_controller.py:115`
    - **Issue**: `fallback_media_player` entity ID is stored but never read. When pyatv is unavailable, code should fall back to HA media_player entity state.
    - **Evidence**: Stored at init, never referenced.

12. **Verify Loop Timeout Can Exceed Intended Time**
    - **Location**: `frame_client.py:266-279`
    - **Issue**: Loop checks `(loop.time() - start) < max_time` but adds `await asyncio.sleep(0.8)` which can cause final iteration to exceed `max_time` by up to 0.8s. Should check BEFORE sleep, or cap total time more strictly.
    - **Evidence**: Line 277 sleeps after check, so final iteration can exceed max_time.

13. **Command Budget Window Not Rolling Correctly for Edge Cases**
    - **Location**: `pair_controller.py:558-566`
    - **Issue**: Window cleanup happens every command, but if no commands for >5min, old entries remain. Also, if system clock changes backward, old entries won't be cleaned.
    - **Impact**: Low, but could cause incorrect breaker triggers.

14. **Manual Override Activation Happens Inside Drift Check**
    - **Location**: `pair_controller.py:668-674`
    - **Issue**: Override is activated but then immediately checked at line 684. If override is set and current time is >= override_until (edge case timing), enforcement still runs.
    - **Evidence**: Line 669 sets override with `datetime.now() + timedelta`, line 684 checks `datetime.now() >= self._manual_override_until`. Race window exists.

15. **Resync Doesn't Update ATV Active State from Fallback**
    - **Location**: `pair_controller.py:632-647`
    - **Issue**: Resync reads Samsung state and recomputes desired, but never updates `_atv_active` from fallback media player if pyatv is disconnected.
    - **Evidence**: Only uses `self._atv_active` which comes from pyatv, never checks fallback.

16. **Debounce Task Not Tracked for Cancellation**
    - **Location**: `atv_client.py:188-205`
    - **Issue**: `_debounce_task` is cancelled in `_handle_disconnect` but if a new `_set_state` is called while disconnect is happening, new task might not be tracked properly.
    - **Evidence**: Task created at 205, but cancellation at 100 might race with creation.

17. **Startup Grace Task Not Awaited on Cleanup**
    - **Location**: `pair_controller.py:235-236`
    - **Issue**: Startup grace task is cancelled but not awaited, and if it's in `await asyncio.sleep(seconds)` it will raise CancelledError.
    - **Evidence**: Cancelled but not awaited, no exception handling.

18. **Services Call Enforcement Without Force Flag**
    - **Location**: `pair_controller.py:722-735`
    - **Issue**: Service methods should bypass cooldown and startup grace, but they call `_enforce_desired_mode` directly which still checks cooldown indirectly via `_should_enforce()` check in `_compute_and_enforce`. However, services bypass `_compute_and_enforce` entirely, so they bypass cooldown correctly, but also bypass lock protection.

### LOW (Polish/Edge Cases)

19. **Entity Update Tasks Not Cancelled on Unload**
    - **Location**: `entities/sensor.py:49-51`, `entities/binary_sensor.py:48-51, 116-118`
    - **Issue**: `async_track_time_interval` tasks are stored but might not be properly cleaned up if entity is removed before integration unloads.
    - **Evidence**: Tasks cleaned up via `async_on_remove`, but if controller is cleaned up before entities, tasks might leak.

20. **Active Hours Update Uses System Clock, Not Monotonic**
    - **Location**: `pair_controller.py:274`
    - **Issue**: `datetime.now()` can jump if system clock changes, but for active hours this is probably fine (user expects wall-clock time).

21. **Recent Events Buffer Not Persisted**
    - **Location**: `pair_controller.py:156`
    - **Issue**: Events are in-memory deque, lost on HA restart. Spec says "in-memory is acceptable for v0.1.0" so this is fine, but could be improved.

22. **Diagnostics May Access Controller After Cleanup**
    - **Location**: `diagnostics.py:30-31`
    - **Issue**: If diagnostics are called during unload, controller might be None but code doesn't check manager.controller before accessing.
    - **Evidence**: Checks `if not controller:` at 33, but accesses `manager.controller` at 30 without checking manager exists first.

## B) FIX PLAN

**Priority Order:**

1. **Fix service methods to use lock** (BLOCKER #1)
   - Wrap service calls in lock acquisition or call through `_compute_and_enforce(force=True)`

2. **Fix return-to-art task lock** (BLOCKER #2)
   - Acquire lock in return task or schedule enforcement through main flow

3. **Fix WOL attempts tracking** (BLOCKER #3)
   - Make wol_attempts instance variable or track properly with retry loop

4. **Fix resync lock protection** (BLOCKER #4)
   - Add lock to `_async_resync` or ensure it doesn't conflict

5. **Handle task cancellation properly** (HIGH #5)
   - Await cancelled tasks with exception handling

6. **Cancel return-to-art on ATV active** (HIGH #6)
   - Explicitly cancel timer when ATV becomes active

7. **Fix presence unknown state trigger** (HIGH #8)
   - Track previous home_ok and trigger if transitions to/from None

8. **Add fallback media player logic** (MEDIUM #11)
   - Use fallback when pyatv disconnected

9. **Fix verify loop timeout** (MEDIUM #12)
   - Check timeout before sleep

10. **Fix manual override timing race** (MEDIUM #14)
    - Use monotonic time or fix timing window

## C) PATCHES

