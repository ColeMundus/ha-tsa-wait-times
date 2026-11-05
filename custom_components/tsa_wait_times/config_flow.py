"""Single-airport setup and polling options."""

from typing import Any

import probatio as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import get_feed
from .client import FeedError
from .const import CONF_AIRPORT, CONF_INTERVAL, DEFAULT_INTERVAL, DOMAIN


def interval(value: Any) -> int:
    """Accept whole minutes, never booleans or numeric strings."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 1 <= value <= 1440
        or int(value) != value
    ):
        raise vol.Invalid("Use whole minutes from 1 to 1440")
    return int(value)


class MinuteSelector(selector.NumberSelector):
    """Serialize as a native number selector with strict minute validation."""

    def __call__(self, data: Any) -> float:
        return interval(data)


def schema(default: int, *, airport: bool = False) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if airport:
        fields[vol.Required(CONF_AIRPORT, default="PDX")] = selector.SelectSelector(
            selector.SelectSelectorConfig(options=["PDX"])
        )
    fields[vol.Required(CONF_INTERVAL, default=default)] = MinuteSelector(
        selector.NumberSelectorConfig(
            min=1,
            max=1440,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="min",
        )
    )
    return vol.Schema(fields)


class TSAFlow(ConfigFlow, domain=DOMAIN):
    """Validate the anonymous feed before creating one PDX entry."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> OptionsFlow:
        return TSAOptions()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            try:
                user_input = schema(DEFAULT_INTERVAL, airport=True)(user_input)
            except vol.Invalid:
                return self.async_show_form(
                    step_id="user",
                    data_schema=schema(DEFAULT_INTERVAL, airport=True),
                    errors={"base": "invalid_input"},
                )
            await self.async_set_unique_id("PDX")
            self._abort_if_unique_id_configured()
            try:
                await get_feed(self.hass).fetch()
            except FeedError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title="TSA Wait Times PDX", data=user_input
                )
        return self.async_show_form(
            step_id="user",
            data_schema=schema(DEFAULT_INTERVAL, airport=True),
            errors=errors,
        )


class TSAOptions(OptionsFlow):
    """Change polling without changing source identity."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            try:
                validated: dict[str, Any] = schema(DEFAULT_INTERVAL)(user_input)
            except vol.Invalid:
                return self.async_show_form(
                    step_id="init",
                    data_schema=schema(DEFAULT_INTERVAL),
                    errors={"base": "invalid_input"},
                )
            return self.async_create_entry(title="", data=validated)
        default = self.config_entry.options.get(
            CONF_INTERVAL, self.config_entry.data.get(CONF_INTERVAL, DEFAULT_INTERVAL)
        )
        return self.async_show_form(step_id="init", data_schema=schema(default))
