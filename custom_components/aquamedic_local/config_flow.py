"""Config flow: find pumps on the LAN or enter an address; the passcode is fetched from the pump."""
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


class AquaMedicConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._found: dict[str, dict] = {}

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
        self._found = {h: d for h, d in self._found.items() if d["did"] not in known}
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
            host = user_input[CONF_HOST].strip()
            result = await self._finish({"host": host}, errors)
            if result is not None:
                return result
        schema = vol.Schema({vol.Required(CONF_HOST, default=(user_input or {}).get(CONF_HOST, "")): str})
        return self.async_show_form(step_id="manual", data_schema=schema, errors=errors)

    async def _finish(self, found: dict, errors: dict[str, str]) -> ConfigFlowResult | None:
        host = found["host"]
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
        product_key = info["product_key"] or found.get("product_key", "")
        if pr.schema_for(product_key) is None:
            _LOGGER.warning("%s: unsupported Gizwits product %s", host, product_key)
            errors["base"] = "unsupported"
            return None
        did = found.get("did")
        if not did:
            # manual entry: ask the pump itself over UDP for its id
            for d in await async_discover(timeout=2.0, target=host):
                if d["host"] == host:
                    found = {**d, **found}
                    did = d["did"]
            if not did:
                did = f"{product_key[:8]}-{host}"
        await self.async_set_unique_id(did)
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
