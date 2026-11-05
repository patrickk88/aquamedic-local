"""Push coordinator: the client delivers status blocks, entities listen."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .client import PumpClient
from .const import CONF_DID, CONF_PASSCODE, CONF_PRODUCT_KEY, DOMAIN
from .discovery import async_run_discovery

_LOGGER = logging.getLogger(__name__)
REDISCOVER_AFTER = 45  # seconds without connection before looking for the pump on the network


class PumpCoordinator(DataUpdateCoordinator[dict]):
    """Latest decoded values of one pump."""

    client: PumpClient

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=f"{DOMAIN} {entry.data[CONF_DID]}", update_interval=None)
        self.did: str = entry.data[CONF_DID]
        self.product_key: str = entry.data[CONF_PRODUCT_KEY]
        self.device_name: str = entry.title
        self.firmware: str | None = None
        self._rediscover: asyncio.Task | None = None

    @callback
    def handle_data(self, data: dict) -> None:
        prev = self.data or {}
        feed_end = prev.get("feed_end")
        if not data.get("feed"):
            feed_end = None
        elif not prev.get("feed"):
            # pause just started (seen live) -> it ends after the pump's own feed time;
            # on the very first status after a start the begin is unknown
            feed_end = (
                dt_util.utcnow() + timedelta(minutes=int(data.get("feed_time") or 0)) if prev else None
            )
        self.async_set_updated_data({**data, "feed_end": feed_end})

    @callback
    def handle_connection(self, connected: bool) -> None:
        if connected:
            self.cancel_rediscovery()
            if self.config_entry is not None and self.client.passcode != self.config_entry.data.get(CONF_PASSCODE):
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data={**self.config_entry.data, CONF_PASSCODE: self.client.passcode}
                )
        elif self._rediscover is None or self._rediscover.done():
            self._rediscover = self.hass.async_create_background_task(
                self._look_for_pump(), f"{DOMAIN} rediscover {self.did}"
            )
        self.async_update_listeners()

    async def _look_for_pump(self) -> None:
        """Still offline after a while -> search the network (the pump may have a new address)."""
        await asyncio.sleep(REDISCOVER_AFTER)
        if not self.client.connected:
            await async_run_discovery(self.hass)

    @callback
    def cancel_rediscovery(self) -> None:
        if self._rediscover is not None and not self._rediscover.done():
            self._rediscover.cancel()
        self._rediscover = None

    @callback
    def handle_info(self, info: dict) -> None:
        fw = info.get("firmware")
        if not fw or self.config_entry is None or fw == self.firmware:
            return
        self.firmware = fw
        reg = dr.async_get(self.hass)
        for device in dr.async_entries_for_config_entry(reg, self.config_entry.entry_id):
            if (DOMAIN, self.did) in device.identifiers and device.sw_version != fw:
                reg.async_update_device(device.id, sw_version=fw)

    @property
    def fresh(self) -> bool:
        # the pump only pushes on change, so "connected" (heartbeat answered) is the freshness test
        return self.client.connected and self.data is not None

    async def async_write(self, **values) -> None:
        await self.client.async_write(values)
