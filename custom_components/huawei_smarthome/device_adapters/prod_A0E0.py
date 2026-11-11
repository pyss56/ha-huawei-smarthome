"""User-contributed protocol for Huawei product A0E0 (海尔 HarmonyOS 智能空调).

设备类型: 智能空调 (Air Conditioner), deviceModel=HarmonyOS, deviceTypeId=012
制造商: 海尔 (manufacturerId=371), protocolType=WiFi, accessType=CLOUD
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/A0E0/A0E0.json
         (运行态缓存: .storage/huawei_smarthome/profiles/A0E0.json)

核心服务 (取自 Profile data.profile.services):
   switch.on            bool RW (0=关, 1=开; quickmenu.switchInfo 明确 off:0/on:1)
   mode.mode            enum RW (1=自动, 2=制冷, 3=制热, 4=通风, 5=除湿)
   temperature.target   int  RW (目标温度 16-30 ℃, step 1.0)
   temperature.current  int  R  (当前室温 -20~50 ℃)
   fan.gear             enum RW (0=自动, 1=低风, 2=中风, 3=高风)
   fan.direction        enum RW (1=固定, 2=左右扫风, 3=上下扫风, 4=左右+上下)
   netInfo.intensity    enum R  (20/40/60/80/100 = 0~4 格信号)
   update.*             仅 OTA, 不暴露

本适配器暴露:
   1. climate 实体: 开关 / 模式 / 目标温度 / 当前室温 / 风速 / 摆风
   2. binary_sensor: 运行异常告警 (faultDetection.status, 存在时)
   3. sensor: Wi-Fi 信号强度 (netInfo.intensity)
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_TEMP_MIN = 16.0
_TEMP_MAX = 30.0
_TEMP_STEP = 1.0

# Profile enumList: 1=自动 2=制冷 3=制热 4=通风 5=除湿
_DEV_TO_HVAC = {1: "auto", 2: "cool", 3: "heat", 4: "fan_only", 5: "dry"}
_HVAC_TO_DEV = {v: k for k, v in _DEV_TO_HVAC.items()}

# Profile enumList: 1=固定 2=左右扫风 3=上下扫风 4=左右+上下
_DEV_TO_SWING = {1: "off", 2: "horizontal", 3: "vertical", 4: "both"}
_SWING_TO_DEV = {v: k for k, v in _DEV_TO_SWING.items()}

# Profile enumList: 0=自动 1=低风 2=中风 3=高风
_DEV_TO_FAN = {0: "auto", 1: "low", 2: "medium", 3: "high"}
_FAN_TO_DEV = {v: k for k, v in _DEV_TO_FAN.items()}

_HVAC_MODES = ["off", "auto", "cool", "heat", "fan_only", "dry"]
_SWING_MODES = ["off", "horizontal", "vertical", "both"]
_FAN_MODES = ["auto", "low", "medium", "high"]


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(int(value))
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.strip().casefold() in {"1", "true", "on"}:
            return True
        if value.strip().casefold() in {"0", "false", "off"}:
            return False
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    return None


class ProductA0E0Adapter:
    """海尔 HarmonyOS 智能空调 (A0E0) 适配器。"""

    prod_id = "A0E0"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None:
            return ()

        specs: list[EntitySpec] = []

        # 1. Climate 实体
        if context.has_service("switch") and context.has_service("mode"):

            def climate_state(device: DeviceContext) -> Mapping[str, Any]:
                is_on = _as_bool(device.value("switch", "on"))
                if is_on is False:
                    hvac_mode = "off"
                else:
                    hvac_mode = _DEV_TO_HVAC.get(
                        _as_int(device.value("mode", "mode")), "auto"
                    )

                return {
                    "hvac_mode": hvac_mode,
                    "current_temperature": _as_float(
                        device.value("temperature", "current")
                    ),
                    "target_temperature": _as_float(
                        device.value("temperature", "target")
                    ),
                    "fan_mode": _DEV_TO_FAN.get(
                        _as_int(device.value("fan", "gear")), "auto"
                    ),
                    "swing_mode": _DEV_TO_SWING.get(
                        _as_int(device.value("fan", "direction")), "off"
                    ),
                }

            async def set_hvac_mode(
                device: DeviceContext, data: Mapping[str, Any]
            ) -> None:
                mode = data.get("hvac_mode")
                if mode == "off":
                    await device.async_send_service("switch", {"on": 0})
                    return
                dev_val = _HVAC_TO_DEV.get(str(mode))
                if dev_val is None:
                    return
                if not _as_bool(device.value("switch", "on")):
                    await device.async_send_service("switch", {"on": 1})
                await device.async_send_service("mode", {"mode": dev_val})

            async def set_temperature(
                device: DeviceContext, data: Mapping[str, Any]
            ) -> None:
                temp = data.get("temperature")
                if temp is None:
                    return
                try:
                    val = int(
                        round(max(_TEMP_MIN, min(_TEMP_MAX, float(temp))))
                    )
                except (TypeError, ValueError):
                    return
                await device.async_send_service("temperature", {"target": val})

            async def set_fan_mode(
                device: DeviceContext, data: Mapping[str, Any]
            ) -> None:
                val = _FAN_TO_DEV.get(str(data.get("fan_mode")))
                if val is not None:
                    await device.async_send_service("fan", {"gear": val})

            async def set_swing_mode(
                device: DeviceContext, data: Mapping[str, Any]
            ) -> None:
                val = _SWING_TO_DEV.get(str(data.get("swing_mode")))
                if val is not None:
                    await device.async_send_service("fan", {"direction": val})

            async def turn_on(
                device: DeviceContext, _data: Mapping[str, Any]
            ) -> None:
                await device.async_send_service("switch", {"on": 1})

            async def turn_off(
                device: DeviceContext, _data: Mapping[str, Any]
            ) -> None:
                await device.async_send_service("switch", {"on": 0})

            specs.append(
                EntitySpec(
                    platform="climate",
                    key="ac",
                    name="空调",
                    state=climate_state,
                    metadata={
                        "hvac_modes": _HVAC_MODES,
                        "fan_modes": _FAN_MODES,
                        "swing_modes": _SWING_MODES,
                        "min_temp": _TEMP_MIN,
                        "max_temp": _TEMP_MAX,
                        "temp_step": _TEMP_STEP,
                    },
                    actions={
                        "set_hvac_mode": set_hvac_mode,
                        "set_temperature": set_temperature,
                        "set_fan_mode": set_fan_mode,
                        "set_swing_mode": set_swing_mode,
                        "turn_on": turn_on,
                        "turn_off": turn_off,
                    },
                )
            )

        # 2. 运行异常告警 (仅当设备实际上报该服务时)
        if context.has_service("faultDetection"):

            def fault_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "is_on": _as_bool(device.value("faultDetection", "status"))
                    is True
                }

            specs.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="fault",
                    name="运行异常告警",
                    state=fault_state,
                    metadata={"device_class": "problem"},
                )
            )

        # 3. Wi-Fi 信号强度 (Profile enum 20/40/60/80/100 对应 0~4 格)
        if context.has_service("netInfo"):

            def wifi_state(device: DeviceContext) -> Mapping[str, Any]:
                intensity = _as_int(device.value("netInfo", "intensity"))
                return {
                    "native_value": intensity
                    if intensity is not None and 0 <= intensity <= 100
                    else None
                }

            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="wifi_signal",
                    name="Wi-Fi信号强度",
                    state=wifi_state,
                    metadata={
                        "unit": "%",
                        "state_class": "measurement",
                        "icon": "mdi:wifi",
                    },
                )
            )

        return tuple(specs)


ADAPTER = ProductA0E0Adapter()
