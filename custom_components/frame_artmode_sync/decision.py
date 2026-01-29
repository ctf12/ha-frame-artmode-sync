"""Decision engine for computing desired mode."""

from __future__ import annotations

import logging
from datetime import datetime, time

from .const import (
    AWAY_POLICY_DISABLED,
    AWAY_POLICY_KEEP_ART_ON,
    AWAY_POLICY_TURN_TV_OFF,
    MODE_ART,
    MODE_ATV,
    MODE_OFF,
    NIGHT_BEHAVIOR_DO_NOTHING,
    NIGHT_BEHAVIOR_FORCE_ART,
    NIGHT_BEHAVIOR_FORCE_OFF,
    PRESENCE_MODE_DISABLED,
    PRESENCE_MODE_ENTITY,
    UNKNOWN_BEHAVIOR_IGNORE,
    UNKNOWN_BEHAVIOR_TREAT_AS_AWAY,
    UNKNOWN_BEHAVIOR_TREAT_AS_HOME,
)

_LOGGER = logging.getLogger(__name__)


def is_time_in_window(now: datetime, start_time: time, end_time: time) -> bool:
    """Check if current time is in active window (handles midnight crossover)."""
    now_time = now.time()

    if start_time <= end_time:
        # Normal case: window within same day
        return start_time <= now_time <= end_time
    else:
        # Window crosses midnight
        return now_time >= start_time or now_time <= end_time


def parse_time_string(time_str: str) -> time:
    """Parse time string (HH:MM:SS or HH:MM) to time object."""
    parts = time_str.split(":")
    hour = int(parts[0])
    minute = int(parts[1])
    second = int(parts[2]) if len(parts) > 2 else 0
    return time(hour, minute, second)


def compute_desired_mode(
    *,
    atv_active: bool,
    in_active_hours: bool,
    night_behavior: str,
    presence_mode: str,
    home_ok: bool | None,
    away_policy: str,
    unknown_behavior: str = UNKNOWN_BEHAVIOR_IGNORE,
) -> str:
    """
    Compute desired mode based on inputs.

    Returns MODE_OFF, MODE_ART, or MODE_ATV.
    """
    _LOGGER.debug("[decision] Computing desired mode: atv_active=%s, in_active_hours=%s, home_ok=%s, "
                 "presence_mode=%s, away_policy=%s, night_behavior=%s, unknown_behavior=%s",
                 atv_active, in_active_hours, home_ok, presence_mode, away_policy, night_behavior, unknown_behavior)
    
    # Handle presence/away logic first
    if presence_mode == PRESENCE_MODE_ENTITY:
        if home_ok is False:
            # User is away
            _LOGGER.debug("[decision] User is away (home_ok=False)")
            if away_policy == AWAY_POLICY_TURN_TV_OFF:
                _LOGGER.debug("[decision] Away policy: turn_tv_off -> MODE_OFF")
                return MODE_OFF
            elif away_policy == AWAY_POLICY_KEEP_ART_ON:
                _LOGGER.debug("[decision] Away policy: keep_art_on -> MODE_ART")
                return MODE_ART
            # else: disabled, fall through to normal logic
            _LOGGER.debug("[decision] Away policy: disabled, falling through to normal logic")
        elif home_ok is None:
            # Unknown state
            _LOGGER.debug("[decision] Presence unknown (home_ok=None), unknown_behavior=%s", unknown_behavior)
            if unknown_behavior == UNKNOWN_BEHAVIOR_TREAT_AS_AWAY:
                if away_policy == AWAY_POLICY_TURN_TV_OFF:
                    _LOGGER.debug("[decision] Unknown treated as away, turn_tv_off -> MODE_OFF")
                    return MODE_OFF
                elif away_policy == AWAY_POLICY_KEEP_ART_ON:
                    _LOGGER.debug("[decision] Unknown treated as away, keep_art_on -> MODE_ART")
                    return MODE_ART
            elif unknown_behavior == UNKNOWN_BEHAVIOR_TREAT_AS_HOME:
                _LOGGER.debug("[decision] Unknown treated as home, falling through to normal logic")
                pass  # Fall through to normal logic
            # else: ignore (default), fall through
            _LOGGER.debug("[decision] Unknown ignored, falling through to normal logic")

    # Normal active hours logic
    if in_active_hours:
        _LOGGER.debug("[decision] In active hours")
        if atv_active:
            _LOGGER.debug("[decision] ATV active -> MODE_ATV")
            return MODE_ATV
        else:
            _LOGGER.debug("[decision] ATV inactive -> MODE_ART")
            return MODE_ART
    else:
        # Outside active hours
        _LOGGER.debug("[decision] Outside active hours, night_behavior=%s", night_behavior)
        if night_behavior == NIGHT_BEHAVIOR_DO_NOTHING:
            # Don't enforce, but we still compute (caller may ignore)
            # For "do nothing", we return current desired based on ATV
            # but the caller should not enforce this
            if atv_active:
                _LOGGER.debug("[decision] Night do_nothing, ATV active -> MODE_ATV (won't enforce)")
                return MODE_ATV
            _LOGGER.debug("[decision] Night do_nothing, ATV inactive -> MODE_ART (won't enforce)")
            return MODE_ART
        elif night_behavior == NIGHT_BEHAVIOR_FORCE_OFF:
            _LOGGER.debug("[decision] Night force_off -> MODE_OFF")
            return MODE_OFF
        elif night_behavior == NIGHT_BEHAVIOR_FORCE_ART:
            _LOGGER.debug("[decision] Night force_art -> MODE_ART")
            return MODE_ART
        else:
            # Default to ART
            _LOGGER.debug("[decision] Night default -> MODE_ART")
            return MODE_ART

