# Wake Method Refactor Summary - Remote Primary, WOL Last-Resort

**Date**: 2024-12-20  
**Status**: ✅ **ALL FIXES APPLIED**

---

## Overview

Refactored wake logic to make **remote KEY_POWER the primary method** and **WOL a last-resort fallback only**. This addresses the issue where WOL doesn't wake Samsung Frame TVs, but `remote.send_command(KEY_POWER)` does.

---

## Key Changes

### 1. Wake Method Priority

**Before**: Single `wake_method` selection (remote_key_power, wol, or none)

**After**: 
- **Primary**: Remote wake (`remote.send_command KEY_POWER`) - always tried first
- **Last-Resort Fallback**: WOL - only tried if remote wake fails AND TV is unreachable
- **Independent toggles**: `enable_remote_wake` and `enable_wol_fallback` can be configured separately

### 2. Improved Reachability Detection

**Before**: Only checked websocket connection and entity state == "unavailable"

**After**: TV is reachable if:
1. TV state entity exists and state is NOT "unavailable" (even if "off" is OK), OR
2. TCP connection to TV ports (8002, 8001) succeeds (fast check with 1s timeout), OR
3. Websocket connection succeeds (slower but definitive)

**Critical**: `media_player state == "off"` is NOT treated as unreachable. TV can be off but still reachable.

### 3. Wake Sequence Logic

```
When TV appears off/unreachable and wake is needed:
1. Try remote wake (if enabled)
   - Attempt up to remote_wake_retries times
   - Wait remote_wake_delay_secs between attempts
   - Log with [wake_remote_attempt] / [wake_remote_fail] tags
   
2. Re-check reachability after remote wake

3. If remote wake failed/not configured AND TV still unreachable:
   - Try WOL fallback (if enabled)
   - Attempt up to wol_retries times
   - Wait wol_delay_secs between attempts
   - Log with [wol_fallback_attempt] / [wol_fallback_fail] tags
   
4. Re-check reachability after WOL

5. Mark degraded only if:
   - TV is truly unreachable (all checks fail)
   - Both wake methods (if enabled) have been exhausted
   - Outside startup grace period
```

### 4. Options Flow Updates

**New Options**:
- `tv_state_source_entity_id` (media_player selector) - **Required**
- `wake_remote_entity_id` (remote selector) - **Optional but recommended**
- `enable_remote_wake` (toggle, default: ON if remote entity selected)
- `enable_wol_fallback` (toggle, default: OFF)
- `remote_wake_retries` (1-10, default: 2)
- `remote_wake_delay_secs` (1-30, default: 2)
- `wol_retries` (1-5, default: 1)
- `wol_delay_secs` (1-30, default: 2)
- `wol_broadcast` (string, default: "255.255.255.255")
- `startup_grace_secs` (0-300, default: 60)

**Removed**: Single `wake_method` dropdown (replaced by toggles)

### 5. Health/Degraded Logic

**Improved**:
- Only marks degraded if TV is **truly unreachable** (not just "off")
- Startup grace period prevents false degradations during HA boot
- Rate-limited logging (max once per 5 minutes) to avoid log spam
- Clear event tags: `[wake_remote_attempt]`, `[wake_remote_fail]`, `[wol_fallback_attempt]`, `[wol_fallback_fail]`, `[degraded]`

**Drift Detection**:
- Reports drift with wake configuration info
- Does not mark degraded if TV is off but reachable

### 6. Backwards Compatibility

**Migration**:
- Old `wake_method="remote_key_power"` → `enable_remote_wake=True`
- Old `wake_method="wol"` → `enable_wol_fallback=True` (WOL now fallback)
- Old retry settings migrated to new names:
  - `wake_retries` → `remote_wake_retries`
  - `wake_retry_delay_seconds` → `remote_wake_delay_secs`
  - `wake_startup_grace_seconds` → `startup_grace_secs`

**Auto-Discovery**:
- TV state source entity auto-discovered on first run if not configured
- Defaults set based on existing configuration

---

## Files Changed

| File | Changes |
|------|---------|
| `const.py` | ✅ Removed `WAKE_METHOD_*` constants<br>✅ Added `DEFAULT_REMOTE_WAKE_*` and `DEFAULT_WOL_*` constants<br>✅ Added `DEFAULT_WOL_BROADCAST` |
| `config_flow.py` | ✅ Replaced single `wake_method` dropdown with toggles<br>✅ Added separate retry/delay settings for remote and WOL<br>✅ Added WOL broadcast address setting<br>✅ Updated entity selectors with validation |
| `pair_controller.py` | ✅ Replaced single wake method with remote primary + WOL fallback<br>✅ Improved `_check_tv_reachable()` with TCP connection check<br>✅ Split `_attempt_wake()` into `_attempt_remote_wake()` and `_attempt_wol_fallback()`<br>✅ Updated `_enforce_desired_mode()` with new wake sequence<br>✅ Added rate-limited degraded logging<br>✅ Updated backwards compatibility migration<br>✅ Updated drift logging with wake config info |
| `frame_client.py` | ✅ Updated `async_wake()` to accept broadcast address parameter |

---

## Implementation Details

### Reachability Check (`_check_tv_reachable()`)

```python
1. Check TV state entity (if configured)
   - If entity exists and state != "unavailable" → reachable
   - Even if state == "off", TV is reachable

2. Try TCP connection to TV ports (8002, 8001)
   - Fast check with 1s timeout per port
   - Non-blocking, uses asyncio.wait_for

3. Fallback to websocket connection
   - Slower but definitive
   - 3s timeout
```

### Wake Sequence (`_enforce_desired_mode()`)

```python
if TV unreachable:
    # Step 1: Try remote wake (primary)
    if enable_remote_wake:
        remote_success = await _attempt_remote_wake()
        if remote_success:
            wait and re-check reachability
    
    # Step 2: Only try WOL if remote failed AND still unreachable
    if not remote_success and still_unreachable and enable_wol_fallback:
        wol_attempted = await _attempt_wol_fallback()
        if wol_attempted:
            wait and re-check reachability
    
    # Step 3: Mark degraded only if truly unreachable
    if still_unreachable and outside_grace_period:
        mark_degraded()  # Rate-limited logging
```

### Type Safety

✅ All datetime/timedelta normalization helpers from previous fix are still in place:
- `normalize_datetime()` used throughout
- `normalize_timedelta()` used for duration calculations
- `ensure_isoformat()` used for timestamp serialization

---

## Expected Behavior

### Scenario 1: TV Off, Remote Wake Enabled

1. Integration detects drift: desired=ART, actual=off
2. Checks reachability: TV state entity reports "off" → **reachable** (not degraded)
3. Attempts remote wake: sends KEY_POWER via remote entity
4. Waits 2 seconds
5. Re-checks reachability and state
6. If TV wakes: continues with enforcement
7. If TV still off: reports drift but **does not mark degraded** (TV is reachable)

### Scenario 2: TV Unreachable, Remote + WOL Enabled

1. Integration detects TV unreachable (entity unavailable AND TCP fails AND websocket fails)
2. Attempts remote wake (primary): tries 2 times with 2s delay
3. If remote wake fails: attempts WOL fallback (tries 1 time with 2s delay)
4. If still unreachable after both: marks degraded (rate-limited log)

### Scenario 3: Startup Grace Period

1. HA boots, integration starts
2. TV may be unreachable during startup (network not ready, etc.)
3. Within first 60 seconds: unreachable TV does NOT trigger degraded status
4. After 60 seconds: normal reachability checks apply

---

## Migration Notes

### For Existing Users

1. **First run after update**: 
   - Old `wake_method` setting automatically migrated to new toggles
   - TV state source entity auto-discovered
   - Defaults applied based on existing config

2. **Options should be reviewed**:
   - Verify TV state source entity is correct
   - Set wake remote entity if not already set
   - Enable `enable_remote_wake` (should be default if remote entity exists)
   - Decide if WOL fallback is needed (default: OFF)

3. **Behavior changes**:
   - Remote wake now tried FIRST (before WOL)
   - WOL only used as last-resort fallback
   - TV state "off" no longer triggers degraded status

---

## Testing Checklist

- [ ] TV off but reachable: Integration does not mark degraded
- [ ] Remote wake works: KEY_POWER command sent correctly
- [ ] WOL fallback works: Only used if remote fails
- [ ] Reachability check: TCP connection check works
- [ ] Startup grace: No false degradations during boot
- [ ] Rate limiting: Degraded logs not spammed
- [ ] Event tags: `[wake_remote_attempt]`, `[wol_fallback_attempt]` appear in logs
- [ ] Options flow: All new settings save correctly
- [ ] Backwards compatibility: Old configs migrate smoothly

---

## Summary

✅ **Remote wake is now PRIMARY** - always tried first if enabled  
✅ **WOL is LAST-RESORT fallback** - only if remote fails AND TV unreachable  
✅ **Reachability improved** - TCP check + "off" not treated as unreachable  
✅ **Health logic improved** - degraded only when truly unreachable  
✅ **Logging improved** - clear tags, rate-limited, no spam  
✅ **Backwards compatible** - existing configs migrate automatically  
✅ **Type safety maintained** - datetime/timedelta normalization in place  

The integration should now wake TVs reliably using remote KEY_POWER, with WOL as a true last-resort fallback only when needed.

