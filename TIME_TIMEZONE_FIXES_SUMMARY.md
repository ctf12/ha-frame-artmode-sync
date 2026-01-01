# Time Entity and Timezone Fixes Summary

**Date**: 2024-12-20  
**Status**: ✅ **ALL FIXES APPLIED**

---

## Issues Fixed

### ✅ FIXED: AttributeError: 'str' object has no attribute 'isoformat'

**Problem**: TimeEntity `native_value` was returning strings instead of `datetime.time` objects, causing HA to crash when trying to call `.isoformat()`.

**Root Cause**: Time entities (`time.great_room_active_start` / `time.great_room_active_end`) returned string values directly from config without parsing them to `datetime.time` objects.

**Solution**:
- Added `normalize_time()` helper function to parse string to `datetime.time`
- Updated `native_value` property to return `time | None` instead of `str | None`
- Parse time strings from config using `datetime.time.fromisoformat()` or `dt_util.parse_time()`
- Store values as ISO format strings (HH:MM:SS) in config, parse when reading

**Files Changed**:
1. `entity_helpers.py`: Added `normalize_time()` helper
2. `entities/time.py`: Fixed `native_value` to return `datetime.time`, added parsing

---

### ✅ FIXED: TypeError: can't compare offset-naive and offset-aware datetimes

**Problem**: Code used `datetime.now()` which returns timezone-naive datetimes, but some comparisons involved timezone-aware datetimes from normalization helpers.

**Root Cause**: Mixed use of `datetime.now()` (naive) and `normalize_datetime()` output (aware) in comparisons.

**Solution**:
- Replaced all `datetime.now()` calls with `dt_util.utcnow()` (timezone-aware UTC)
- Updated `ensure_isoformat()` to ensure datetime is timezone-aware before calling `.isoformat()`
- All internal datetime comparisons now use timezone-aware datetimes consistently

**Files Changed**:
1. `entity_helpers.py`: Updated `ensure_isoformat()` to ensure timezone-aware
2. `pair_controller.py`: Replaced all `datetime.now()` with `dt_util.utcnow()`
3. `atv_client.py`: Replaced all `datetime.now()` with `dt_util.utcnow()`
4. `entities/binary_sensor.py`: Replaced `datetime.now()` with `dt_util.utcnow()`

---

## Files Changed Summary

| File | Changes |
|------|---------|
| `entity_helpers.py` | ✅ Added `normalize_time()` helper<br>✅ Updated `ensure_isoformat()` to ensure timezone-aware |
| `entities/time.py` | ✅ Fixed `native_value` return type to `time \| None`<br>✅ Added time parsing using `normalize_time()`<br>✅ Store values as ISO strings in config |
| `pair_controller.py` | ✅ Replaced all `datetime.now()` with `dt_util.utcnow()`<br>✅ Updated `_update_active_hours()` to use `normalize_time()`<br>✅ Fixed indentation error |
| `atv_client.py` | ✅ Replaced all `datetime.now()` with `dt_util.utcnow()`<br>✅ Added `dt_util` import |
| `entities/binary_sensor.py` | ✅ Replaced `datetime.now()` with `dt_util.utcnow()` |

---

## Implementation Details

### Time Normalization (`normalize_time()`)

```python
def normalize_time(value: time | str | None) -> time | None:
    """
    Normalize a value to datetime.time or None.
    
    Accepts:
    - time: returned as-is
    - str: ISO time format string (HH:MM:SS or HH:MM) parsed using fromisoformat
    - None: returned as None
    """
```

**Parsing order**:
1. Try `time.fromisoformat()` (handles HH:MM:SS and HH:MM)
2. Fallback to `dt_util.parse_time()` if fromisoformat fails
3. Return None and log warning if both fail

### Timezone-Aware Datetimes

All datetime operations now use:
- `dt_util.utcnow()` - Get current UTC time (timezone-aware)
- `dt_util.as_utc()` - Convert naive datetime to UTC (from `normalize_datetime()`)
- `normalize_datetime()` already ensures timezone-aware output

### TimeEntity Implementation

```python
@property
def native_value(self) -> time | None:
    """Return current time value as datetime.time."""
    value = options.get("active_start", DEFAULT_ACTIVE_START)
    normalized = normalize_time(value)
    if normalized is None:
        # Fallback to default if parsing failed
        normalized = normalize_time(DEFAULT_ACTIVE_START)
    return normalized

async def async_set_value(self, value: time | str) -> None:
    """Set time value."""
    normalized = normalize_time(value)
    if normalized is None:
        _LOGGER.warning("Invalid time value provided: %s", value)
        return
    # Store as ISO format string (HH:MM:SS) for consistency
    time_str = normalized.isoformat()
    options["active_start"] = time_str
```

---

## Verification

### Syntax Check
```
✓ All files compile successfully
✓ No indentation errors
✓ No import errors
```

### Expected Behavior

1. **Time Entities**: 
   - Return `datetime.time` objects (not strings)
   - HA can call `.isoformat()` without errors
   - Time picker in UI works correctly

2. **Datetime Comparisons**:
   - All comparisons use timezone-aware datetimes
   - No "offset-naive and offset-aware" errors

3. **Storage**:
   - Times stored as ISO strings (HH:MM:SS) in config
   - Parsed to `datetime.time` when read
   - Consistent format across all operations

---

## Testing Checklist

- [ ] Time entities load without errors
- [ ] Time entities show correct values in UI
- [ ] Time entities can be set via UI without crashes
- [ ] No "isoformat" errors in logs
- [ ] No "offset-naive and offset-aware" errors in logs
- [ ] Active hours detection works correctly
- [ ] Override time calculations work correctly
- [ ] All datetime comparisons work without timezone errors

---

## Summary

✅ **Time entities return `datetime.time`** - Fixed `native_value` return type and added parsing  
✅ **All datetimes are timezone-aware** - Replaced `datetime.now()` with `dt_util.utcnow()`  
✅ **Time parsing is defensive** - `normalize_time()` handles strings safely  
✅ **Storage format consistent** - Times stored as ISO strings, parsed when read  
✅ **No more isoformat errors** - All `.isoformat()` calls are on timezone-aware datetimes  

The integration should now load without time/timezone-related errors.

