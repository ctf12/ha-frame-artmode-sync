# Second-Pass Runtime Bug Audit

## PHASE 1: Runtime Threat Model

### State Machine Flow

```
States: OFF, ART, ATV
Health States: OK, DEGRADED, BREAKER_OPEN
Override States: NONE, ACTIVE

Transitions:
- ATV active → ATV (within active hours)
- ATV inactive → ART (after delay)
- Outside active hours → OFF/ART (per night_behavior)
- Presence away → OFF/ART (per away_policy)
- Manual override → BLOCK enforcement (continue monitoring)
- Breaker open → BLOCK commands (except manual services)
```

### Data Flow Sources of Truth

1. **atv_active**: 
   - Source: `ATVClient._current_state` (debounced)
   - Updated via: push listener callbacks → `_set_state` (debounced) → callback → `_handle_atv_state_change`
   - Debounce: configurable, default 2s

2. **desired_mode**:
   - Source: `compute_desired_mode()` (pure function)
   - Computed in: `_compute_and_enforce()`, `_async_resync()`
   - Depends on: atv_active, in_active_hours, night_behavior, presence, override

3. **actual_artmode**:
   - Source: `frame_client.async_get_artmode()` (reads from TV)
   - Updated: before enforcement, in resync

4. **Samsung Commands**:
   - Issued: `_enforce_desired_mode()` → `frame_client.async_force_art_on/off()`
   - Verified: `async_verify_artmode()` with bounded retries (max 8s total)

### Potential Loop Sources

1. State update → enforcement → state read → update → enforcement (protected by cooldown)
2. Resync → drift → enforcement → state change → resync (protected by drift cooldown)
3. ATV callback → state change → enforce → ATV callback (protected by debounce + cooldown)
4. Presence change → enforce → state read → presence change (no loop, one-way)

## PHASE 2: Edge Case Analysis

### A) Apple TV Flaps (playing → paused → idle → playing within 3s)
**Status**: Debounce should handle, but verify task cancellation.

### B) Apple TV Disconnects for 30s Then Reconnects
**Status**: Grace period holds state. Reconnect should update.

### C) HA Restarts While TV in ART and ATV Active
**Status**: Startup grace prevents immediate enforcement.

### D) Presence Entity Goes Unknown/Unavailable
**Status**: Handled but doesn't trigger recompute if was known before.

### E) Active Hours Window Crosses Midnight (22:00–06:00)
**Status**: Logic handles this correctly.

### F) Samsung WS Connect Fails and WOL Enabled
**Status**: WOL logic exists but has bug (attempts never increment).

### G) Circuit Breaker Opens Then Manual Service Called
**Status**: Manual services bypass breaker check - CORRECT per spec.

### H) Return-to-Art Timer Scheduled, Then ATV Becomes Active
**Status**: Timer checks ATV state but doesn't cancel proactively.

### I) Drift Correction Runs While Manual Override Active
**Status**: Checked but race condition possible.

### J) Dry-Run Enabled: Verify NO Samsung Commands
**Status**: Dry-run check is early in `_enforce_desired_mode` - correct.

## PHASE 3: Bug Findings

