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
    CONF_ATV_CREDENTIALS,
    CONF_ATV_HOST,
    CONF_ATV_IDENTIFIER,
    CONF_ATV_PAIRED_PROTOCOL,
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
    DEFAULT_MOTION_DETECTION_GRACE_MINUTES,
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
    try:
        from pyatv.exceptions import AuthenticationError, NotPairedError, PairingError
    except ImportError:
        # Some pyatv versions may not have these specific exceptions
        AuthenticationError = Exception  # type: ignore[assignment, misc]
        NotPairedError = Exception  # type: ignore[assignment, misc]
        PairingError = Exception  # type: ignore[assignment, misc]
    PYATV_AVAILABLE = True
    _LOGGER.debug("pyatv successfully imported")
except ImportError as import_err:
    scan = None
    pair = None
    connect = None
    Protocol = None  # type: ignore[assignment, misc]
    AuthenticationError = Exception  # type: ignore[assignment, misc]
    NotPairedError = Exception  # type: ignore[assignment, misc]
    PairingError = Exception  # type: ignore[assignment, misc]
    PYATV_AVAILABLE = False
    _LOGGER.warning("pyatv not available: %s. Apple TV pairing will be skipped. Install pyatv to enable Apple TV support.", import_err)


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
        self._pairing_config = None
        self._pairing_pin_requested = False

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
        """Pair with Apple TV using Companion protocol only."""
        if not PYATV_AVAILABLE or Protocol is None:
            _LOGGER.warning("pyatv unavailable; skipping Apple TV pairing")
            return await self.async_step_options()

        apple_tv_host = self.data.get("apple_tv_host")
        apple_tv_identifier = self.data.get("apple_tv_identifier")

        if not apple_tv_host and not apple_tv_identifier:
            _LOGGER.warning("No Apple TV host or identifier provided; skipping pairing")
            return await self.async_step_options()

        config = self._pairing_config or await self._get_atv_config()
        if config is None:
            _LOGGER.warning("Could not find Apple TV for pairing (host=%s identifier=%s)", apple_tv_host, apple_tv_identifier)
            # Allow user to proceed even if discovery fails. This avoids a dead-end
            # loop where the form can never be submitted successfully.
            if user_input is not None:
                _LOGGER.warning(
                    "Proceeding without Apple TV pairing because the device could not be discovered. "
                    "Apple TV features (Companion push updates) will be unavailable until pairing succeeds."
                )
                return await self.async_step_options()
            description_placeholders = {
                "instructions": "On Apple TV: Settings → Remotes and Devices → Remote App and Devices. Approve the request. "
                "If a PIN appears, enter it below; otherwise just continue.",
                "pin": "Check your Apple TV screen",
            }
            return self.async_show_form(
                step_id="pair_apple_tv",
                data_schema=vol.Schema({}),
                description_placeholders=description_placeholders,
                errors={"base": "not_found"},
            )

        # Persist resolved host/identifier
        self.data["apple_tv_host"] = str(config.address)
        if getattr(config, "identifier", None):
            self.data["apple_tv_identifier"] = str(config.identifier)

        if user_input is None:
            already_paired = await self._is_companion_paired(config)
            if already_paired:
                _LOGGER.info("Apple TV already paired for Companion; continuing setup")
                return await self.async_step_options()

            try:
                pin = await self._start_companion_pairing(config)
            except PairingError as err:
                _LOGGER.warning("Unable to start Companion pairing: %s", err)
                description_placeholders = {
                    "instructions": "On Apple TV: Settings → Remotes and Devices → Remote App and Devices. Approve the request. "
                    "If a PIN appears, enter it below; otherwise just continue.",
                    "pin": "Check your Apple TV screen",
                }
                return self.async_show_form(
                    step_id="pair_apple_tv",
                    data_schema=vol.Schema({}),
                    description_placeholders=description_placeholders,
                    errors={"base": "pairing_failed"},
                )

            schema = vol.Schema({}) if pin is None else vol.Schema({vol.Required("pin"): str})
            description_placeholders = {
                "instructions": "On Apple TV: Settings → Remotes and Devices → Remote App and Devices. Approve the request. "
                "If a PIN appears, enter it below; otherwise just continue.",
                "pin": pin or "Check your Apple TV screen",
            }
            return self.async_show_form(
                step_id="pair_apple_tv",
                data_schema=schema,
                description_placeholders=description_placeholders,
                errors={},
            )

        # User continued or provided PIN
        pin = user_input.get("pin") if user_input else None
        if self._pairing_pin_requested and not pin:
            return self.async_show_form(
                step_id="pair_apple_tv",
                data_schema=vol.Schema({vol.Required("pin"): str}),
                errors={"pin": "pin_required"},
            )

        errors: dict[str, str] = {}
        try:
            await self._finish_companion_pairing(config, pin)
            return await self.async_step_options()
        except PairingError as err:
            _LOGGER.warning("Companion pairing failed: %s", err)
            errors["base"] = "pairing_failed"
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Unexpected error finishing pairing: %s", err)
            errors["base"] = "pairing_failed"

        # Restart pairing for retry after a failure
        try:
            pin = await self._start_companion_pairing(config)
        except PairingError:
            pin = None

        schema = vol.Schema({}) if pin is None else vol.Schema({vol.Required("pin"): str})
        description_placeholders = {
            "instructions": "On Apple TV: Settings → Remotes and Devices → Remote App and Devices. Approve the request. "
            "If a PIN appears, enter it below; otherwise just continue.",
            "pin": pin or "Check your Apple TV screen",
        }
        return self.async_show_form(
            step_id="pair_apple_tv",
            data_schema=schema,
            description_placeholders=description_placeholders,
            errors=errors,
        )

    async def _get_atv_config(self):
        """Find Apple TV config by identifier or host."""
        if scan is None:
            return None

        identifier = self.data.get("apple_tv_identifier")
        host = self.data.get("apple_tv_host")
        loop = asyncio.get_running_loop()

        results = None
        try:
            if identifier:
                try:
                    results = await scan(loop=loop, identifier=identifier, timeout=10)
                except TypeError:
                    results = await scan(identifier=identifier, timeout=10)
            elif host:
                try:
                    results = await scan(loop=loop, hosts=[host], timeout=10)
                except TypeError:
                    results = await scan(hosts=[host], timeout=10)
        except Exception as ex:  # noqa: BLE001
            _LOGGER.warning("Apple TV scan failed: %s", ex)
            results = None

        if results:
            return results[0]

        # Fallback: do a network scan and match by identifier OR name OR host.
        # This makes manual entry more forgiving (users often enter the device name
        # in the identifier field, or the IP may change).
        try:
            try:
                results = await scan(loop=loop, timeout=12)
            except TypeError:
                results = await scan(timeout=12)
        except Exception as ex:  # noqa: BLE001
            _LOGGER.warning("Apple TV fallback network scan failed: %s", ex)
            return None

        if not results:
            return None

        identifier_str = str(identifier).strip() if identifier else ""
        identifier_lower = identifier_str.lower()
        host_str = str(host).strip() if host else ""

        def _match(cfg) -> bool:
            try:
                if identifier_str:
                    if str(getattr(cfg, "identifier", "")) == identifier_str:
                        return True
                    if str(getattr(cfg, "name", "")).strip().lower() == identifier_lower:
                        return True
                if host_str and str(getattr(cfg, "address", "")) == host_str:
                    return True
            except Exception:  # noqa: BLE001
                return False
            return False

        matched = [cfg for cfg in results if _match(cfg)]
        if len(matched) == 1:
            return matched[0]
        if len(matched) > 1:
            _LOGGER.warning(
                "Multiple Apple TVs matched identifier/name/host (identifier=%s host=%s); "
                "please select from discovered list.",
                identifier,
                host,
            )
            return matched[0]
        return None

    async def _is_companion_paired(self, config) -> bool:
        """Check if Companion credentials already work."""
        loop = asyncio.get_running_loop()
        try:
            try:
                atv = await connect(config, protocol=Protocol.Companion, loop=loop)
            except TypeError:
                # Fallback for versions that don't accept loop parameter. Do NOT
                # fall back to protocol-less connect, as that can succeed via
                # AirPlay/MRP and produce false positives for Companion pairing.
                atv = await connect(config, protocol=Protocol.Companion)
            try:
                await atv.close()
            except Exception:  # noqa: BLE001
                pass
            return True
        except (AuthenticationError, NotPairedError, PairingError):
            return False
        except Exception as ex:  # noqa: BLE001
            _LOGGER.debug("Companion pairing check failed: %s", ex)
            return False

    async def _start_companion_pairing(self, config):
        """Begin Companion pairing and return PIN if required."""
        self._pairing_config = config
        loop = asyncio.get_running_loop()

        if Protocol is not None and hasattr(config, "protocols") and Protocol.Companion not in config.protocols:
            raise PairingError("companion_not_supported")

        try:
            try:
                self._pairing = await pair(config, Protocol.Companion, loop=loop)
            except TypeError:
                self._pairing = await pair(config, Protocol.Companion)
        except Exception as ex:  # noqa: BLE001
            self._pairing = None
            raise PairingError(str(ex)) from ex

        if not self._pairing:
            raise PairingError("pairing_not_started")

        try:
            pin = await self._pairing.begin()
        except Exception as ex:  # noqa: BLE001
            await self._close_pairing()
            raise PairingError(str(ex)) from ex

        self._pairing_pin_requested = bool(pin)
        return pin

    async def _finish_companion_pairing(self, config, pin: str | None) -> None:
        """Finish Companion pairing handling pyatv API variants."""
        if not self._pairing:
            raise PairingError("pairing_missing")

        try:
            if pin:
                try:
                    await self._pairing.finish(pin)
                except TypeError:
                    if hasattr(self._pairing, "pin"):
                        try:
                            setattr(self._pairing, "pin", pin)
                        except Exception:  # noqa: BLE001
                            pass
                    await self._pairing.finish()
            else:
                try:
                    await self._pairing.finish()
                except TypeError:
                    await self._pairing.finish(None)

            credentials = self._extract_credentials(config)
            self.data[CONF_ATV_CREDENTIALS] = credentials
            self.data[CONF_ATV_PAIRED_PROTOCOL] = "companion"
            self.data[CONF_ATV_HOST] = str(config.address)
            if getattr(config, "identifier", None):
                self.data[CONF_ATV_IDENTIFIER] = str(config.identifier)
        finally:
            await self._close_pairing()

    def _extract_credentials(self, config) -> dict[str, Any] | None:
        """Extract serializable credentials from pyatv config."""
        try:
            creds = getattr(config, "credentials", None)
            if isinstance(creds, dict) and creds:
                normalized: dict[str, Any] = {}
                for key, value in creds.items():
                    if not value:
                        continue
                    name = key.name.lower() if hasattr(key, "name") else str(key).lower()
                    normalized[name] = value
                if normalized:
                    return normalized
        except Exception:  # noqa: BLE001
            pass

        if Protocol is not None:
            try:
                cred = config.get_credentials(Protocol.Companion)
                if cred:
                    return {"companion": str(cred)}
            except Exception:  # noqa: BLE001
                pass
        return None

    async def _close_pairing(self) -> None:
        """Close pairing handler safely."""
        pairing = self._pairing
        self._pairing = None
        self._pairing_config = None
        self._pairing_pin_requested = False
        if pairing:
            try:
                await pairing.close()
            except Exception:  # noqa: BLE001
                pass

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
            CONF_ATV_CREDENTIALS: self.data.get(CONF_ATV_CREDENTIALS),
            CONF_ATV_IDENTIFIER: self.data.get("apple_tv_identifier"),
            CONF_ATV_HOST: self.data.get("apple_tv_host"),
            CONF_ATV_PAIRED_PROTOCOL: self.data.get(CONF_ATV_PAIRED_PROTOCOL, "companion" if self.data.get(CONF_ATV_CREDENTIALS) else None),
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
            "motion_detection_grace_minutes": DEFAULT_MOTION_DETECTION_GRACE_MINUTES,
            "max_commands_per_5min": DEFAULT_MAX_COMMANDS_PER_5MIN,
            "breaker_cooldown_minutes": DEFAULT_BREAKER_COOLDOWN_MINUTES,
            "startup_grace_seconds": DEFAULT_STARTUP_GRACE_SECONDS,
            "dry_run": False,
        }
        
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
                "motion_detection_grace_minutes",
                default=options.get("motion_detection_grace_minutes", DEFAULT_MOTION_DETECTION_GRACE_MINUTES),
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
