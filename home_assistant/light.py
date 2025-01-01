"""Platform for Mr Tree light integration."""
from __future__ import annotations
import logging
import aiohttp
import async_timeout
import asyncio

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
        if not self._session:
            self._session = aiohttp.ClientSession()

        # Build state update
        state = {"on": True}

        if ATTR_EFFECT in kwargs:
            effect = kwargs[ATTR_EFFECT]
            if effect in self._attr_effect_list:
                self._attr_effect = effect
                state["effect"] = effect

        if ATTR_RGB_COLOR in kwargs:
            self._attr_rgb_color = kwargs[ATTR_RGB_COLOR]
            rgb_hex = "%02x%02x%02x" % self._attr_rgb_color
            state["color"] = rgb_hex

        if ATTR_BRIGHTNESS in kwargs:
            self._attr_brightness = kwargs[ATTR_BRIGHTNESS]
            # Convert from HA's 0-255 to Tree's 0-100
            state["brightness"] = round((kwargs[ATTR_BRIGHTNESS] / 255) * 100)

        # Send single request with all updates
        url = f"http://{self._host}:{self._port}/state"
        try:
            async with async_timeout.timeout(10):
                async with self._session.post(url, json=state) as response:
                    if response.status == 200:
                        data = await response.json()
                        self._update_from_state(data)
                    else:
                        _LOGGER.error("Failed to update state: %s", response.status)
        except Exception as err:
            _LOGGER.error("Failed to update state: %s", err)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the light off."""
        if not self._session:
            self._session = aiohttp.ClientSession()

        url = f"http://{self._host}:{self._port}/state"
        try:
            async with async_timeout.timeout(10):
                async with self._session.post(url, json={"on": False}) as response:
                    if response.status == 200:
                        data = await response.json()
                        self._update_from_state(data)
                    else:
                        _LOGGER.error("Failed to turn off: %s", response.status)
        except Exception as err:
            _LOGGER.error("Failed to turn off: %s", err)

    def _update_from_state(self, data: dict) -> None:
        """Update internal state from server response."""
        if not data:
            _LOGGER.error("Empty response from tree")
            return
        self._attr_is_on = data.get("on", False)
        # Convert brightness from 0-100 to 0-255
        self._attr_brightness = round((data.get("brightness", 0) / 100) * 255)
        color = data.get("color", {"red": 255, "green": 255, "blue": 255})
        self._attr_rgb_color = (color.get("red", 0), color.get("green", 0), color.get("blue", 0))
        self._attr_effect = data.get("effect")
        # Filter out timer from available effects
        self._attr_effect_list = [
            effect for effect in data.get("available_effects", [])
            if effect != "timer"
        ]

    async def async_update(self) -> None:
        """Fetch new state data for this light."""
        if not self._session:
            self._session = aiohttp.ClientSession()

        url = f"http://{self._host}:{self._port}/state"
        try:
            async with async_timeout.timeout(10):
                async with self._session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if not data:
                            _LOGGER.error("Empty response from tree")
                            return
                        self._attr_is_on = data.get("on", False)
                        # Convert brightness from 0-100 to 0-255
                        self._attr_brightness = round((data.get("brightness", 0) / 100) * 255)
                        color = data.get("color", {"red": 255, "green": 255, "blue": 255})
                        self._attr_rgb_color = (color.get("red", 0), color.get("green", 0), color.get("blue", 0))
                        self._attr_effect = data.get("effect")
                        # Filter out timer from available effects
                        self._attr_effect_list = [
                            effect for effect in data.get("available_effects", [])
                            if effect != "timer"
                        ]
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout connecting to %s", self._host)
        except aiohttp.ClientError as err:
            _LOGGER.error("Error connecting to %s: %s", self._host, err)
        except Exception as err:
            _LOGGER.error("Failed to update: %s", err)