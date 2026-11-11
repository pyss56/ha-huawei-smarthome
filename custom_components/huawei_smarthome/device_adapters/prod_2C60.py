"""User-contributed protocol for Huawei product 2C60 (鸿蒙智选 海雀智能摄像头 Pro 64GB / HuaQue Smart Camera Pro).

Profile: https://smarthome-drcn.dbankcdn.com/device/guide/2C60/2C60.json
厂商: 海雀 (Haique) | deviceTypeName: 鸿蒙智选 海雀智能摄像头Pro 64GB | protocolType: WiFi | accessType: CLOUD

服务与特征（注意原 Profile 把摄像头服务写成 carmera，是拼写，本适配器照此 sid 读取）：
  carmera.on            bool  RW   摄像头开关 (1 开 / 0 关)
  carmera.shoot         bool  RW   拍照/抓拍 (瞬时动作，触发后自动回 0)
  carmera.cruise        bool  RW   巡航/巡视 (1 开 / 0 关)
  carmera.humanBodyAlarm int  RW   人形侦测 (1 开 / 0 关)
  carmera.audioAlarm    int   R    声音告警事件 (1=告警 / 0=消失)
  carmera.videoAlarm    int   R    画面/移动告警事件 (1=告警 / 0=消失)
  carmera.babyCryAlarm  int   R    婴儿哭声告警事件 (1=告警 / 0=消失)
  carmera.alarmID       str   R    告警 id (诊断，不暴露)
  voip.voipCall         bool  RW   发起视频通话 (瞬时动作)
  voip.calling          bool  R    通话进行中
  voip.voipMsg          str   R    通话消息 (不暴露)
  hwaccount.*                 账号/授权管理，敏感，不暴露
  deviceInfo.*                设备 id，不暴露
  netInfo.RSSI/intensity     信号强度 (R)
  visitPoint1..6.move  bool  RW   预置点跳转 (瞬时动作)；enable=是否已配置

为什么没有 camera 平台实体（重点）：
  * 该仓库未注册 camera 平台 (无 camera.py)，且本 Profile 也**没有**快照 URL / 视频流地址特征。
    因此无法在 HA 中呈现摄像头实时画面或抓拍图——这是硬限制，不是漏适配。
  * 按仓库"避免错误状态映射"的原则，本适配器不臆造 camera 实体，而是把云端真实可读/可写的
    控制与侦测能力映射到受支持的平台：switch / binary_sensor / button / sensor。
  * 若未来需要实时画面，需仓库侧新增 camera 平台并补充取流逻辑，那超出单品适配器范围。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


def _bool(value: Any) -> bool | None:
    """把设备上报值 (bool / 1,0 / "1","0","true","false") 规整为 bool，失败返回 None。"""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.casefold()
        if lowered in {"1", "true", "on"}:
            return True
        if lowered in {"0", "false", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _make_switch_spec(sid: str, char: str, name: str) -> EntitySpec:
    """为某个 0/1 可写特征 (开关机 / 巡航 / 人形侦测) 生成一个 HA switch 实体。"""

    def state(context: DeviceContext) -> Mapping[str, Any]:
        return {"is_on": _bool(context.value(sid, char))}

    async def turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {char: 1})

    async def turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {char: 0})

    return EntitySpec(
        platform="switch",
        key=f"{sid}_{char}",
        name=name,
        state=state,
        actions={"turn_on": turn_on, "turn_off": turn_off},
    )


def _make_binary_sensor_spec(
    sid: str,
    char: str,
    name: str,
    *,
    device_class: str | None = None,
) -> EntitySpec:
    """为某个 1=告警/0=消失 的只读告警特征生成一个 HA binary_sensor 实体。"""

    def state(context: DeviceContext) -> Mapping[str, Any]:
        return {"is_on": _bool(context.value(sid, char))}

    metadata: dict[str, Any] = {}
    if device_class is not None:
        metadata["device_class"] = device_class
    return EntitySpec(
        platform="binary_sensor",
        key=f"{sid}_{char}",
        name=name,
        state=state,
        metadata=metadata,
    )


def _make_button_spec(sid: str, char: str, name: str, value: Any = 1) -> EntitySpec:
    """为某个瞬时动作 (拍照 / 视频通话 / 预置点跳转) 生成一个 HA button 实体。"""

    async def press(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {char: value})

    return EntitySpec(
        platform="button",
        key=f"{sid}_{char}",
        name=name,
        state=lambda _context: {},
        actions={"press": press},
    )


class Product2C60Adapter:
    """海雀智能摄像头 Pro：开关/巡航/人形侦测 + 移动/声音/哭声告警 + 拍照/通话/预置点 + 信号。"""

    prod_id = "2C60"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None:
            return ()

        specs: list[EntitySpec] = []

        # ---- carmera 服务：可写控制 + 只读告警 ----
        if context.has_service("carmera"):
            specs.append(_make_switch_spec("carmera", "on", "摄像头"))
            specs.append(_make_switch_spec("carmera", "cruise", "巡航"))
            specs.append(_make_switch_spec("carmera", "humanBodyAlarm", "人形侦测"))

            specs.append(_make_binary_sensor_spec("carmera", "videoAlarm", "移动侦测", device_class="motion"))
            specs.append(_make_binary_sensor_spec("carmera", "audioAlarm", "声音告警", device_class="sound"))
            specs.append(_make_binary_sensor_spec("carmera", "babyCryAlarm", "婴儿哭声", device_class="sound"))

            # 拍照/抓拍：瞬时动作 → button。
            specs.append(_make_button_spec("carmera", "shoot", "拍照"))

        # ---- voip 服务：视频通话 ----
        if context.has_service("voip"):
            specs.append(_make_button_spec("voip", "voipCall", "视频通话"))
            specs.append(_make_binary_sensor_spec("voip", "calling", "视频通话中"))

        # ---- visitPoint1..6：预置点跳转（瞬时动作 → button）----
        for index in range(1, 7):
            sid = f"visitPoint{index}"
            if context.has_service(sid):
                specs.append(_make_button_spec(sid, "move", f"预置点{index}"))

        # ---- netInfo：信号强度 ----
        if context.has_service("netInfo"):

            def rssi_state(device: DeviceContext) -> Mapping[str, Any]:
                return {"native_value": _to_int(device.value("netInfo", "RSSI"))}

            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="rssi",
                    name="信号强度 RSSI",
                    state=rssi_state,
                    metadata={
                        "unit": "dBm",
                        "device_class": "signal_strength",
                        "state_class": "measurement",
                    },
                )
            )

        return tuple(specs)


ADAPTER = Product2C60Adapter()
