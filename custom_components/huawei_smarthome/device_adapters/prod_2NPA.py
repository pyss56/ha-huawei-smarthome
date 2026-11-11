"""User-contributed protocol for Huawei product 2NPA (海雀智能摄像头3Pro 4K双频版 / HuaQue Smart Camera 3 Pro 4K Dual-band).

Profile: https://smarthome-drcn.dbankcdn.com/device/guide/2NPA/2NPA.json
厂商: 深圳市海雀科技有限公司 | deviceName: 海雀智能摄像头3Pro 4K双频版 | protocolType: WiFi

与同门 2C60 (海雀摄像头Pro) 的关键差异（务必注意，不要照抄）：
  * 本型号摄像头服务拼写**正确**：switch / shootSwitch / videoSwitch / cruiseSwitch，不再有 2C60 的 carmera。
  * humanBodyAlarm 在本型号是只读 (R)，位于 alarmEvent 服务下 → 做 binary_sensor（2C60 中它是 carmera 下 RW，做成 switch）。
  * 本型号新增：animalAlarm(动物检测)、alarm(综合告警)、areaFencing(区域进入/离开侦测 RW)、
    numberIdentification.personNum(人数 0-6)、完整 6 个预置点；保留 voip 视频通话。

服务与特征（未列出者为敏感/隐私，不暴露）：
  switch.on                  bool  RW   摄像头开关 (1 开 / 0 待机)
  shootSwitch.on             bool  RW   拍照/抓拍开关 (常驻使能，非瞬时)
  videoSwitch.on             bool  RW   摄像开关
  cruiseSwitch.on            bool  RW   全景巡航 (拼写正确，有 c)
  alarmEvent.videoAlarm      bool  R    视频/移动检测告警
  alarmEvent.alarm           bool  R    综合告警 (有告警/无告警)
  alarmEvent.audioAlarm      bool  R    声音检测告警
  alarmEvent.animalAlarm     bool  R    动物检测告警
  alarmEvent.humanBodyAlarm  bool  R    人形检测告警
  alarmEvent.babyCryAlarm    bool  R    婴儿哭声检测告警
  alarmEvent.alarmId/id      str   RW   告警 id / 预留 id (敏感，不暴露)
  areaFencing.enterAreaAlarm     bool RW  区域进入侦测
  areaFencing.areaDepartureAlarm bool RW  区域离开侦测
  areaFencing.alarmId        str   RW   围栏告警 id (不暴露)
  numberIdentification.personNum int RW  人数识别 (0-6，单位"个") → 只读 sensor
  voip.voipCall              bool  RW   发起视频通话 (瞬时动作)
  voip.calling              bool   R    通话进行中
  voip.message              str    R    通话消息 (不暴露)
  visitPoint1..6.move       bool  RW   预置点跳转 (瞬时动作)；enable=是否已配置
  deviceInfo.id/verifyId    str   R/RW 设备云端 id (App 拉起插件用，敏感，不暴露)
  netInfo.RSSI/intensity    信号强度 (R)

为什么没有 camera 平台实体（重点）：
  * 该仓库未注册 camera 平台 (无 camera.py)，且本 Profile 也**没有**快照 URL / 视频流地址特征。
    因此无法在 HA 中呈现摄像头实时画面或抓拍图——这是硬限制，不是漏适配。
  * 按仓库"避免错误状态映射"的原则，本适配器不臆造 camera 实体，而是把云端真实可读/可写的
    控制与侦测能力映射到受支持的平台：switch / binary_sensor / button / sensor。
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
    """为某个 0/1 可写特征 (摄像头/拍摄/巡航/区域侦测) 生成一个 HA switch 实体。"""

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
    """为某个瞬时动作 (视频通话 / 预置点跳转) 生成一个 HA button 实体。"""

    async def press(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {char: value})

    return EntitySpec(
        platform="button",
        key=f"{sid}_{char}",
        name=name,
        state=lambda _context: {},
        actions={"press": press},
    )


def _make_sensor_spec(
    sid: str,
    char: str,
    name: str,
    *,
    unit: str | None = None,
    device_class: str | None = None,
) -> EntitySpec:
    """为某个整数/数值只读特征 (信号强度 / 人数) 生成一个 HA sensor 实体。"""

    def state(context: DeviceContext) -> Mapping[str, Any]:
        return {"native_value": _to_int(context.value(sid, char))}

    metadata: dict[str, Any] = {"state_class": "measurement"}
    if unit is not None:
        metadata["unit"] = unit
    if device_class is not None:
        metadata["device_class"] = device_class
    return EntitySpec(
        platform="sensor",
        key=char if sid == "netInfo" else f"{sid}_{char}",
        name=name,
        state=state,
        metadata=metadata,
    )


class Product2NPAAdapter:
    """海雀摄像头3Pro 4K：4 控制开关 + 2 区域侦测 + 6 告警 + 视频通话 + 6 预置点 + 人数/信号。"""

    prod_id = "2NPA"

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
        if context.has_service("cruiseSwitch"):  # 拼写正确，有 c（与 2C60 carmera 不同）
            specs.append(_make_switch_spec("cruiseSwitch", "on", "全景巡航"))

        # ---- 区域围栏：2 个 RW 区域侦测开关 ----
        if context.has_service("areaFencing"):
            specs.append(_make_switch_spec("areaFencing", "enterAreaAlarm", "区域进入侦测"))
            specs.append(_make_switch_spec("areaFencing", "areaDepartureAlarm", "区域离开侦测"))

        # ---- 告警事件服务 alarmEvent：本型号全部为只读告警 → binary_sensor ----
        if context.has_service("alarmEvent"):
            specs.append(_make_binary_sensor_spec("alarmEvent", "videoAlarm", "移动侦测", device_class="motion"))
            specs.append(_make_binary_sensor_spec("alarmEvent", "alarm", "综合告警"))
            specs.append(_make_binary_sensor_spec("alarmEvent", "audioAlarm", "声音告警", device_class="sound"))
            specs.append(_make_binary_sensor_spec("alarmEvent", "animalAlarm", "动物侦测", device_class="motion"))
            specs.append(_make_binary_sensor_spec("alarmEvent", "humanBodyAlarm", "人形侦测", device_class="motion"))
            specs.append(_make_binary_sensor_spec("alarmEvent", "babyCryAlarm", "婴儿哭声", device_class="sound"))

        # ---- 人数识别：personNum 0-6，只读展示为 sensor（不臆造 number 写入语义）----
        if context.has_service("numberIdentification"):
            specs.append(
                _make_sensor_spec("numberIdentification", "personNum", "人数识别", unit="个")
            )

        # ---- voip 视频通话 ----
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
            specs.append(
                _make_sensor_spec("netInfo", "RSSI", "信号强度 RSSI", unit="dBm", device_class="signal_strength")
            )

        return tuple(specs)


ADAPTER = Product2NPAAdapter()
