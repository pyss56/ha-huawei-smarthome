"""User-contributed protocol for Huawei product 22Q4 (小豚室外摄像机 云台版 / DophiGo Smart Camera).

Profile: https://smarthome-drcn.dbankcdn.com/device/guide/22Q4/22Q4.json
厂商: 智多豚 (DophiGo) | deviceTypeName: 网络摄像头 | deviceModel: DPH-OP-200 | protocolType: WiFi

服务与特征（原 Profile 把"全景巡航"服务写成 cruiseSwith，是拼写，本适配器照此 sid 读取）：
  switch.on              bool  RW   摄像头开关 (1 开 / 0 待机)
  shootSwitch.on         bool  RW   拍照开关/抓拍使能 (1 开 / 0 关)
  videoSwitch.on         bool  RW   摄像开关 (1 开 / 0 关)
  cruiseSwith.on         bool  RW   全景巡航 (1 开 / 0 关)  ← 注意拼写少了 c
  alarmEvent.humanBodyAlarm  bool RW   人形检测 (RW) → 视为检测使能/状态
  alarmEvent.animalAlarm     bool RW   动物检测 (RW) → 视为检测使能/状态
  alarmEvent.videoAlarm      bool R    视频/移动检测告警事件 (1=有 / 0=无)
  alarmEvent.audioAlarm      bool R    声音检测告警事件
  alarmEvent.babyCryAlarm    bool R    婴儿哭声检测告警事件
  alarmEvent.alarmId         str  RW   告警 id (PUSH 携带，敏感，不暴露)
  visitPoint1.enable     bool  RW   预置点是否已配置 (1=已配置)
  visitPoint1.move       bool  RW   移动到预置点 (瞬时动作，move=1 触发)
  visitPoint1.id/name    str   RW   预置点配置信息 (不暴露)
  commonExecution1.action enum  RW   一键执行 (0完成/1执行/2失败/3暂停) → 做成瞬时按钮
  deviceInfo.id          str   R    设备云端 id (App 拉起插件用，敏感，不暴露)
  update.*                    固件升级 (action 只写，危险，不暴露)
  netInfo.RSSI/intensity     信号强度 (R)

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
    """为某个 0/1 可写特征 (开关机 / 巡航 / 检测使能) 生成一个 HA switch 实体。"""

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
    """为某个瞬时动作 (预置点跳转 / 一键执行) 生成一个 HA button 实体。"""

    async def press(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {char: value})

    return EntitySpec(
        platform="button",
        key=f"{sid}_{char}",
        name=name,
        state=lambda _context: {},
        actions={"press": press},
    )


class Product22Q4Adapter:
    """小豚室外摄像机：4 控制开关 + 2 检测使能 + 3 只读告警 + 预置点 + 一键执行 + 信号。"""

    prod_id = "22Q4"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None:
            return ()

        specs: list[EntitySpec] = []

        # ---- 摄像头基础控制：4 个常驻开关 ----
        if context.has_service("switch"):
            specs.append(_make_switch_spec("switch", "on", "摄像头"))
        if context.has_service("shootSwitch"):
            specs.append(_make_switch_spec("shootSwitch", "on", "拍照开关"))
        if context.has_service("videoSwitch"):
            specs.append(_make_switch_spec("videoSwitch", "on", "摄像开关"))
        if context.has_service("cruiseSwith"):  # 注意：原 Profile 拼写缺 c
            specs.append(_make_switch_spec("cruiseSwith", "on", "全景巡航"))

        # ---- 告警事件服务 alarmEvent：RW 检测做 switch，只读告警做 binary_sensor ----
        if context.has_service("alarmEvent"):
            specs.append(_make_switch_spec("alarmEvent", "humanBodyAlarm", "人形侦测"))
            specs.append(_make_switch_spec("alarmEvent", "animalAlarm", "动物侦测"))

            specs.append(_make_binary_sensor_spec("alarmEvent", "videoAlarm", "移动侦测", device_class="motion"))
            specs.append(_make_binary_sensor_spec("alarmEvent", "audioAlarm", "声音告警", device_class="sound"))
            specs.append(_make_binary_sensor_spec("alarmEvent", "babyCryAlarm", "婴儿哭声", device_class="sound"))

        # ---- 预置点：本 Profile 只有 visitPoint1，enable 显示是否已配置，move 是跳转按钮 ----
        if context.has_service("visitPoint1"):
            specs.append(_make_binary_sensor_spec("visitPoint1", "enable", "预置点已配置"))
            specs.append(_make_button_spec("visitPoint1", "move", "预置点1"))

        # ---- 一键执行：通用执行槽，按枚举下发"执行"(1) ----
        if context.has_service("commonExecution1"):
            specs.append(_make_button_spec("commonExecution1", "action", "一键执行", value="1"))

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


ADAPTER = Product22Q4Adapter()
