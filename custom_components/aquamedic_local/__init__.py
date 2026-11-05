"""Aqua Medic Local (unofficial): LAN control of Aqua Medic EcoDrift / SmartDrift / DC Runner pumps."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType

from .client import PumpClient
from .const import CONF_PASSCODE, CONF_PRODUCT_KEY, DOMAIN
from .coordinator import PumpCoordinator
from .discovery import async_run_discovery

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH, Platform.SELECT, Platform.NUMBER]
DISCOVERY_INTERVAL = timedelta(minutes=10)

type PumpConfigEntry = ConfigEntry[PumpCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def _at_start(hass: HomeAssistant) -> None:
        await async_run_discovery(hass, force=True)

    async def _interval(_now) -> None:
        await async_run_discovery(hass, force=True)

    async_at_started(hass, _at_start)
    async_track_time_interval(hass, _interval, DISCOVERY_INTERVAL, cancel_on_shutdown=True)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PumpConfigEntry) -> bool:
    coordinator = PumpCoordinator(hass, entry)
    coordinator.client = PumpClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PRODUCT_KEY],
        entry.data[CONF_PASSCODE],
        on_data=coordinator.handle_data,
        on_connection=coordinator.handle_connection,
        on_info=coordinator.handle_info,
    )
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(hass, coordinator.client.run(), f"{DOMAIN} {entry.data[CONF_HOST]}")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PumpConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await entry.runtime_data.client.stop()
    entry.runtime_data.cancel_rediscovery()
    return ok
