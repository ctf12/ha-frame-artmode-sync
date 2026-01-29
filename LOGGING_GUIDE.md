# Logging Guide

This integration includes comprehensive logging to help analyze runtime behavior, debug issues, and understand state transitions.

## Log Levels

- **DEBUG**: Detailed flow information, state reads, decision details
- **INFO**: Important state changes, commands sent, results, transitions
- **WARNING**: Issues, failures, unexpected states, drift detection
- **ERROR**: Critical errors that prevent operation

## Key Log Prefixes

Logs use prefixes in brackets to identify the subsystem:
- `[atv_state_change]` - Apple TV state changes
- `[enforce]` - Enforcement decisions and actions
- `[resync]` - Periodic resync and drift detection
- `[decision]` - Decision engine computations
- `[force_art_on]` / `[force_art_off]` - Force command strategies
- `[wake_remote_attempt]` / `[wake_remote_fail]` - Remote wake attempts
- `[wol_fallback_attempt]` / `[wol_fallback_fail]` - WOL fallback attempts

## What Gets Logged

### Apple TV State Changes
- When ATV active state changes (on/off)
- Playback state changes (playing/paused/idle)
- Power state changes
- State computation details (which mode is used, grace period handling)

### Art Mode Commands
- When Art Mode commands are sent (ON/OFF)
- Command results (success/failure)
- Verification attempts and results
- Fallback strategy attempts (power toggle, power twice)

### Decision Making
- Desired mode computation with all inputs
- Why a particular mode was chosen (ATV active, active hours, presence, etc.)
- When desired mode changes

### Enforcement
- When enforcement is triggered
- Why enforcement might be blocked (cooldown, breaker, backoff, override)
- Command execution results
- State before and after commands

### TV Reachability
- Entity state reads (what state the TV entity reports)
- TCP connection attempts
- Websocket connection attempts
- Reachability determination

### Wake Attempts
- Remote wake attempts (which entity, which attempt)
- WOL fallback attempts
- Wake success/failure

### Drift Detection
- When drift is detected (desired vs actual mismatch)
- Resync operations
- Drift correction attempts

### Entity State Reads
- TV state source entity reads
- Presence entity reads
- Active hours calculations

## Example Log Flow

When Apple TV turns on:
```
INFO [atv_state_change] ATV state changed: active=False -> True, playback=playing
INFO [atv_state_change] Triggering enforcement due to ATV state change
DEBUG [decision] Computing desired mode: atv_active=True, in_active_hours=True, ...
DEBUG [decision] In active hours
DEBUG [decision] ATV active -> MODE_ATV
INFO Desired mode changed: ART -> ATV (atv_active=True, in_active_hours=True, ...)
INFO [enforce] Calling _enforce_desired_mode(ATV)
INFO [enforce] State change required: desired=ATV, actual=ON -> sending command
INFO Enforcing ATV mode: calling async_force_art_off()
INFO [force_art_off] Starting force Art Mode OFF with fallback strategy
INFO Setting Art Mode to OFF on TV at 192.168.1.100:8002
INFO Art Mode command sent successfully: OFF
INFO [force_art_off] Strategy 1: Command sent, verifying...
INFO Art Mode verification SUCCESS: state=False matches expected=False (took 0.8s)
INFO [force_art_off] Strategy 1 SUCCESS: Art Mode OFF verified
INFO Art Mode OFF command result (for ATV): success=True, action=set_art_off
INFO Switching TV input to HDMI1 for ATV
INFO [enforce] Command succeeded: action=set_art_off, desired=ATV
```

When drift is detected:
```
INFO [resync] Actual Art Mode state: ON
INFO [resync] Desired mode: ART (atv_active=False, in_active_hours=True)
WARNING [resync] DRIFT DETECTED: desired=ART, actual=ON
INFO [resync] Enforcing desired mode ART due to drift
INFO [enforce] State change required: desired=ART, actual=ON -> sending command
INFO Enforcing ART mode: calling async_force_art_on()
...
```

## Enabling Debug Logging

To see all DEBUG level logs in Home Assistant:

1. Go to **Settings** → **System** → **Logs**
2. Click **Load Full Home Assistant Log**
3. Or add to `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.frame_artmode_sync: debug
```

## What to Look For

### If Art Mode commands aren't working:
- Look for `[force_art_on]` or `[force_art_off]` logs
- Check if commands are sent: `"Setting Art Mode to ..."`
- Check verification results: `"Art Mode verification SUCCESS/FAILED"`
- Check which strategy succeeded or if all failed

### If Apple TV state isn't detected correctly:
- Look for `[atv_state_change]` logs
- Check power state and playback state values
- Verify active mode computation: `"ATV active computation: ..."`
- Check if state changes are triggering enforcement

### If enforcement is blocked:
- Look for `[enforce] Enforcement blocked:` messages
- Check cooldown, breaker, backoff, override states
- Verify `_should_enforce()` return value

### If drift is detected but not corrected:
- Look for `[resync] DRIFT DETECTED` messages
- Check if override is active
- Verify drift correction cooldown
- Check if limit is reached

### If wrong entity states are used:
- Look for `"TV state from entity ..."` logs
- Check `"Presence entity ... state:"` logs
- Verify entity IDs match your configuration
