# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2024-12-20

### Added
- Initial release of Frame Art Mode Sync integration
- Reliable Art Mode control for Samsung The Frame TVs (2018+)
- Apple TV integration using pyatv for real-time push updates
- Multi-TV/pair support with independent configuration
- Active hours time window configuration (supports midnight crossover)
- Optional presence/occupancy gating with configurable policies
- Comprehensive safety mechanisms:
  - Circuit breaker to prevent command spam
  - Cooldown periods and debouncing
  - Manual override detection (doesn't fight user actions)
  - Command budget limits with configurable thresholds
  - Exponential backoff on connection failures
  - Startup grace period to avoid premature enforcement
- Rich observability:
  - Status sensor with detailed attributes
  - Recent events log (last 20 events)
  - Pair health monitoring (ok/degraded/breaker_open)
  - Home Assistant event bus integration
- Configurable options:
  - ATV active detection mode (playing only, playing/paused, or power on)
  - Return-to-art delay after ATV turns off
  - Input switching (HDMI1/2/3 or none)
  - Night behavior (do nothing, force off, force art)
  - Dry-run mode for testing
  - Wake-on-LAN support for Frame TV wake
  - Apple TV debounce and grace period on disconnect
- Entity platforms:
  - Switch (enabled/disabled)
  - Time entities (active start/end)
  - Number entities (various delays/cooldowns/limits)
  - Select entities (night behavior, presence mode, away policy, input mode, ATV active mode)
  - Sensors (status, pair health, recent events)
  - Binary sensors (active hours, ATV active, override active)
- Custom services:
  - force_art_on, force_art_off, force_tv_on, force_tv_off
  - resync, clear_override, clear_breaker
- HACS support with proper metadata and CI workflows
- Dashboard example (Lovelace YAML)

### Technical Details
- Async/await throughout (no event-loop blocking)
- Monotonic time for timeout/backoff durations (resilient to clock changes)
- Memory-bounded data structures (capped deques, ring buffers)
- Automatic reconnection for Apple TV with exponential backoff
- Comprehensive error handling and degraded state management
- Token persistence for Samsung TV pairing
- Diagnostics support with sensitive data redaction

### Known Limitations
- Fallback media_player entity support is not yet implemented (pyatv is primary)
- Recent events buffer is in-memory only (lost on HA restart) - acceptable for v0.1.0
- Requires network connectivity between HA, Frame TV, and Apple TV
- Frame TV pairing requires manual approval on first setup
- Wake-on-LAN requires Frame TV MAC address configuration

### Dependencies
- pyatv >= 0.14.0 (MIT License)
- samsungtvws >= 2.6.0 (LGPL-3.0 License)
- wakeonlan >= 3.0.0

### Minimum Requirements
- Home Assistant 2024.1.0 or newer
- Python 3.11 or newer (HA requirement)

