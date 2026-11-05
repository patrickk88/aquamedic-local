"""Switches: pump on/off, feed pause, timer."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PumpConfigEntry
from . import protocol as pr
from .entity import PumpEntity


@dataclass(frozen=True, kw_only=True)
class PumpSwitchDescription(SwitchEntityDescription):
    attrs: tuple[str, ...] = ()


SWITCHES = (
    PumpSwitchDescription(key="power", translation_key="power", icon="mdi:pump"),
    PumpSwitchDescription(key="feed", translation_key="feed", icon="mdi:fish", attrs=("feed_time", "feed_end")),
    PumpSwitchDescription(key="timer", translation_key="timer", icon="mdi:timer-outline", attrs=("auto_mode", "schedule")),
)


async def async_setup_entry(hass: HomeAssistant, entry: PumpConfigEntry, add: AddEntitiesCallback) -> None:
    c = entry.runtime_data
    if c.product_key in pr.WRITE_MAP:  # read-only products (DC Runner) get binary sensors instead
        add(PumpSwitch(c, d) for d in SWITCHES)


class PumpSwitch(PumpEntity, SwitchEntity):
    entity_description: PumpSwitchDescription

    def __init__(self, coordinator, description: PumpSwitchDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        v = self.data.get(self._key)
        return None if v is None else bool(v)

    @property
    def extra_state_attributes(self) -> dict | None:
        return {k: self.data[k] for k in self.entity_description.attrs if k in self.data} or None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.write(**{self._key: True})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.write(**{self._key: False})
