"""Platform for Mr Tree light integration."""
from __future__ import annotations
import logging
import aiohttp
import async_timeout

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ATTR_EFFECT,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from . import const

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the Mr Tree Light platform."""
    host = config.get(CONF_HOST, const.DEFAULT_HOST)
    port = config.get(CONF_PORT, const.DEFAULT_PORT)

    try:
        tree = MrTreeLight(host, port)
        await tree.async_update()
        add_entities([tree], True)
    except Exception as err:
        _LOGGER.error("Failed to connect to Mr Tree: %s", err)

class MrTreeLight(LightEntity):
    """Representation of a Mr Tree Light."""

    def __init__(self, host: str, port: int) -> None:
        """Initialize the light."""
        self._host = host
        self._port = port
        self._session = None
        self._attr_unique_id = f"mr_tree_{host}"
        self._attr_name = "Mr Tree"
        self._attr_supported_color_modes = {ColorMode.RGB}
        self._attr_color_mode = ColorMode.RGB
        self._attr_supported_features = LightEntityFeature.EFFECT

        self._attr_is_on = False
        self._attr_brightness = 255
        self._attr_rgb_color = (255, 255, 255)
        self._attr_effect = None
        self._attr_effect_list = []

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        self._session = aiohttp.ClientSession()

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        if self._session:
            await self._session.close()
            self._session = None

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._attr_is_on

    @property
    def brightness(self) -> int:
        """Return the brightness of this light between 0..255."""
        return self._attr_brightness

    @property
    def rgb_color(self) -> tuple[int, int, int]:
        """Return the rgb color value [int, int, int]."""
        return self._attr_rgb_color

    @property
    def effect(self) -> str | None:
        """Return the current effect."""
        return self._attr_effect

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the light on."""
        url = f"http://{self._host}:{self._port}/on"

        if ATTR_EFFECT in kwargs:
            effect = kwargs[ATTR_EFFECT]
            if effect in self._attr_effect_list:
                self._attr_effect = effect
                url = f"http://{self._host}:{self._port}/effect/{effect}"

        if ATTR_RGB_COLOR in kwargs:
            self._attr_rgb_color = kwargs[ATTR_RGB_COLOR]
            rgb_hex = "%02x%02x%02x" % self._attr_rgb_color
            url = f"http://{self._host}:{self._port}/color/{rgb_hex}"

        if ATTR_BRIGHTNESS in kwargs:
            self._attr_brightness = kwargs[ATTR_BRIGHTNESS]
            # Convert from HA's 0-255 to Tree's 0-100
            brightness_percent = round((kwargs[ATTR_BRIGHTNESS] / 255) * 100)
            url = f"http://{self._host}:{self._port}/brightness/{brightness_percent}"

        try:
            async with async_timeout.timeout(10):
                async with self._session.get(url) as response:
                    if response.status == 200:
                        self._attr_is_on = True
        except Exception as err:
            _LOGGER.error("Failed to turn on: %s", err)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the light off."""
        url = f"http://{self._host}:{self._port}/off"
        try:
            async with async_timeout.timeout(10):
                async with self._session.get(url) as response:
                    if response.status == 200:
                        self._attr_is_on = False
        except Exception as err:
            _LOGGER.error("Failed to turn off: %s", err)

    async def async_update(self) -> None:
        """Fetch new state data for this light."""
        url = f"http://{self._host}:{self._port}/state"
        try:
            async with async_timeout.timeout(10):
                async with self._session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        self._attr_is_on = data["on"]
                        # Convert brightness from 0-100 to 0-255
                        self._attr_brightness = round((data["brightness"] / 100) * 255)
                        color = data["color"]
                        self._attr_rgb_color = (color["red"], color["green"], color["blue"])
                        self._attr_effect = data.get("effect")
                        self._attr_effect_list = data.get("available_effects", [])
        except Exception as err:
            _LOGGER.error("Failed to update: %s", err)