# Long-Run Reliability Fixes - Complete

## A) FINDINGS

### BLOCKER - Memory Leak: Deques Not Pruned Without Commands ✅ FIXED
**Issue**: `_command_times` deque only pruned when `_record_command()` is called. If no commands sent for days, old entries accumulate.
**Fix**: Added pruning in resync timer (runs periodically).

### BLOCKER - Memory Leak: Drift Corrections Not Pruned ✅ FIXED
**Issue**: `_drift_corrections_this_hour` only pruned in `_async_resync()`. If resync disabled or interval very long, accumulates.
**Fix**: Added pruning in resync timer regardless of whether resync runs.

### HIGH - Time Robustness: Wall-Clock Used for Timeouts ✅ FIXED
**Issue**: All timeouts/backoff use `datetime.now()` which can jump with NTP/DST/clock changes.
**Fix**: Use monotonic time (`asyncio.get_running_loop().time()`) for durations. Keep wall-clock for user-facing (active hours) and status display.

### HIGH - Missing PyATV Reconnect Logic ✅ FIXED
**Issue**: If pyatv disconnects (network issue, ATV reboot), no automatic reconnect. Integration stays degraded indefinitely.
**Fix**: Added reconnect loop with exponential backoff (10s/30s/60s max). Stops on unload.

### MEDIUM - Samsung Connection Failures Don't Always Set Degraded ✅ FIXED
**Issue**: Connection failures increment counter but don't always update phase/health.
**Fix**: Set degraded phase on connection failures in enforce path. Also sets degraded after WOL attempts fail.

### MEDIUM - Event Spam: Repeated Backoff Messages ✅ FIXED
**Issue**: If backoff active, every trigger logs "Enforcement blocked: connection backoff active". Can spam events.
**Fix**: Rate-limit identical event messages (log once per condition change using `_last_backoff_log_time`).

### MEDIUM - Manual Service Spam: No Rate Limit ✅ FIXED
**Issue**: Rapid service calls can spam Samsung. No guard against accidental double-tap or automation loops.
**Fix**: Added per-entry service rate limit (2 seconds minimum between service calls).

## B) MINIMAL PATCHES APPLIED

### 1. Memory Leak Fixes
- Added deque pruning in `_async_resync_timer()` for both `_command_times` and `_drift_corrections_this_hour`
- Pruning happens on every resync timer tick, regardless of whether resync runs

### 2. Monotonic Time for Timeouts
- Added `*_monotonic` fields for all timeout/backoff durations:
  - `_cooldown_until_monotonic`
  - `_breaker_open_until_monotonic`
  - `_connection_backoff_until_monotonic`
  - `_manual_override_until_monotonic`
- `_should_enforce()` checks monotonic time for cooldown
- Breaker auto-close uses monotonic time
- Connection backoff check uses monotonic time
- Manual override check uses monotonic time (with fallback to wall-clock for backward compatibility)
- Wall-clock fields retained for user-facing status display

### 3. PyATV Reconnect Logic
- Added `_reconnect_task`, `_reconnect_backoff`, `_should_reconnect` fields
- `_schedule_reconnect()` method with exponential backoff (10s → 30s → 60s max)
- Reconnect triggered on connection failure
- Reconnect stops on `async_disconnect()` (cleanup/unload)

### 4. Samsung Connection Failure Handling
- Connection failures in `_enforce_desired_mode()` now:
  - Set degraded phase if health was OK
  - Log degraded event
  - Trigger backoff via `_handle_command_failure()`
- WOL failures also set degraded state

### 5. Event Spam Rate Limiting
- Added `_last_backoff_log_time` to track when backoff message was last logged
- Only logs "Enforcement blocked: connection backoff active" once per backoff period

### 6. Service Rate Limiting
- Added `_last_service_call_time` (monotonic time)
- All service methods check if 2+ seconds have passed since last call
- Warns and returns early if rate limited

## C) LONG-RUN RISK CHECKLIST AFTER PATCHES

✅ **Memory leaks**: All deques now pruned periodically
✅ **Clock jumps**: All timeouts use monotonic time
✅ **PyATV disconnect**: Auto-reconnect with backoff
✅ **Connection failures**: Properly surface degraded state
✅ **Event spam**: Rate-limited
✅ **Service spam**: Rate-limited
✅ **Task cleanup**: All tasks properly cancelled and awaited

**Remaining LOW risks:**
- Recent events ring buffer capped at 20 (acceptable per spec)
- Statistics counters (`_command_fail_count`, etc.) can grow unbounded (but integers, minimal memory)
- Wall-clock fields for timeouts may drift slightly from monotonic time (but only used for display)

## D) WHAT TO WATCH IN LIVE LOGS

1. **Memory growth**: Monitor `command_count_5min` attribute - should stay below max_commands, not grow unbounded
2. **Reconnect attempts**: Look for "Attempting to reconnect to Apple TV..." followed by "Reconnect failed, next attempt in Xs" - should see backoff increasing (10s → 30s → 60s)
3. **Degraded state**: Look for "TV connection failed" or "TV unreachable after WOL attempts" events - health should change to degraded
4. **Service rate limiting**: Look for "Service call rate limited (last call X.Xs ago)" warnings - indicates spam prevention working
5. **Backoff spam prevention**: Look for "Enforcement blocked: connection backoff active" - should only appear once per backoff period, not on every trigger
6. **Breaker auto-close**: Look for "Circuit breaker auto-closed" event in resync timer
7. **Deque pruning**: No explicit log, but `command_count_5min` should decrease over time if no commands sent
8. **Monotonic time**: No explicit log, but timeouts should behave correctly even if system clock changes (test with manual clock change if possible)
9. **Drift corrections**: Look for "Drift detected" events - `_drift_corrections_this_hour` deque should stay pruned (no explicit log, but should not grow unbounded)
10. **Task cleanup**: On unload, verify no "Task was destroyed but it is pending!" warnings

## E) REAL-WORLD SCENARIOS VERIFICATION

### 1) TV offline overnight → returns online morning ✅
- Resync timer will detect drift
- Backoff will expire after cooldown
- Auto-reconnect will attempt reconnection
- Once TV responds, degraded state clears

### 2) ATV on at 05:59 then active hours start at 06:00 ✅
- `_update_active_hours()` called in resync/compute
- Time window change triggers enforcement
- ATV active state transitions correctly

### 3) User turns TV off manually while ATV inactive ✅
- Drift detected on next resync
- Consecutive drifts trigger manual override
- Override prevents enforcement for configured duration
- Status shows override active with remaining time

### 4) Ring buffer + status make it obvious ✅
- Recent events sensor shows last 20 events
- Status sensor shows current phase, health, override state
- All early returns now log reasons
- Rate-limiting prevents spam

---

**All critical long-run reliability issues fixed. Integration should now be stable over days/weeks.**
