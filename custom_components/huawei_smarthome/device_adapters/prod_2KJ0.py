"""User-contributed protocol for Huawei product 2KJ0 (KAMAI 吸顶灯).

设备类型: 吸顶灯 (KM032-F03A)
本适配器暴露:
   1. light 吸顶灯：开关 / 亮度(1~100% ↔ 0~255) / 色温(2700~6500K)
   2. select 灯光模式（8 档场景）

说明: progressTurnOn/progressTurnOff/nightWakeup（渐亮渐灭、夜灯唤醒）与
timer/delay 定时数组协议暂不适配。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.casefold() in {"1", "true", "on"}:
            return True
        if value.casefold() in {"0", "false", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _service(profile: Mapping[str, Any], sid: str) -> Mapping[str, Any] | None:
    for service in profile.get("services", ()):
        if isinstance(service, Mapping) and service.get("serviceId") == sid:
            return service
    return None


def _field(
    profile: Mapping[str, Any],
    sid: str,
    name: str,
) -> Mapping[str, Any] | None:
    service = _service(profile, sid)
    if service is None:
        return None
    for field in service.get("characteristics", ()):
        if isinstance(field, Mapping) and field.get("characteristicName") == name:
            return field
    return None


def _device_brightness_to_ha(
    value: Any,
    field: Mapping[str, Any],
) -> int | None:
    """Convert the device brightness percentage to HA's 0-255 scale.

    华为这个 Profile 用百分比表示亮度（unit=%），最小值 1 表示"最暗"而不是"关灯"，
    因此**不能**把 min 当成偏移量做线性映射：那样 52% 会得到
    round((52-1) * 255 / 99) = 131，在 HA 里显示成 131/255 = 51.4% → 51%，
    比设备实际值少 1%。这里直接按 max 归一化，与项目内其它百分比亮度适配器一致。
    """

    number = _number(value)
    minimum = _number(field.get("min"))
    maximum = _number(field.get("max"))
    if number is None or maximum is None or maximum <= 0:
        return None
    if minimum is not None:
        number = max(float(number), float(minimum))
    number = min(float(number), float(maximum))
    return round(number * 255 / maximum)


def _ha_brightness_to_device(
    value: Any,
    field: Mapping[str, Any],
) -> int:
    """Convert HA's 0-255 brightness back to the device percentage."""

    maximum = _number(field.get("max"))
    minimum = _number(field.get("min"))
    if maximum is None or maximum <= 0 or minimum is None or maximum <= minimum:
        raise ValueError("2KJ0 brightness range is missing from the Profile")
    number = _number(value)
    if number is None:
        number = 0.0
    number = min(max(float(number), 0.0), 255.0)
    device_value = number * maximum / 255
    return int(round(max(device_value, float(minimum))))


async def _turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 1})
    if data.get("brightness") is not None:
        brightness_field = _field(
            context.profile or {}, "brightness", "brightness"
        )
        if brightness_field is None:
            raise ValueError("2KJ0 brightness field is missing from the Profile")
        await context.async_send_service(
            "brightness",
            {
                "brightness": _ha_brightness_to_device(
                    data["brightness"], brightness_field
                )
            },
        )
    if data.get("color_temp_kelvin") is not None:
        kelvin = _number(data["color_temp_kelvin"])
        if kelvin is not None:
            await context.async_send_service(
                "cct", {"colorTemperature": int(kelvin)}
            )


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 0})


class Product2KJ0Adapter:
    """Keep all 2KJ0 entity and command choices in this file."""

    prod_id = "2KJ0"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None or not all(
            context.has_service(sid) for sid in ("switch", "brightness", "cct")
        ):
            return ()

        brightness = _field(profile, "brightness", "brightness") or {}
        cct = _field(profile, "cct", "colorTemperature") or {}

        def light_state(device: DeviceContext) -> Mapping[str, Any]:
            is_on = _bool(device.value("switch", "on"))
            color_temp = _number(device.value("cct", "colorTemperature"))
            return {
                "is_on": is_on,
                "brightness": _device_brightness_to_ha(
                    device.value("brightness", "brightness"), brightness
                ),
                "color_temp_kelvin": color_temp if is_on else None,
                "color_mode": "color_temp" if is_on and color_temp else None,
            }

        entities = [
            EntitySpec(
                platform="light",
                key="light",
                name="灯",
                state=light_state,
                metadata={
                    "supported_color_modes": {"color_temp"},
                    "min_color_temp_kelvin": cct.get("min"),
                    "max_color_temp_kelvin": cct.get("max"),
                },
                actions={"turn_on": _turn_on, "turn_off": _turn_off},
            )
        ]

        if context.has_service("lightMode"):
            mode_field = _field(profile, "lightMode", "mode") or {}
            options = tuple(
                (
                    str(option.get("descCh") or option.get("enumVal")),
                    str(option.get("enumVal")),
                )
                for option in mode_field.get("enumList", ())
                if isinstance(option, Mapping)
            )

            def mode_state(device: DeviceContext) -> Mapping[str, Any]:
                value = _number(device.value("lightMode", "mode"))
                if value is None:
                    return {"current_option": None}
                current = next(
                    (label for label, raw in options if _number(raw) == value),
                    str(value),
                )
                return {"current_option": current}

            async def select_mode(
                device: DeviceContext, data: Mapping[str, Any]
            ) -> None:
                target = next(
                    (raw for label, raw in options if label == data["option"]),
                    None,
                )
                if target is None:
                    raise ValueError(f"unknown light mode: {data['option']}")
                await device.async_send_service(
                    "lightMode", {"mode": int(_number(target) or 0)}
                )

            entities.append(
                EntitySpec(
                    platform="select",
                    key="light_mode",
                    name="灯光模式",
                    state=mode_state,
                    metadata={"options": tuple(label for label, _ in options)},
                    actions={"select_option": select_mode},
                )
            )
        return tuple(entities)


ADAPTER = Product2KJ0Adapter()
