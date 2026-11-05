"""Binary sensors: any fault (problem) plus the seven individual fault flags."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PumpConfigEntry
from . import protocol as pr
from .entity import PumpEntity

FAULT = BinarySensorEntityDescription(key="fault", translation_key="fault", device_class=BinarySensorDeviceClass.PROBLEM)
FAULTS = tuple(
    BinarySensorEntityDescription(
        key=f"fault_{name}", translation_key=f"fault_{name}", device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC, entity_registry_enabled_default=False,
    )
    for name in pr.FAULT_KEYS.values()
)


# read-only products (DC Runner): what the EcoDrift exposes as switches
STATE_FLAGS = (
    BinarySensorEntityDescription(key="power", translation_key="power", device_class=BinarySensorDeviceClass.RUNNING),
    BinarySensorEntityDescription(key="feed", translation_key="feed", icon="mdi:fish"),
    BinarySensorEntityDescription(key="timer", translation_key="timer", icon="mdi:timer-outline"),
)


async def async_setup_entry(hass: HomeAssistant, entry: PumpConfigEntry, add: AddEntitiesCallback) -> None:
    c = entry.runtime_data
    ents: list[BinarySensorEntity] = [PumpFault(c), *(PumpFaultFlag(c, d) for d in FAULTS)]
    if c.product_key not in pr.WRITE_MAP:
        ents += [PumpStateFlag(c, d) for d in STATE_FLAGS]
    add(ents)


class PumpStateFlag(PumpEntity, BinarySensorEntity):
    def __init__(self, coordinator, description: BinarySensorEntityDescription) -> None:
        super().__init__(coordinator, f"state_{description.key}")
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        v = self.data.get(self.entity_description.key)
        return None if v is None else bool(v)


class PumpFault(PumpEntity, BinarySensorEntity):
    entity_description = FAULT

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, FAULT.key)

    @property
    def is_on(self) -> bool | None:
        return self.data.get("fault_active")

    @property
    def extra_state_attributes(self) -> dict | None:
        return {"faults": self.data.get("fault_list", [])}


class PumpFaultFlag(PumpEntity, BinarySensorEntity):
    def __init__(self, coordinator, description: BinarySensorEntityDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._fault = description.key.removeprefix("fault_")

    @property
    def is_on(self) -> bool | None:
        return self.data.get("faults", {}).get(self._fault)
