# Frame Art Mode Sync

A robust Home Assistant integration that keeps Samsung The Frame TVs in Art Mode by default and reliably exits/returns to Art Mode based on Apple TV activity, with configurable active hours, optional presence gating, anti-loop protections, and comprehensive observability.

## Features

- **Reliable Art Mode Control**: Robust fallback strategies (verify, retry, power-toggle) to ensure Art Mode changes succeed
- **Apple TV Integration**: Uses `pyatv` for real-time push updates of Apple TV playback state
- **Multi-TV Support**: Configure multiple Frame TV / Apple TV pairs independently
- **Active Hours**: Define time windows when sync is active (supports midnight crossover)
- **Presence Integration**: Optional home/away gating with configurable policies
- **Safety Features**:
  - Circuit breaker to prevent command spam
  - Cooldown periods and debouncing
  - Manual override detection (doesn't fight user actions)
  - Command budget limits
  - Exponential backoff on failures
- **Observability**:
  - Status sensor with rich attributes
  - Recent events log (last 20 events)
  - Pair health monitoring
  - Home Assistant events for automation
- **Configurable**:
  - ATV active detection mode (playing only, playing/paused, or power on)
  - Return-to-art delay
  - Input switching (HDMI1/2/3 or none)
  - Night behavior (do nothing, force off, force art)
  - Dry-run mode for testing

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations**
3. Click the three dots menu (⋮) and select **Custom repositories**
4. Add this repository URL: `https://github.com/ctf12/ha-frame-artmode-sync`
5. Select category: **Integration**
6. Click **Add**
7. Click **Download** on the Frame Art Mode Sync card
8. Restart Home Assistant

### Manual Installation

1. Download the latest release or clone this repository
2. Copy the `custom_components/frame_artmode_sync` directory to your Home Assistant `custom_components` directory
3. Restart Home Assistant
4. Add the integration via Settings → Devices & Services → Add Integration

## Setup

### Prerequisites

- Samsung The Frame TV (2018 or newer, with Art Mode)
- Apple TV connected to the Frame TV via HDMI
- Both devices on the same network as Home Assistant
- Frame TV must have network access enabled

### Configuration Flow

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for "Frame Art Mode Sync"
3. Enter the following:
   - **Pair Name**: A friendly name (e.g., "Living Room TV")
   - **Frame TV IP Address**: The IP address of your Samsung Frame TV
   - **Frame TV Port**: Usually `8002` (default)
   - **Frame TV MAC Address**: Optional, for Wake-on-LAN support
   - **Tag**: A short identifier (e.g., "LR", "BR") used in pairing name
   - **Apple TV**: Choose discovered Apple TV or enter manually

4. Complete the setup and configure options as needed

### Pairing Prompt

When setting up, your Frame TV will display a pairing prompt. The integration uses a short client name (by default "FrameArtSync-{tag}") that's truncated to 18 characters or less. Approve the pairing on your TV to allow the integration to control it.

### Choosing HDMI Input

In the integration options, you can configure which HDMI input to switch to when exiting Art Mode:
- **none**: Don't switch inputs (assumes Apple TV is on current input)
- **hdmi1/hdmi2/hdmi3**: Switch to specific HDMI input
- **last_used**: Attempt to use last used input (best effort)

## Configuration Options

### Basic Settings

- **Enabled**: Enable/disable command sending (watchers still run)
- **Active Start/End**: Time window when sync is active
- **Return Delay**: Delay before returning to Art Mode after ATV turns off (seconds)
- **Cooldown**: Minimum time between enforcement attempts (seconds)

### Apple TV Settings

- **ATV Active Mode**: When to consider Apple TV "active"
  - `playing_only`: Only when actively playing
  - `playing_or_paused`: When playing or paused (default)
  - `power_on`: When Apple TV power is on
- **ATV Debounce**: Debounce time for ATV state changes (seconds)
- **ATV Grace on Disconnect**: Hold last-known state briefly if connection drops (seconds)

### Night Behavior

- **do_nothing**: Don't react to ATV changes outside active hours
- **force_off**: Turn TV off outside active hours
- **force_art**: Force Art Mode on outside active hours

### Presence (Optional)

- **Presence Mode**: `disabled` or `entity`
- **Presence Entity**: Home Assistant entity to monitor (person, group, binary_sensor, etc.)
- **Home States**: Comma-separated states that mean "home" (default: "home,on,true,True")
- **Away States**: Comma-separated states that mean "away" (default: "not_home,away,off,false,False")
- **Unknown Behavior**: How to treat unknown presence state
- **Away Policy**: What to do when away
  - `disabled`: Ignore away state
  - `turn_tv_off`: Turn TV off when away
  - `keep_art_on`: Keep Art Mode on when away

### Safety Settings

- **Max Commands per 5min**: Circuit breaker threshold
- **Breaker Cooldown**: How long circuit breaker stays open (minutes)
- **Startup Grace**: Don't enforce for this many seconds after HA restart
- **Resync Interval**: Periodic drift correction interval (minutes, 0 to disable)
- **Max Drift Corrections per Hour**: Limit on automatic corrections
- **Override Minutes**: How long manual override lasts when drift detected

### Advanced

- **Base Pairing Name**: Base name for TV pairing (default: "FrameArtSync")
- **WOL Enabled**: Enable Wake-on-LAN (requires MAC address)
- **Wake Retry Delay**: Delay before retrying after WOL (seconds)
- **Input Mode**: HDMI input to switch to
- **Dry Run**: Test mode (no commands sent)

## Entities

Each pair creates the following entities:

### Switches
- `switch.frame_artmode_sync_{pair}_enabled`: Enable/disable command sending

### Time
- `time.frame_artmode_sync_{pair}_active_start`: Active hours start time
- `time.frame_artmode_sync_{pair}_active_end`: Active hours end time

### Numbers
- `number.frame_artmode_sync_{pair}_return_delay`: Return delay (seconds)
- `number.frame_artmode_sync_{pair}_cooldown`: Cooldown period (seconds)
- `number.frame_artmode_sync_{pair}_atv_debounce`: ATV debounce (seconds)

### Selects
- `select.frame_artmode_sync_{pair}_night_behavior`: Night behavior
- `select.frame_artmode_sync_{pair}_presence_mode`: Presence mode
- `select.frame_artmode_sync_{pair}_away_policy`: Away policy
- `select.frame_artmode_sync_{pair}_input_mode`: Input switching mode
- `select.frame_artmode_sync_{pair}_atv_active_mode`: ATV active detection mode

### Sensors
- `sensor.frame_artmode_sync_{pair}_status`: Primary status sensor with rich attributes
- `sensor.frame_artmode_sync_{pair}_pair_health`: Health status (ok/degraded/breaker_open)
- `sensor.frame_artmode_sync_{pair}_recent_events`: Text log of recent events

### Binary Sensors
- `binary_sensor.frame_artmode_sync_{pair}_in_active_hours`: Active hours indicator
- `binary_sensor.frame_artmode_sync_{pair}_atv_active`: Apple TV active state
- `binary_sensor.frame_artmode_sync_{pair}_override_active`: Manual override indicator

## Services

All services support targeting by `device_id` or `entry_id`. If neither is specified, the service applies to all pairs.

- `frame_artmode_sync.force_art_on`: Force Art Mode on
- `frame_artmode_sync.force_art_off`: Force Art Mode off
- `frame_artmode_sync.force_tv_on`: Force TV on (exit Art Mode)
- `frame_artmode_sync.force_tv_off`: Force TV off
- `frame_artmode_sync.resync`: Trigger a resync/drift correction
- `frame_artmode_sync.clear_override`: Clear manual override
- `frame_artmode_sync.clear_breaker`: Clear circuit breaker

## Events

The integration fires `frame_artmode_sync_event` events with the following payload:
- `entry_id`: Config entry ID
- `pair_name`: Pair name
- `event_type`: Type of event (atv_on, atv_off, presence_change, etc.)
- `result`: Result (success/fail)
- `message`: Message
- `timestamp`: ISO timestamp
- `desired_mode`: Computed desired mode
- `atv_active`: ATV active state
- `home_ok`: Presence state (True/False/None)
- `breaker_open`: Circuit breaker state

## Troubleshooting

### Frame TV Not Responding

1. **Check TV state**: Frame TV must be on (not in standby) or in Art Mode. Standby mode typically doesn't respond to network commands.
2. **Verify network**: Ensure the Frame TV is on the same network as Home Assistant. Test connectivity: `ping <tv_ip_address>`
3. **Check IP address**: Verify the configured IP address is correct. You can find it in your router's DHCP client list.
4. **Check port**: Ensure port 8002 (or your configured port) is accessible. Some firewalls may block this port.
5. **Pairing**: If first-time setup, check if a pairing prompt appeared on the TV and was approved. The client name will be "FrameArtSync-{tag}" (e.g., "FrameArtSync-LR").
6. **Review diagnostics**: Check the status sensor attributes and diagnostics for specific error messages.
7. **Wake-on-LAN**: If enabled, ensure the MAC address is correct. WOL only works when the TV is in standby mode.

### Apple TV Not Detecting

1. Ensure Apple TV and Home Assistant are on the same network
2. Try manual entry instead of discovery
3. Check that `pyatv` dependency is installed correctly
4. Review logs for connection errors

### Circuit Breaker Opens

If the circuit breaker opens (too many commands in 5 minutes), it will automatically close after the cooldown period (configurable via `breaker_cooldown_minutes`). You can also manually clear it using the `clear_breaker` service.

**Symptoms**: Status shows "breaker_open", enforcement is blocked, and recent events show "Enforcement blocked: circuit breaker open".

**What to do**:
1. Clear immediately: Use the `clear_breaker` service from the dashboard or via Developer Tools → Services
2. Review configuration if this happens frequently:
   - Increase `max_commands_per_5min` (default: 10)
   - Increase `cooldown_seconds` (default: 5)
   - Check for network issues causing repeated retries
   - Review if drift corrections are running too frequently

### Status Shows "Degraded"

This indicates connection issues with the Frame TV. The integration will automatically retry with exponential backoff. Check:
- Network connectivity (ping the Frame TV IP)
- Frame TV power state (TV must be on or in Art Mode)
- Firewall settings (port 8002 must be accessible)
- Review the status sensor attributes for specific error messages

**Connection Backoff Active**: If you see "Enforcement blocked: connection backoff active" in recent events, the integration is waiting before retrying. This prevents connection storms. Backoff automatically clears after the delay period.

### Manual Override

If the integration detects persistent drift (likely from manual TV remote usage), it enters a manual override period. During this time, no commands are sent. Override clears automatically when:
- ATV becomes active (integration takes over)
- Override period expires (configurable via `override_minutes`)
- You call `clear_override` service

To clear manually: Use the `clear_override` service from the dashboard or via Developer Tools → Services.

### pyatv Reconnect Expectations

If Apple TV disconnects, the integration automatically attempts reconnection with exponential backoff:
- First attempt after 10 seconds
- Then 30 seconds, then 60 seconds (max)
- Backoff resets on successful connection

During reconnection, the integration holds the last-known Apple TV state for the grace period (configurable via `atv_grace_on_disconnect_seconds`). This prevents false triggers during brief network hiccups.

## Diagnostics

View diagnostics via **Settings** → **Devices & Services** → **Frame Art Mode Sync** → **[Your Pair]** → **Diagnostics**. This includes:
- Configuration (with sensitive data redacted)
- Controller state
- Client connection status
- Error counts

## Credits & Licensing

This project is licensed under the MIT License.

For credits and acknowledgements, see [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md).

For licensing information about dependencies, see [NOTICE](NOTICE).

**Disclaimer**: This project is not affiliated with, endorsed by, or associated with Samsung or Apple.

## Privacy & Security

- All network communication is local (no cloud services)
- Pairing tokens are stored locally in Home Assistant's storage
- No data is sent to external servers
- Sensitive information (tokens, IPs) is redacted in diagnostics

## Support

For issues, feature requests, or questions:
- Open an issue on [GitHub](https://github.com/ctf12/ha-frame-artmode-sync/issues)
- Check existing issues and discussions

## Preflight + Deploy

### Check for Dependency Updates

Before deploying, check if dependencies (`pyatv`, `samsungtvws`, `wakeonlan`) have updates available:

```bash
python3 scripts/check_dependencies.py
```

This script:
- Checks the latest versions from GitHub releases and PyPI
- Compares with versions in `manifest.json`
- Reports which dependencies have updates available
- Provides links to changelogs for review

**Note**: Before updating dependencies:
1. Review changelogs for breaking changes
2. Test the integration with new versions
3. Update `manifest.json` with new version requirements (e.g., `"pyatv>=0.15.0"`)

### Preflight Checks

Before deploying the integration to Home Assistant, run the preflight gate to catch import errors, circular dependencies, and other issues:

```bash
python3 tools/preflight.py
```

The preflight script performs comprehensive checks:
- **A) Import Order**: Tests all modules import in HA-like order
- **B) Dynamic Imports**: Imports all `.py` files to catch hidden issues
- **C) Circular Imports**: Detects circular dependency chains
- **D) Const Contract**: Verifies all imported constants exist in `const.py`
- **E) Config Flow Safety**: Ensures config flow doesn't import heavy deps at module level
- **F) Entrypoint Sanity**: Verifies `async_setup_entry` and `async_unload_entry` exist

If preflight passes, the integration is ready for deployment.

### Optional: Import Graph

To visualize import relationships and debug circular dependencies:

```bash
python3 tools/print_import_graph.py
```

### Deploy Command

After preflight passes, copy the integration to Home Assistant:

```bash
# From repo root
cp -r custom_components/frame_artmode_sync /path/to/homeassistant/config/custom_components/
```

Or use your preferred deployment method (git, HACS, etc.).

## Import Reliability Checklist

Before copying the integration to Home Assistant:

1. **Run smoke test** (optional but recommended):
   ```bash
   python3 tools/smoke_import.py
   ```
   This verifies all constants are properly defined. Full module testing requires HA environment.

2. **Clean cache files** before copying:
   ```bash
   find custom_components/frame_artmode_sync -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true
   find custom_components/frame_artmode_sync -name "*.pyc" -delete 2>/dev/null || true
   ```

3. **Copy integration** to Home Assistant:
   - Copy the entire `custom_components/frame_artmode_sync/` folder to your HA `custom_components/` directory

4. **Restart Home Assistant** and test:
   - Go to Settings → Devices & Services → Add Integration
   - Search for "Frame Art Mode Sync"
   - The config flow should load without errors

If you encounter import errors, ensure all dependencies are installed and run the preflight script to verify integration integrity.

## Contributing

Contributions are welcome! Please open a pull request or issue to discuss changes.
