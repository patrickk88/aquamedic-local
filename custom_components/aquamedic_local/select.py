"""Selects: wave mode, wave form (pulse/tide), linkage - EcoDrift / SmartDrift only."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PumpConfigEntry
from . import protocol as pr
from .entity import PumpEntity


@dataclass(frozen=True, kw_only=True)
class PumpSelectDescription(SelectEntityDescription):
    products: tuple[str, ...] = (pr.PRODUCT_ECODRIFT,)


SELECTS = (
    PumpSelectDescription(key="mode", translation_key="mode", icon="mdi:waves", options=list(pr.WAVE_MODES)),
    PumpSelectDescription(key="wave_form", translation_key="wave_form", icon="mdi:sine-wave", options=list(pr.WAVE_FORMS)),
    PumpSelectDescription(
        key="linkage", translation_key="linkage", icon="mdi:link-variant", options=list(pr.LINKAGE),
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: PumpConfigEntry, add: AddEntitiesCallback) -> None:
    c = entry.runtime_data
    add(PumpSelect(c, d) for d in SELECTS if c.product_key in d.products)


class PumpSelect(PumpEntity, SelectEntity):
    entity_description: PumpSelectDescription

    def __init__(self, coordinator, description: PumpSelectDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def current_option(self) -> str | None:
        v = self.data.get(self._key)
        return v if isinstance(v, str) and v in self.options else None

    async def async_select_option(self, option: str) -> None:
        await self.write(**{self._key: option})
