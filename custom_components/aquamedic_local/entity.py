"""Base entity."""
from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import protocol as pr
from .const import CONF_MAC, DOMAIN, MANUFACTURER
from .coordinator import PumpCoordinator


class PumpEntity(CoordinatorEntity[PumpCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: PumpCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{coordinator.did}_{key}"
        mac = coordinator.config_entry.data.get(CONF_MAC) if coordinator.config_entry else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.did)},
            connections={(CONNECTION_NETWORK_MAC, mac)} if mac else set(),
            manufacturer=MANUFACTURER,
            model=pr.MODEL_NAME.get(coordinator.product_key, "Gizwits pump"),
            name=coordinator.device_name,
            serial_number=coordinator.did,
            sw_version=coordinator.firmware,
        )

    @property
    def available(self) -> bool:
        return self.coordinator.fresh

    @property
    def data(self) -> dict:
        return self.coordinator.data or {}

    async def write(self, **values) -> None:
        try:
            await self.coordinator.async_write(**values)
        except (ConnectionError, pr.ProtocolError) as err:
            raise HomeAssistantError(f"{self.coordinator.device_name}: {err}") from err
