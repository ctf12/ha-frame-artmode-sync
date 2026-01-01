"""Decision engine for computing desired mode."""

from __future__ import annotations

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
    # Handle presence/away logic first
    if presence_mode == PRESENCE_MODE_ENTITY:
        if home_ok is False:
            # User is away
            if away_policy == AWAY_POLICY_TURN_TV_OFF:
                return MODE_OFF
            elif away_policy == AWAY_POLICY_KEEP_ART_ON:
                return MODE_ART
            # else: disabled, fall through to normal logic
        elif home_ok is None:
            # Unknown state
            if unknown_behavior == UNKNOWN_BEHAVIOR_TREAT_AS_AWAY:
                if away_policy == AWAY_POLICY_TURN_TV_OFF:
                    return MODE_OFF
                elif away_policy == AWAY_POLICY_KEEP_ART_ON:
                    return MODE_ART
            elif unknown_behavior == UNKNOWN_BEHAVIOR_TREAT_AS_HOME:
                pass  # Fall through to normal logic
            # else: ignore (default), fall through

    # Normal active hours logic
    if in_active_hours:
        if atv_active:
            return MODE_ATV
        else:
            return MODE_ART
    else:
        # Outside active hours
        if night_behavior == NIGHT_BEHAVIOR_DO_NOTHING:
            # Don't enforce, but we still compute (caller may ignore)
            # For "do nothing", we return current desired based on ATV
            # but the caller should not enforce this
            if atv_active:
                return MODE_ATV
            return MODE_ART
        elif night_behavior == NIGHT_BEHAVIOR_FORCE_OFF:
            return MODE_OFF
        elif night_behavior == NIGHT_BEHAVIOR_FORCE_ART:
            return MODE_ART
        else:
            # Default to ART
            return MODE_ART

