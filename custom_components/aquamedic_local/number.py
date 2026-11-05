"""Numbers: flow, frequency, feed time (EcoDrift); speed, feed time (DC Runner)."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PumpConfigEntry
from . import protocol as pr
from .entity import PumpEntity


@dataclass(frozen=True, kw_only=True)
class PumpNumberDescription(NumberEntityDescription):
    products: tuple[str, ...] = (pr.PRODUCT_ECODRIFT,)  # DC Runner: read only, see sensor.py


NUMBERS = (
    PumpNumberDescription(
        key="flow", translation_key="flow", icon="mdi:waves-arrow-right", native_min_value=0, native_max_value=100,
        native_step=1, native_unit_of_measurement=PERCENTAGE, mode=NumberMode.SLIDER, products=(pr.PRODUCT_ECODRIFT,),
    ),
    PumpNumberDescription(
        key="frequency", translation_key="frequency", icon="mdi:metronome", native_min_value=0, native_max_value=100,
        native_step=1, native_unit_of_measurement=PERCENTAGE, mode=NumberMode.SLIDER, products=(pr.PRODUCT_ECODRIFT,),
    ),
    PumpNumberDescription(
        key="feed_time", translation_key="feed_time", icon="mdi:timer-sand", native_min_value=1, native_max_value=60,
        native_step=1, native_unit_of_measurement=UnitOfTime.MINUTES, mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: PumpConfigEntry, add: AddEntitiesCallback) -> None:
    c = entry.runtime_data
    add(PumpNumber(c, d) for d in NUMBERS if c.product_key in d.products)


class PumpNumber(PumpEntity, NumberEntity):
    entity_description: PumpNumberDescription

    def __init__(self, coordinator, description: PumpNumberDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        v = self.data.get(self._key)
        return None if v is None else float(v)

    async def async_set_native_value(self, value: float) -> None:
        await self.write(**{self._key: int(round(value))})
