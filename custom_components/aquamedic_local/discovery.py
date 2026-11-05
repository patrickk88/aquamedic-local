"""Network discovery: offers new pumps under "Discovered" and follows IP changes of known ones.

Runs when Home Assistant has started, every 10 minutes, and shortly after a pump lost its
connection. A known pump found at a new address updates its config entry (and reloads it)
through the config flow's unique-id check, so a changed DHCP address heals itself.
"""
from __future__ import annotations

import logging
import time

from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY
from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery_flow

from . import protocol as pr
from .client import async_discover
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
MIN_GAP_SECONDS = 60
_LAST_RUN = "discovery_last_run"


async def async_run_discovery(hass: HomeAssistant, force: bool = False) -> None:
    store = hass.data.setdefault(DOMAIN, {})
    now = time.monotonic()
    if not force and now - store.get(_LAST_RUN, -MIN_GAP_SECONDS) < MIN_GAP_SECONDS:
        return
    store[_LAST_RUN] = now
    try:
        devices = await async_discover(timeout=3.0)
    except OSError as err:
        _LOGGER.debug("discovery failed: %s", err)
        return
    for dev in devices:
        if pr.schema_for(dev.get("product_key", "")) is None:
            continue
        discovery_flow.async_create_flow(
            hass, DOMAIN, context={"source": SOURCE_INTEGRATION_DISCOVERY}, data=dev
        )
