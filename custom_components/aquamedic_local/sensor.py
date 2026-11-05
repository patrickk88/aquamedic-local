"""Sensors: current timer mode, schedule, DC Runner control mode and clock."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PumpConfigEntry
from . import protocol as pr
from .entity import PumpEntity


@dataclass(frozen=True, kw_only=True)
class PumpSensorDescription(SensorEntityDescription):
    products: tuple[str, ...] = (pr.PRODUCT_ECODRIFT, pr.PRODUCT_DC_RUNNER)
    value_fn: Callable[[dict], Any] = lambda d: None
    attrs: tuple[str, ...] = ()


SENSORS = (
    PumpSensorDescription(
        key="auto_mode", translation_key="auto_mode", icon="mdi:calendar-clock", device_class=SensorDeviceClass.ENUM,
        options=list(pr.AUTO_MODES), value_fn=lambda d: d.get("auto_mode"),
        attrs=("auto_flow", "auto_frequency", "auto_wave_form", "auto_feed_time"), products=(pr.PRODUCT_ECODRIFT,),
    ),
    PumpSensorDescription(
        key="auto_mode", translation_key="auto_mode", icon="mdi:calendar-clock", device_class=SensorDeviceClass.ENUM,
        options=list(pr.DC_AUTO_MODES), value_fn=lambda d: d.get("auto_mode"),
        attrs=("auto_speed", "auto_feed_time"), products=(pr.PRODUCT_DC_RUNNER,),
    ),
    PumpSensorDescription(
        key="feed_end", translation_key="feed_end", icon="mdi:timer-sand", device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.get("feed_end"),
    ),
    PumpSensorDescription(
        key="schedule", translation_key="schedule", icon="mdi:calendar-multiselect",
        value_fn=lambda d: len(d.get("schedule", [])), attrs=("schedule",), entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PumpSensorDescription(
        key="speed", translation_key="speed", icon="mdi:speedometer", native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda d: d.get("speed"), products=(pr.PRODUCT_DC_RUNNER,),
    ),
    PumpSensorDescription(
        key="feed_time", translation_key="feed_time", icon="mdi:timer-sand", native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda d: d.get("feed_time"), products=(pr.PRODUCT_DC_RUNNER,),
    ),
    PumpSensorDescription(
        key="control", translation_key="control", icon="mdi:remote", device_class=SensorDeviceClass.ENUM,
        options=list(pr.DC_CONTROL), value_fn=lambda d: d.get("control"),
        entity_category=EntityCategory.DIAGNOSTIC, products=(pr.PRODUCT_DC_RUNNER,),
    ),
    PumpSensorDescription(
        key="device_time", translation_key="device_time", icon="mdi:clock-outline",
        value_fn=lambda d: d.get("device_time"), attrs=("device_date",),
        entity_category=EntityCategory.DIAGNOSTIC, entity_registry_enabled_default=False, products=(pr.PRODUCT_DC_RUNNER,),
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: PumpConfigEntry, add: AddEntitiesCallback) -> None:
    c = entry.runtime_data
    add(PumpSensor(c, d) for d in SENSORS if c.product_key in d.products)


class PumpSensor(PumpEntity, SensorEntity):
    entity_description: PumpSensorDescription

    def __init__(self, coordinator, description: PumpSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        v = self.entity_description.value_fn(self.data)
        if self.entity_description.options and v not in self.entity_description.options:
            return None
        return v

    @property
    def extra_state_attributes(self) -> dict | None:
        return {k: self.data[k] for k in self.entity_description.attrs if k in self.data} or None
