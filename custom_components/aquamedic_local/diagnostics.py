"""Diagnostics download: entry, connection and the last status (decoded and raw). Secrets redacted."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import PumpConfigEntry
from .const import CONF_DID, CONF_MAC, CONF_PASSCODE

TO_REDACT = {CONF_PASSCODE, CONF_MAC, CONF_DID, "passcode", "mac", "did"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: PumpConfigEntry) -> dict[str, Any]:
    c = entry.runtime_data
    client = c.client
    return {
        "entry": {"title": entry.title, "version": entry.version, "data": async_redact_data(dict(entry.data), TO_REDACT)},
        "connected": client.connected,
        "product_key": c.product_key,
        "module_firmware": c.firmware,
        "status": async_redact_data(dict(c.data or {}), TO_REDACT),
        "raw_status_hex": client.last_status.hex() if client.last_status else None,
    }
