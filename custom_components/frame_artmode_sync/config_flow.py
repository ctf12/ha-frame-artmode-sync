"""Config flow for Frame Art Mode Sync."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    AWAY_POLICY_DISABLED,
    DEFAULT_ACTIVE_END,
    DEFAULT_ACTIVE_START,
    DEFAULT_ATV_ACTIVE_MODE_PLAYING_OR_PAUSED,
    DEFAULT_ATV_DEBOUNCE_SECONDS,
    DEFAULT_ATV_GRACE_SECONDS_ON_DISCONNECT,
    DEFAULT_BASE_PAIRING_NAME,
    DEFAULT_BREAKER_COOLDOWN_MINUTES,
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_DRIFT_CORRECTION_COOLDOWN_MINUTES,
    DEFAULT_ENABLED,
    DEFAULT_MAX_COMMANDS_PER_5MIN,
    DEFAULT_MAX_DRIFT_CORRECTIONS_PER_HOUR,
    DEFAULT_OVERRIDE_MINUTES,
    DEFAULT_RESYNC_INTERVAL_MINUTES,
    DEFAULT_RETURN_DELAY_SECONDS,
    DEFAULT_STARTUP_GRACE_SECONDS,
    DEFAULT_REMOTE_WAKE_DELAY_SECONDS,
    DEFAULT_REMOTE_WAKE_RETRIES,
    DEFAULT_WAKE_RETRY_DELAY_SECONDS,
    DEFAULT_WAKE_STARTUP_GRACE_SECONDS,
    DEFAULT_WOL_BROADCAST,
    DEFAULT_WOL_DELAY_SECONDS,
    DEFAULT_WOL_RETRIES,
    DOMAIN,
    INPUT_MODE_HDMI1,
    INPUT_MODE_NONE,
    NIGHT_BEHAVIOR_FORCE_OFF,
    PRESENCE_MODE_DISABLED,
)

_LOGGER = logging.getLogger(__name__)

try:
    from pyatv import scan, pair, connect
    from pyatv.const import Protocol
    from pyatv.exceptions import AuthenticationError, NotPairedError, PairingError
    PYATV_AVAILABLE = True
except ImportError:
    scan = None
    pair = None
    connect = None
    PYATV_AVAILABLE = False


async def async_discover_apple_tvs(hass: HomeAssistant) -> list[dict[str, str]]:
    """Discover Apple TVs on the network."""
    if scan is None:
        return []

    try:
        loop = asyncio.get_running_loop()
        # pyatv compatibility: some versions require loop parameter
        try:
            results = await scan(loop=loop, timeout=5)
        except TypeError:
            # Fallback for versions that don't accept loop parameter
            results = await scan(timeout=5)
        
        devices = []
        for atv in results:
            devices.append({
                "identifier": str(atv.identifier),
                "name": atv.name,
                "host": str(atv.address),
            })
        return devices
    except Exception as ex:
        _LOGGER.error("Error discovering Apple TVs: %s", ex)
        return []


class FrameArtModeSyncConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Frame Art Mode Sync."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self.discovered_atvs: list[dict[str, str]] = []
        self.data: dict[str, Any] = {}
        self._pairing = None
        self._pairing_protocol = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            # Discover Apple TVs
            self.discovered_atvs = await async_discover_apple_tvs(self.hass)
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({
                    vol.Required("pair_name"): str,
                    vol.Required("frame_host"): str,
                    vol.Optional("frame_port", default=8002): int,
                    vol.Optional("frame_mac"): str,
                    vol.Required("tag"): str,
                    vol.Required(
                        "apple_tv_choice",
                        default="manual" if not self.discovered_atvs else "discovered"
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["discovered", "manual"],
                            translation_key="apple_tv_choice",
                        )
                    ),
                }),
            )

        self.data = {**user_input}
        self.data["frame_port"] = user_input.get("frame_port", 8002)

        if user_input.get("apple_tv_choice") == "discovered" and self.discovered_atvs:
            return await self.async_step_select_apple_tv()
        else:
            return await self.async_step_apple_tv_manual()

    async def async_step_select_apple_tv(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select discovered Apple TV."""
        if user_input is None:
            options = {
                atv["identifier"]: f"{atv['name']} ({atv['host']})"
                for atv in self.discovered_atvs
            }
            return self.async_show_form(
                step_id="select_apple_tv",
                data_schema=vol.Schema({
                    vol.Required("apple_tv_identifier"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options)
                    ),
                }),
            )

        selected_id = user_input["apple_tv_identifier"]
        selected_atv = next(
            (atv for atv in self.discovered_atvs if atv["identifier"] == selected_id),
            None,
        )
        if selected_atv:
            self.data["apple_tv_host"] = selected_atv["host"]
            self.data["apple_tv_identifier"] = selected_atv["identifier"]

        # Check if pairing is needed before proceeding
        return await self.async_step_pair_apple_tv()

    async def async_step_apple_tv_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Enter Apple TV details manually."""
        if user_input is None:
            return self.async_show_form(
                step_id="apple_tv_manual",
                data_schema=vol.Schema({
                    vol.Required("apple_tv_host"): str,
                    vol.Optional("apple_tv_identifier"): str,
                }),
            )

        self.data.update(user_input)
        return await self.async_step_pair_apple_tv()

    async def async_step_pair_apple_tv(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Pair with Apple TV if needed."""
        if not PYATV_AVAILABLE:
            # Skip pairing if pyatv not available, proceed to options
            return await self.async_step_options()
        
        apple_tv_host = self.data.get("apple_tv_host")
        apple_tv_identifier = self.data.get("apple_tv_identifier")
        
        if not apple_tv_host:
            return await self.async_step_options()
        
        # Try to scan for the Apple TV
        try:
            loop = asyncio.get_running_loop()
            try:
                if apple_tv_identifier:
                    results = await scan(loop=loop, identifier=apple_tv_identifier, timeout=10)
                else:
                    results = await scan(loop=loop, hosts=[apple_tv_host], timeout=10)
            except TypeError:
                if apple_tv_identifier:
                    results = await scan(identifier=apple_tv_identifier, timeout=10)
                else:
                    results = await scan(hosts=[apple_tv_host], timeout=10)
            
            if not results:
                _LOGGER.warning("Could not find Apple TV for pairing, proceeding without pairing")
                return await self.async_step_options()
            
            config = results[0]
            
            # Try to connect to see if pairing is needed
            try:
                try:
                    atv = await connect(config, loop=loop)
                except TypeError:
                    atv = await connect(config)
                # Connection successful, no pairing needed
                await atv.close()
                _LOGGER.info("Apple TV already paired, proceeding to options")
                return await self.async_step_options()
            except (AuthenticationError, NotPairedError):
                # Pairing is required
                pass
            except Exception as ex:
                _LOGGER.warning("Error checking pairing status: %s, proceeding anyway", ex)
                return await self.async_step_options()
            
            # Pairing is needed
            if user_input is None:
                # Start pairing process
                try:
                    # Find MRP protocol (most common for Apple TV)
                    pairing = None
                    pairing_protocol = None
                    for protocol in config.protocols:
                        if protocol in (Protocol.MRP, Protocol.AirPlay, Protocol.Companion):
                            try:
                                pairing = await pair(config, protocol, loop=loop)
                            except TypeError:
                                pairing = await pair(config, protocol)
                            if pairing:
                                pairing_protocol = protocol
                                break
                    
                    if not pairing:
                        _LOGGER.warning("No supported pairing protocol found. Available protocols: %s", 
                                      [p.name for p in config.protocols])
                        return await self.async_step_options()
                    
                    # Store pairing object for PIN entry
                    self._pairing = pairing
                    self._pairing_protocol = pairing_protocol
                    
                    # Get PIN (will be displayed on Apple TV)
                    pin = await pairing.begin()
                    
                    return self.async_show_form(
                        step_id="pair_apple_tv",
                        data_schema=vol.Schema({
                            vol.Required("pin", default=""): str,
                        }),
                        description_placeholders={
                            "pin": pin if pin else "Check your Apple TV screen for the PIN code",
                        },
                        errors={},
                    )
                except Exception as pair_ex:
                    _LOGGER.error("Error starting pairing: %s", pair_ex)
                    return self.async_show_form(
                        step_id="pair_apple_tv",
                        data_schema=vol.Schema({
                            vol.Required("pin", default=""): str,
                        }),
                        errors={"base": "pairing_failed"},
                    )
            
            # User entered PIN
            pin = user_input.get("pin", "")
            if not pin:
                return self.async_show_form(
                    step_id="pair_apple_tv",
                    data_schema=vol.Schema({
                        vol.Required("pin", default=""): str,
                    }),
                    errors={"pin": "pin_required"},
                )
            
            try:
                # Complete pairing with the PIN entered by user
                await self._pairing.finish(pin)
                _LOGGER.info("Successfully paired with Apple TV")
                
                # CRITICAL: Save credentials after pairing
                # The config object now contains credentials, but we need to persist them
                # Store the config object temporarily so we can save credentials
                self._paired_config = config
                
                # Save credentials to storage (will be loaded when connecting later)
                from .storage import async_save_atv_credentials
                # Note: We don't have entry yet, so we'll save during entry creation
                # Store config in flow data for later
                self.data["_paired_atv_config"] = config
                
                return await self.async_step_options()
            except Exception as finish_ex:
                _LOGGER.error("Pairing failed with PIN: %s", finish_ex)
                # Clean up pairing object on failure
                try:
                    await self._pairing.close()
                except Exception:
                    pass
                self._pairing = None
                return self.async_show_form(
                    step_id="pair_apple_tv",
                    data_schema=vol.Schema({
                        vol.Required("pin", default=""): str,
                    }),
                    errors={"pin": "pairing_failed"},
                )
        except Exception as ex:
            _LOGGER.error("Error during pairing process: %s", ex)
            # Proceed to options even if pairing fails (user can pair manually later)
            return await self.async_step_options()

    async def async_step_options(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure options."""
        if user_input is None:
            return self.async_show_form(
                step_id="options",
                data_schema=vol.Schema({
                    vol.Optional(
                        "fallback_ha_media_player_entity"
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="media_player")
                    ),
                    vol.Optional("presence_mode", default=PRESENCE_MODE_DISABLED): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["disabled", "entity"],
                            translation_key="presence_mode",
                        )
                    ),
                }),
            )

        self.data.update(user_input)

        # Create entry with defaults
        entry_data = {
            **self.data,
            "enabled": DEFAULT_ENABLED,
            "active_start": DEFAULT_ACTIVE_START,
            "active_end": DEFAULT_ACTIVE_END,
            "return_delay_seconds": DEFAULT_RETURN_DELAY_SECONDS,
            "cooldown_seconds": DEFAULT_COOLDOWN_SECONDS,
            "atv_debounce_seconds": DEFAULT_ATV_DEBOUNCE_SECONDS,
            "atv_grace_seconds_on_disconnect": DEFAULT_ATV_GRACE_SECONDS_ON_DISCONNECT,
            "atv_active_mode": DEFAULT_ATV_ACTIVE_MODE_PLAYING_OR_PAUSED,
            "night_behavior": NIGHT_BEHAVIOR_FORCE_OFF,
            "presence_mode": user_input.get("presence_mode", PRESENCE_MODE_DISABLED),
            "away_policy": AWAY_POLICY_DISABLED,
            "input_mode": INPUT_MODE_HDMI1,
            "base_pairing_name": DEFAULT_BASE_PAIRING_NAME,
            "wol_enabled": bool(self.data.get("frame_mac")),
            "wake_retry_delay_seconds": DEFAULT_WAKE_RETRY_DELAY_SECONDS,
            "override_minutes": DEFAULT_OVERRIDE_MINUTES,
            "resync_interval_minutes": DEFAULT_RESYNC_INTERVAL_MINUTES,
            "max_drift_corrections_per_hour": DEFAULT_MAX_DRIFT_CORRECTIONS_PER_HOUR,
            "drift_correction_cooldown_minutes": DEFAULT_DRIFT_CORRECTION_COOLDOWN_MINUTES,
            "max_commands_per_5min": DEFAULT_MAX_COMMANDS_PER_5MIN,
            "breaker_cooldown_minutes": DEFAULT_BREAKER_COOLDOWN_MINUTES,
            "startup_grace_seconds": DEFAULT_STARTUP_GRACE_SECONDS,
            "dry_run": False,
        }

        # Store paired config in flow data so we can save it after entry creation
        if self._paired_config:
            # Store in hass.data temporarily - will be saved in async_setup_entry
            self.hass.data.setdefault(f"{DOMAIN}_pending_credentials", {})
            self.hass.data[f"{DOMAIN}_pending_credentials"][self.data["pair_name"]] = self._paired_config
        
        return self.async_create_entry(title=self.data["pair_name"], data=entry_data)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> FrameArtModeSyncOptionsFlowHandler:
        """Get the options flow for this handler."""
        return FrameArtModeSyncOptionsFlowHandler(config_entry)


class FrameArtModeSyncOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Normalize empty strings to None for entity fields
            if user_input.get("tv_state_source_entity_id") == "":
                user_input["tv_state_source_entity_id"] = None
            if user_input.get("wake_remote_entity_id") == "":
                user_input["wake_remote_entity_id"] = None
            if user_input.get("presence_entity_id") == "":
                user_input["presence_entity_id"] = None
            
            # Validate entity IDs if provided
            if user_input.get("tv_state_source_entity_id"):
                entity_id = user_input["tv_state_source_entity_id"]
                # EntitySelector can return a list, extract first item if needed
                if isinstance(entity_id, list):
                    entity_id = entity_id[0] if entity_id else None
                    user_input["tv_state_source_entity_id"] = entity_id
                
                if entity_id:
                    state = self.hass.states.get(entity_id)
                    if not state:
                        return self.async_show_form(
                            step_id="init",
                            data_schema=vol.Schema(self._get_schema()),
                            errors={"tv_state_source_entity_id": "entity_not_found"},
                        )
                    if not entity_id.startswith("media_player."):
                        return self.async_show_form(
                            step_id="init",
                            data_schema=vol.Schema(self._get_schema()),
                            errors={"tv_state_source_entity_id": "must_be_media_player"},
                        )
            
            if user_input.get("wake_remote_entity_id"):
                entity_id = user_input["wake_remote_entity_id"]
                # EntitySelector can return a list, extract first item if needed
                if isinstance(entity_id, list):
                    entity_id = entity_id[0] if entity_id else None
                    user_input["wake_remote_entity_id"] = entity_id
                
                if entity_id:
                    state = self.hass.states.get(entity_id)
                    if not state:
                        return self.async_show_form(
                            step_id="init",
                            data_schema=vol.Schema(self._get_schema()),
                            errors={"wake_remote_entity_id": "entity_not_found"},
                        )
                    if not entity_id.startswith("remote."):
                        return self.async_show_form(
                            step_id="init",
                            data_schema=vol.Schema(self._get_schema()),
                            errors={"wake_remote_entity_id": "must_be_remote"},
                        )
            
            # Update options
            current_options = dict(self._config_entry.options)
            current_options.update(user_input)
            return self.async_create_entry(title="", data=current_options)

        options = {**self._config_entry.data, **self._config_entry.options}
        schema = self._get_schema(options)
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))

    def _get_schema(self, options: dict[str, Any] | None = None) -> dict:
        """Get the options schema."""
        if options is None:
            options = {**self._config_entry.data, **self._config_entry.options}
        
        # Start with the most important/commonly used fields first
        schema = {
            # Basic settings
            vol.Optional("enabled", default=options.get("enabled", DEFAULT_ENABLED)): bool,
            vol.Optional("active_start", default=options.get("active_start", DEFAULT_ACTIVE_START)): str,
            vol.Optional("active_end", default=options.get("active_end", DEFAULT_ACTIVE_END)): str,
            # TV state and wake configuration (important fields first)
            vol.Optional(
                "tv_state_source_entity_id",
                default=options.get("tv_state_source_entity_id"),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player", multiple=False)
            ),
            vol.Optional(
                "wake_remote_entity_id",
                default=options.get("wake_remote_entity_id"),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="remote", multiple=False)
            ),
            vol.Optional(
                "enable_remote_wake",
                default=options.get("enable_remote_wake", bool(options.get("wake_remote_entity_id"))),
            ): bool,
            vol.Optional(
                "enable_wol_fallback",
                default=options.get("enable_wol_fallback", False),
            ): bool,
            vol.Optional(
                "return_delay_seconds",
                default=options.get("return_delay_seconds", DEFAULT_RETURN_DELAY_SECONDS),
            ): vol.All(int, vol.Range(min=0, max=300)),
            vol.Optional(
                "cooldown_seconds",
                default=options.get("cooldown_seconds", DEFAULT_COOLDOWN_SECONDS),
            ): vol.All(int, vol.Range(min=0, max=300)),
            vol.Optional(
                "atv_debounce_seconds",
                default=options.get("atv_debounce_seconds", DEFAULT_ATV_DEBOUNCE_SECONDS),
            ): vol.All(int, vol.Range(min=0, max=60)),
            vol.Optional(
                "atv_active_mode",
                default=options.get("atv_active_mode", DEFAULT_ATV_ACTIVE_MODE_PLAYING_OR_PAUSED),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["playing_only", "playing_or_paused", "power_on"],
                    translation_key="atv_active_mode",
                )
            ),
            vol.Optional(
                "atv_grace_seconds_on_disconnect",
                default=options.get("atv_grace_seconds_on_disconnect", DEFAULT_ATV_GRACE_SECONDS_ON_DISCONNECT),
            ): vol.All(int, vol.Range(min=0, max=300)),
            vol.Optional(
                "night_behavior",
                default=options.get("night_behavior", NIGHT_BEHAVIOR_FORCE_OFF),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["do_nothing", "force_off", "force_art"],
                    translation_key="night_behavior",
                )
            ),
            vol.Optional(
                "presence_mode",
                default=options.get("presence_mode", PRESENCE_MODE_DISABLED),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["disabled", "entity"],
                    translation_key="presence_mode",
                )
            ),
        }

        # Conditional presence fields
        if options.get("presence_mode") == "entity":
            schema.update({
                vol.Optional("presence_entity_id", default=options.get("presence_entity_id")): selector.EntitySelector(
                    selector.EntitySelectorConfig(multiple=False)
                ),
                vol.Optional("home_states", default=options.get("home_states", "home,on,true,True")): str,
                vol.Optional("away_states", default=options.get("away_states", "not_home,away,off,false,False")): str,
                vol.Optional(
                    "unknown_behavior",
                    default=options.get("unknown_behavior", "ignore"),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["ignore", "treat_as_home", "treat_as_away"],
                        translation_key="unknown_behavior",
                    )
                ),
                vol.Optional(
                    "away_policy",
                    default=options.get("away_policy", AWAY_POLICY_DISABLED),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["disabled", "turn_tv_off", "keep_art_on"],
                        translation_key="away_policy",
                    )
                ),
            })

        # Add remaining advanced settings
        schema.update({
            vol.Optional(
                "remote_wake_retries",
                default=options.get("remote_wake_retries", DEFAULT_REMOTE_WAKE_RETRIES),
            ): vol.All(int, vol.Range(min=1, max=10)),
            vol.Optional(
                "remote_wake_delay_secs",
                default=options.get("remote_wake_delay_secs", DEFAULT_REMOTE_WAKE_DELAY_SECONDS),
            ): vol.All(int, vol.Range(min=1, max=30)),
            vol.Optional(
                "wol_retries",
                default=options.get("wol_retries", DEFAULT_WOL_RETRIES),
            ): vol.All(int, vol.Range(min=1, max=5)),
            vol.Optional(
                "wol_delay_secs",
                default=options.get("wol_delay_secs", DEFAULT_WOL_DELAY_SECONDS),
            ): vol.All(int, vol.Range(min=1, max=30)),
            vol.Optional(
                "wol_broadcast",
                default=options.get("wol_broadcast", DEFAULT_WOL_BROADCAST),
            ): str,
            vol.Optional(
                "startup_grace_secs",
                default=options.get("startup_grace_secs", DEFAULT_WAKE_STARTUP_GRACE_SECONDS),
            ): vol.All(int, vol.Range(min=0, max=300)),
            vol.Optional("input_mode", default=options.get("input_mode", INPUT_MODE_HDMI1)): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["none", "hdmi1", "hdmi2", "hdmi3", "last_used"],
                    translation_key="input_mode",
                )
            ),
            vol.Optional(
                "base_pairing_name",
                default=options.get("base_pairing_name", DEFAULT_BASE_PAIRING_NAME),
            ): str,
            vol.Optional("wol_enabled", default=options.get("wol_enabled", False)): bool,
            vol.Optional(
                "override_minutes",
                default=options.get("override_minutes", DEFAULT_OVERRIDE_MINUTES),
            ): vol.All(int, vol.Range(min=0, max=1440)),
            vol.Optional(
                "resync_interval_minutes",
                default=options.get("resync_interval_minutes", DEFAULT_RESYNC_INTERVAL_MINUTES),
            ): vol.All(int, vol.Range(min=0, max=1440)),
            vol.Optional(
                "max_drift_corrections_per_hour",
                default=options.get("max_drift_corrections_per_hour", DEFAULT_MAX_DRIFT_CORRECTIONS_PER_HOUR),
            ): vol.All(int, vol.Range(min=1, max=60)),
            vol.Optional(
                "drift_correction_cooldown_minutes",
                default=options.get("drift_correction_cooldown_minutes", DEFAULT_DRIFT_CORRECTION_COOLDOWN_MINUTES),
            ): vol.All(int, vol.Range(min=0, max=60)),
            vol.Optional(
                "max_commands_per_5min",
                default=options.get("max_commands_per_5min", DEFAULT_MAX_COMMANDS_PER_5MIN),
            ): vol.All(int, vol.Range(min=1, max=100)),
            vol.Optional(
                "breaker_cooldown_minutes",
                default=options.get("breaker_cooldown_minutes", DEFAULT_BREAKER_COOLDOWN_MINUTES),
            ): vol.All(int, vol.Range(min=1, max=60)),
            vol.Optional(
                "startup_grace_seconds",
                default=options.get("startup_grace_seconds", DEFAULT_STARTUP_GRACE_SECONDS),
            ): vol.All(int, vol.Range(min=0, max=600)),
            vol.Optional("dry_run", default=options.get("dry_run", False)): bool,
        })
        
        return schema

