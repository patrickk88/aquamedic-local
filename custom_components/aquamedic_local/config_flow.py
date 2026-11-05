"""Config flow: pumps found on the LAN (list or "Discovered"), manual address, reconfigure.

The passcode is fetched from the pump itself; the Gizwits device id is the unique id, so a
pump that shows up at a new address updates its existing entry instead of becoming a new one.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.helpers.selector import SelectOptionDict, SelectSelector, SelectSelectorConfig

from . import protocol as pr
from .client import NeedsBinding, PumpError, async_discover, async_probe
from .const import CONF_DID, CONF_MAC, CONF_PASSCODE, CONF_PRODUCT_KEY, DOMAIN

_LOGGER = logging.getLogger(__name__)
MANUAL = "manual"


def _default_name(product_key: str, mac: str | None) -> str:
    base = pr.MODEL_NAME.get(product_key, "Aqua Medic pump").split(" / ")[0]
    return f"{base} {mac.replace(':', '')[-4:].upper()}" if mac else base


async def _identify(host: str, errors: dict[str, str]) -> tuple[dict, dict] | None:
    """Log in once (passcode, module info, status) and ask the pump for its id over UDP."""
    try:
        info = await async_probe(host)
    except NeedsBinding:
        errors["base"] = "needs_binding"
        return None
    except PumpError:
        errors["base"] = "login_failed"
        return None
    except (OSError, TimeoutError):
        errors["base"] = "cannot_connect"
        return None
    if pr.schema_for(info["product_key"]) is None:
        _LOGGER.warning("%s: unsupported Gizwits product %s", host, info["product_key"])
        errors["base"] = "unsupported"
        return None
    found: dict = {}
    try:
        for dev in await async_discover(timeout=2.0, target=host):
            if dev["host"] == host:
                found = dev
    except OSError:
        pass
    return info, found


class AquaMedicConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._found: dict[str, dict] = {}
        self._discovered: dict | None = None

    # --- user: list of pumps found now, or manual address -------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            choice = user_input["pump"]
            if choice == MANUAL:
                return await self.async_step_manual()
            return await self._finish(self._found[choice], errors) or self._show_user(errors)
        try:
            self._found = {d["host"]: d for d in await async_discover()}
        except OSError as err:
            _LOGGER.debug("discovery failed: %s", err)
            self._found = {}
        known = {e.unique_id for e in self._async_current_entries()}
        self._found = {
            h: d for h, d in self._found.items() if d["did"] not in known and pr.schema_for(d["product_key"])
        }
        if not self._found:
            return await self.async_step_manual()
        return self._show_user(errors)

    def _show_user(self, errors: dict[str, str]) -> ConfigFlowResult:
        options = [
            SelectOptionDict(value=host, label=f"{pr.MODEL_NAME.get(d['product_key'], d['product_key'][:8])} - {host} ({d['mac']})")
            for host, d in sorted(self._found.items())
        ]
        options.append(SelectOptionDict(value=MANUAL, label="manual"))
        schema = vol.Schema({vol.Required("pump"): SelectSelector(SelectSelectorConfig(options=options, translation_key="pump"))})
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            result = await self._finish({"host": user_input[CONF_HOST].strip()}, errors)
            if result is not None:
                return result
        schema = vol.Schema({vol.Required(CONF_HOST, default=(user_input or {}).get(CONF_HOST, "")): str})
        return self.async_show_form(step_id="manual", data_schema=schema, errors=errors)

    # --- discovery (background search, see discovery.py) ---------------------------------

    async def async_step_integration_discovery(self, discovery_info: dict[str, Any]) -> ConfigFlowResult:
        did, host = discovery_info.get("did"), discovery_info.get("host")
        if not did or not host or pr.schema_for(discovery_info.get("product_key", "")) is None:
            return self.async_abort(reason="unsupported")
        await self.async_set_unique_id(did)
        # known pump at a new address -> update and reload its entry, nothing to confirm
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        self._discovered = discovery_info
        self.context["title_placeholders"] = {
            "name": _default_name(discovery_info["product_key"], discovery_info.get("mac")),
            "host": host,
        }
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._discovered is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            result = await self._finish(self._discovered, errors)
            if result is not None:
                return result
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders=dict(self.context["title_placeholders"]),
            errors=errors,
        )

    # --- reconfigure: new address by hand ------------------------------------------------

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            res = await _identify(host, errors)
            if res is not None:
                info, found = res
                same = found.get("did") == entry.unique_id if found.get("did") else info["product_key"] == entry.data[CONF_PRODUCT_KEY]
                if not same:
                    errors["base"] = "wrong_device"
                else:
                    return self.async_update_reload_and_abort(
                        entry, data_updates={CONF_HOST: host, CONF_PASSCODE: info["passcode"]}
                    )
        schema = vol.Schema({vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str})
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors, description_placeholders={"name": entry.title}
        )

    # --- shared -------------------------------------------------------------------------------

    async def _finish(self, found: dict, errors: dict[str, str]) -> ConfigFlowResult | None:
        host = found["host"]
        res = await _identify(host, errors)
        if res is None:
            return None
        info, disc = res
        found = {**disc, **found}
        product_key = info["product_key"]
        did = found.get("did") or f"{product_key[:8]}-{host}"
        await self.async_set_unique_id(did, raise_on_progress=False)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        name = _default_name(product_key, found.get("mac"))
        return self.async_create_entry(
            title=name,
            data={
                CONF_HOST: host,
                CONF_NAME: name,
                CONF_DID: did,
                CONF_MAC: found.get("mac"),
                CONF_PRODUCT_KEY: product_key,
                CONF_PASSCODE: info["passcode"],
            },
        )
