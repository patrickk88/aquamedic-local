"""Push coordinator: the client delivers status blocks, entities listen."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .client import PumpClient
from .const import CONF_DID, CONF_PASSCODE, CONF_PRODUCT_KEY, DOMAIN

_LOGGER = logging.getLogger(__name__)


class PumpCoordinator(DataUpdateCoordinator[dict]):
    """Latest decoded values of one pump."""

    client: PumpClient

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=f"{DOMAIN} {entry.data[CONF_DID]}", update_interval=None)
        self.did: str = entry.data[CONF_DID]
        self.product_key: str = entry.data[CONF_PRODUCT_KEY]
        self.device_name: str = entry.title
        self.firmware: str | None = None

    @callback
    def handle_data(self, data: dict) -> None:
        self.async_set_updated_data(data)

    @callback
    def handle_connection(self, connected: bool) -> None:
        if connected and self.config_entry is not None and self.client.passcode != self.config_entry.data.get(CONF_PASSCODE):
            self.hass.config_entries.async_update_entry(
                self.config_entry, data={**self.config_entry.data, CONF_PASSCODE: self.client.passcode}
            )
        self.async_update_listeners()

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
