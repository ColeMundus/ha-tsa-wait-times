"""Live directory airport setup and conservative polling options."""

from typing import Any

import probatio as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import get_feed
from .airports import nearest_airport
from .client import Airport, FeedError
from .const import (
    CONF_AIRPORT,
    CONF_INTERVAL,
    CONF_NAME,
    CONF_PATH,
    DEFAULT_INTERVAL,
    DOMAIN,
)


def interval(value: Any) -> int:
    """Accept whole minutes, never booleans, strings or sub-five-minute values."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 5 <= value <= 1440
        or int(value) != value
    ):
        raise vol.Invalid("Use whole minutes from 5 to 1440")
    return int(value)


class MinuteSelector(selector.NumberSelector):
    """Native numeric selector with strict minute validation."""

    def __call__(self, data: Any) -> float:
        return interval(data)


def schema(
    default: int,
    airports: dict[str, Airport] | None = None,
    airport_default: str | None = None,
) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if airports is not None:
        airport_key = (
            vol.Required(CONF_AIRPORT, default=airport_default)
            if airport_default in airports
            else vol.Required(CONF_AIRPORT)
        )
        fields[airport_key] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(
                        value=code, label=f"{code} — {airport.name}"
                    )
                    for code, airport in sorted(airports.items())
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
    fields[vol.Required(CONF_INTERVAL, default=max(5, default))] = MinuteSelector(
        selector.NumberSelectorConfig(
            min=5,
            max=1440,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="min",
        )
    )
    return vol.Schema(fields)


class TSAFlow(ConfigFlow, domain=DOMAIN):
    """One validated entry per exact live-directory code."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> OptionsFlow:
        return TSAOptions()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors = {}
        try:
            airports = await get_feed(self.hass).airports()
        except FeedError:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({}),
                errors={"base": "cannot_connect"},
            )
        if user_input is not None:
            try:
                user_input = schema(DEFAULT_INTERVAL, airports)(user_input)
            except vol.Invalid:
                errors["base"] = "invalid_input"
            else:
                code = user_input[CONF_AIRPORT]
                await self.async_set_unique_id(code)
                self._abort_if_unique_id_configured()
                try:
                    await get_feed(self.hass).fetch(
                        airports[code], user_input[CONF_INTERVAL]
                    )
                except FeedError:
                    errors["base"] = "cannot_connect"
                else:
                    airport = airports[code]
                    return self.async_create_entry(
                        title=f"TSA Wait Times {code}",
                        data={
                            **user_input,
                            CONF_PATH: airport.path,
                            CONF_NAME: airport.name,
                        },
                    )
        configured = {entry.unique_id for entry in self._async_current_entries()}
        airport_default = (
            user_input.get(CONF_AIRPORT)
            if user_input is not None
            else nearest_airport(
                self.hass.config.latitude,
                self.hass.config.longitude,
                airports.keys() - configured,
            )
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema(
                user_input[CONF_INTERVAL]
                if user_input is not None and errors.get("base") != "invalid_input"
                else DEFAULT_INTERVAL,
                airports,
                airport_default,
            ),
            errors=errors,
        )


class TSAOptions(OptionsFlow):
    """Change polling without changing selected airport identity."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        default = self.config_entry.options.get(
            CONF_INTERVAL, self.config_entry.data.get(CONF_INTERVAL, DEFAULT_INTERVAL)
        )
        if user_input is not None:
            try:
                validated: dict[str, Any] = schema(default)(user_input)
            except vol.Invalid:
                return self.async_show_form(
                    step_id="init",
                    data_schema=schema(default),
                    errors={"base": "invalid_input"},
                )
            return self.async_create_entry(title="", data=validated)
        return self.async_show_form(step_id="init", data_schema=schema(default))
