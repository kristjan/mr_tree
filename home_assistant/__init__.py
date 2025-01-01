"""The Mr Tree integration."""
from __future__ import annotations

import logging
import voluptuous as vol

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, DEFAULT_HOST, DEFAULT_PORT

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LIGHT]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_HOST, default=DEFAULT_HOST): cv.string,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Mr Tree component."""
    if DOMAIN not in config:
        return True

    hass.data[DOMAIN] = config[DOMAIN]

    await hass.helpers.discovery.async_load_platform("light", DOMAIN, {}, config)

    return True