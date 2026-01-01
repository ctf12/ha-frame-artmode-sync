# Frame Art Mode Sync - Deep Audit Report

## A) Audit Findings

### BLOCKERS (Must Fix Before Running)

1. **pyatv deprecated `loop=` parameter** 
   - **Location**: `atv_client.py:63,65,74`, `config_flow.py:57`
   - **Issue**: Modern pyatv (v0.14+) deprecated `loop=` parameter. Will fail at runtime.
   - **Evidence**: Code uses `scan(loop=asyncio.get_event_loop())` and `connect(config, loop=...)`

2. **Manual Override Detection Logic Missing**
   - **Location**: `pair_controller.py`
   - **Issue**: `EVENT_TYPE_OVERRIDE_ACTIVATED` constant exists but is never logged. There's no code that sets `_manual_override_until` when drift is detected (user likely changed state manually). Manual override can only be cleared, never activated.
   - **Evidence**: Search shows `EVENT_TYPE_OVERRIDE_ACTIVATED` in const.py but only `EVENT_TYPE_OVERRIDE_CLEARED` is ever logged.

3. **WOL (Wake-on-LAN) Not Implemented**
   - **Location**: `pair_controller.py`, `frame_client.py`
   - **Issue**: Config options (`wol_enabled`, `wake_retry_delay_seconds`, `frame_mac`) exist but no WOL implementation. No `wakeonlan` import or WOL packet sending code. Spec requires WOL when MAC provided and enabled.
   - **Evidence**: Grep shows WOL constants/config but no actual implementation.

4. **Return-to-Art Delay Logic Bug**
   - **Location**: `pair_controller.py:372`
   - **Issue**: Condition `(self._desired_mode == MODE_ATV or ...)` checks `self._desired_mode` but it was just set to `MODE_ART` on line 353. This condition will never match the ATV->ART transition correctly.
   - **Evidence**: Line 353 sets `self._desired_mode = desired` (which is ART), then line 372 checks if it's ATV.

5. **Services Cleanup Not Called**
   - **Location**: `__init__.py:45-53`
   - **Issue**: `async_unload_services()` exists but is never called in `async_unload_entry()`. Services remain registered after integration is unloaded, causing errors.
   - **Evidence**: `async_unload_entry` doesn't call `async_unload_services`.

### HIGH (Likely Runtime Failures)

6. **ATV Push Listener Tasks Not Tracked**
   - **Location**: `atv_client.py:230,240`
   - **Issue**: `asyncio.create_task()` in `ATVPushListener` callbacks creates untracked tasks. If controller is cleaned up, these tasks continue running and may crash or leak.
   - **Evidence**: Tasks created without storing references for cancellation.

7. **Cooldown Never Set After Enforcement**
   - **Location**: `pair_controller.py:405-492`
   - **Issue**: `_enforce_desired_mode()` checks cooldown but never sets `_cooldown_until` after successful enforcement. Cooldown only prevents entry but is never activated.
   - **Evidence**: `_cooldown_until` is only checked, never assigned after commands.

8. **Circuit Breaker Never Auto-Closes**
   - **Location**: `pair_controller.py:532-544`
   - **Issue**: Breaker opens when limit exceeded, but there's no logic to auto-close it when `_breaker_open_until` expires. Only manual `clear_breaker` or resync closes it.
   - **Evidence**: Breaker opening sets `_breaker_open_until` but no periodic check to close it.

9. **Service Methods Bypass Safety Checks**
   - **Location**: `pair_controller.py:655-663`
   - **Issue**: Service methods (`async_force_art_on`, etc.) call `_enforce_desired_mode()` directly, bypassing `_compute_and_enforce()` lock and cooldown checks. Spec says services should respect timeouts but not cooldown.
   - **Impact**: Could spam commands if called rapidly.

10. **Resync Bypasses Cooldown**
    - **Location**: `pair_controller.py:670-673`
    - **Issue**: `async_resync()` calls `_async_resync()` directly which checks drift correction cooldown but not the main enforcement cooldown. Could conflict with ongoing enforcement.

### MEDIUM (Quality/Robustness Issues)

11. **Idempotency Check Logic Incomplete**
    - **Location**: `pair_controller.py:448-455`
    - **Issue**: When `desired == MODE_ATV and actual_artmode is False`, code assumes success and only switches input. But if TV is actually off, Art Mode would be False too, so this doesn't distinguish between "TV on with Art off" vs "TV off".

12. **Night Behavior "do_nothing" Still Enforces**
    - **Location**: `pair_controller.py:377-378`
    - **Issue**: Decision engine returns a mode for `do_nothing`, but `_enforce_desired_mode()` is still called. Spec says "do not react to ATV transitions" - enforcement should be skipped entirely.

13. **Fallback Media Player Entity Not Used**
    - **Location**: `pair_controller.py:114`
    - **Issue**: `fallback_ha_media_player_entity` is stored but never read. Spec requires optional fallback when pyatv unavailable.

14. **Task Cancellation Not Awaited**
    - **Location**: `pair_controller.py:227-232`
    - **Issue**: Tasks are cancelled but not awaited, may raise `asyncio.CancelledError` warnings.

15. **Return-to-Art Timer Doesn't Cancel on ATV Active**
    - **Location**: `pair_controller.py:390-403`
    - **Issue**: When ATV becomes active while return-to-art timer is running, timer should be cancelled. Currently handled implicitly by checking `if not self._atv_active` but explicit cancel is clearer.

16. **No Timeout on Service Calls**
    - **Location**: `services.py:66-82`
    - **Issue**: Service handler calls controller methods without timeouts. Could hang if controller deadlocks.

17. **Entity Unique IDs May Collide**
    - **Location**: `entity_helpers.py:25`
    - **Issue**: Uses `f"{entry.entry_id}_{entity_id_suffix}"` but doesn't verify uniqueness if same entry_id used twice (shouldn't happen, but no validation).

### LOW (Style/Docs Improvements)

18. **Missing `.github/workflows` Directory Check**
    - **Location**: `.github/workflows/`
    - **Issue**: Workflows exist but should verify they're in correct format.

19. **Dashboard Example Uses Placeholder Entry IDs**
    - **Location**: `examples/dashboard_frames.yaml:66,73,80,87,94,101`
    - **Issue**: Uses `<entry_id_here>` placeholders. Should document how to find real IDs.

20. **Diagnostics Redacts Too Much**
    - **Location**: `diagnostics.py:13-20`
    - **Issue**: Redacts `frame_host` and `apple_tv_host` which aren't sensitive (local IPs). Only tokens should be redacted.

21. **No Persistent Notifications for Breaker/Degraded**
    - **Location**: Spec requirement
    - **Issue**: Spec says "If breaker opens or degraded persists > 10 minutes, create persistent_notification". Not implemented.

22. **pyatv `loop=` Parameter Also in Config Flow**
    - **Location**: `config_flow.py:57`
    - **Issue**: Same deprecated parameter issue in discovery.

## B) Fix Plan

**Priority Order (by severity):**

1. **Fix pyatv deprecated loop parameter** (BLOCKER #1)
   - Files: `atv_client.py`, `config_flow.py`
   - Remove `loop=` from all `scan()` and `connect()` calls
   - Scope: 4 locations

2. **Implement manual override activation** (BLOCKER #2)
   - Files: `pair_controller.py`
   - Add logic in `_async_resync()` to detect persistent drift and set `_manual_override_until`
   - Scope: ~20 lines

3. **Implement WOL support** (BLOCKER #3)
   - Files: `pair_controller.py`, `frame_client.py`, `manifest.json`
   - Add `wakeonlan` dependency, implement WOL in `frame_client.py`, call from `_enforce_desired_mode()` before connection attempts
   - Scope: ~50 lines + dependency

4. **Fix return-to-art delay logic** (BLOCKER #4)
   - Files: `pair_controller.py`
   - Track previous desired mode or check ATV state transition instead of comparing current desired mode
   - Scope: ~10 lines

5. **Call services cleanup on unload** (BLOCKER #5)
   - Files: `__init__.py`
   - Call `async_unload_services()` in `async_unload_entry()`
   - Scope: 1 line

6. **Track and cancel ATV listener tasks** (HIGH #6)
   - Files: `atv_client.py`, `pair_controller.py`
   - Store task references, cancel in cleanup
   - Scope: ~15 lines

7. **Set cooldown after enforcement** (HIGH #7)
   - Files: `pair_controller.py`
   - Set `_cooldown_until` after successful commands (not manual services)
   - Scope: ~5 lines

8. **Auto-close circuit breaker** (HIGH #8)
   - Files: `pair_controller.py`
   - Check `_breaker_open_until` in periodic resync or add timer
   - Scope: ~10 lines

9. **Add timeouts to service calls** (HIGH #16)
   - Files: `services.py`
   - Wrap service calls in `asyncio.wait_for()` with timeout
   - Scope: ~10 lines

10. **Fix night_behavior do_nothing enforcement** (MEDIUM #12)
    - Files: `pair_controller.py`
    - Skip enforcement entirely when night_behavior is `do_nothing` and outside active hours
    - Scope: ~5 lines

11. **Implement fallback media player** (MEDIUM #13)
    - Files: `pair_controller.py`
    - Use fallback entity when ATV client disconnected
    - Scope: ~30 lines

12. **Add persistent notifications** (LOW #21)
    - Files: `pair_controller.py`
    - Track degraded/breaker duration, create notifications
    - Scope: ~20 lines

## C) Patches

See separate patch files for each fix.

