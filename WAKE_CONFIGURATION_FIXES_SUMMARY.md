# Wake Configuration and TV State Source Fixes Summary

**Date**: 2024-12-20  
**Status**: ✅ **ALL FIXES APPLIED**

---

## Overview

Replaced hard-coded WOL behavior with configurable wake methods and made the Samsung TV entity selectable. This allows users to:
- Select which media_player entity to use for TV state detection
- Choose wake method: remote KEY_POWER, WOL, or none
- Configure wake retry settings
- Avoid "degraded" health status when TV is reachable but off

---

## Issues Fixed

### ✅ FIXED: WOL doesn't wake TV, needs remote.send_command instead

**Problem**: WOL packets don't wake the Samsung Frame TV. Users need to use `remote.send_command(KEY_POWER)` via a Home Assistant remote entity.

**Solution**: 
- Added configurable wake method selection (remote_key_power, wol, none)
- Implemented `remote_key_power` wake method using `remote.send_command` service
- Added wake retry configuration (retries, delay, startup grace)

**Files Changed**:
1. `const.py`: Added wake method constants and defaults
2. `config_flow.py`: Added options for TV state source, wake remote, wake method, retry settings
3. `pair_controller.py`: Implemented wake logic with remote_key_power support

---

### ✅ FIXED: TV state source is hard-coded

**Problem**: Integration couldn't determine TV state reliably because it only used websocket connection status.

**Solution**:
- Added configurable `tv_state_source_entity_id` option (media_player selector)
- Integration now uses this entity to check TV state (on/off/unavailable)
- Health/reachability checks use entity state OR websocket connection

**Files Changed**:
1. `config_flow.py`: Added TV state source entity selector
2. `pair_controller.py`: Added `_check_tv_reachable()` and `_get_tv_state()` helpers

---

### ✅ FIXED: "Degraded" health when TV is off but reachable

**Problem**: Integration marked health as "degraded" when TV was off, even though TV was reachable on LAN (ports open, pingable).

**Solution**:
- Updated reachability checks to consider TV state entity (if configured)
- TV is considered "reachable" if:
  - TV state entity is not "unavailable", OR
  - Websocket connection succeeds
- Only mark degraded if TV is truly unreachable AND outside startup grace period

**Files Changed**:
1. `pair_controller.py`: Updated `_enforce_desired_mode()` to use new reachability logic

---

## New Configuration Options

### Options Flow Fields

1. **TV State Source Entity** (`tv_state_source_entity_id`)
   - Type: `media_player` entity selector
   - Purpose: Media player entity used to determine TV on/off/artmode state
   - Default: Auto-discovered from Samsung/Frame entities if not set

2. **Wake Remote Entity** (`wake_remote_entity_id`)
   - Type: `remote` entity selector
   - Purpose: Remote entity used to send KEY_POWER command
   - Required if `wake_method` is `remote_key_power`

3. **Wake Method** (`wake_method`)
   - Type: Dropdown selector
   - Options: `remote_key_power` (default), `wol`, `none`
   - Purpose: How to wake the TV when it's off

4. **Wake Retries** (`wake_retries`)
   - Type: Number (1-10)
   - Default: 3
   - Purpose: Number of wake attempts before giving up

5. **Wake Retry Delay** (`wake_retry_delay_seconds`)
   - Type: Number (1-30)
   - Default: 2
   - Purpose: Seconds to wait between wake attempts

6. **Wake Startup Grace** (`wake_startup_grace_seconds`)
   - Type: Number (0-300)
   - Default: 60
   - Purpose: Seconds after startup during which unreachable TV won't trigger degraded status

---

## Files Changed Summary

| File | Changes |
|------|---------|
| `const.py` | ✅ Added `WAKE_METHOD_*` constants<br>✅ Added `DEFAULT_WAKE_RETRIES`, `DEFAULT_WAKE_STARTUP_GRACE_SECONDS`<br>✅ Added `ACTION_REMOTE_WAKE` |
| `config_flow.py` | ✅ Added TV state source entity selector<br>✅ Added wake remote entity selector<br>✅ Added wake method dropdown<br>✅ Added wake retry settings (retries, delay, grace)<br>✅ Added entity validation (domain checks) |
| `pair_controller.py` | ✅ Store wake configuration from options<br>✅ Implement `_attempt_wake()` with remote_key_power and WOL support<br>✅ Implement `_check_tv_reachable()` using entity state<br>✅ Implement `_get_tv_state()` from entity<br>✅ Update `_enforce_desired_mode()` to use new wake/reachability logic<br>✅ Add backwards compatibility for existing configs<br>✅ Update drift logging to include wake method info |

---

## Implementation Details

### Wake Method: remote_key_power

When `wake_method == "remote_key_power"`:
```python
await hass.services.async_call(
    domain="remote",
    service="send_command",
    service_data={
        "entity_id": wake_remote_entity_id,
        "command": "KEY_POWER",
        "num_repeats": 1,
        "delay_secs": 0.4,
    },
    blocking=True,
)
```

### Reachability Check

TV is considered "reachable" if:
1. `tv_state_source_entity_id` is configured and entity state is not "unavailable", OR
2. Websocket connection to TV succeeds (`async_get_artmode()` returns non-None)

### Health/Degraded Logic

TV is marked "degraded" only if:
1. TV is unreachable (both entity unavailable AND websocket fails), AND
2. Outside startup grace period (if configured), AND
3. Wake attempts (if any) have been exhausted

TV is NOT marked degraded if:
- TV state entity reports "off" but entity exists (TV is reachable)
- TV is in startup grace period
- Wake method is "none" and TV is simply off

---

## Backwards Compatibility

### Auto-Discovery

For existing config entries without `tv_state_source_entity_id`:
1. On first run, integration searches for Samsung/Frame media_player entities
2. Matches by host IP, pair name, or entity name containing "samsung"/"frame"
3. Stores discovered entity in options for future use

### Default Wake Method

For existing config entries without `wake_method`:
1. If `wake_remote_entity_id` exists → defaults to `remote_key_power`
2. Else if `wol_enabled=True` and MAC configured → defaults to `wol`
3. Else → defaults to `none`

Default wake retry settings are applied if not present.

---

## Testing

### Expected Behavior

1. **Wake via Remote**: 
   - When TV is off and wake method is `remote_key_power`, integration calls `remote.send_command(KEY_POWER)`
   - Retries up to configured number of times with delay between attempts

2. **TV State Detection**:
   - Integration uses `tv_state_source_entity_id` to check TV state
   - Falls back to websocket connection if entity not configured

3. **Health Status**:
   - TV off but reachable (entity state = "off") → NOT degraded
   - TV unavailable and websocket fails → Degraded (after grace period)
   - TV in startup grace period → NOT degraded even if unreachable

4. **Drift Detection**:
   - Logs include wake method info when drift is detected
   - Wake attempts logged once per attempt (not spammed)

---

## Migration Notes

- **No breaking changes**: Existing configs continue to work
- **Auto-discovery**: First run after update will auto-discover TV entity if not configured
- **Default wake method**: Existing WOL configs continue to work, but users should switch to `remote_key_power` for better reliability
- **Options flow**: Users should configure TV state source and wake remote via integration options

---

## Next Steps

1. Copy updated files to Home Assistant
2. Restart Home Assistant
3. Configure options:
   - Set TV state source entity (media_player)
   - Set wake remote entity (remote)
   - Set wake method to `remote_key_power`
   - Adjust retry settings if needed
4. Verify:
   - TV wakes correctly when off
   - Health status doesn't show "degraded" when TV is off but reachable
   - Drift detection works correctly

