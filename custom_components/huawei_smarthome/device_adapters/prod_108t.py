"""User-contributed protocol for Huawei product 108T (720 全效空气净化器).

型号 KJ500F-EP500H(720), deviceTypeId=013(空气净化器)。
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/108T/108T.json

实机 5 台验证通过（其中 1 台长期离线，实体为 unavailable 属正常）。

═══════════════════════════════════════════════════════
为什么要重写
═══════════════════════════════════════════════════════

远端原版是 gen_adapters.py 扫 Profile 生成的草稿, **只吐了 6 个实体**:

    switch childLock            童锁
    switch UV                   UV杀菌
    switch anion                负离子
    switch screenSwitch         显示屏
    switch keytoneSwitch        按键音
    sensor  pm2p5               PM2.5

**连电源开关都没有** —— 用户没法在 HA 里开关这台机器, 也没法定风速、切模式。
另外滤网寿命、故障、「待机自动开关」(实机上报但 Profile 没声明)全都没出来。

本版补齐到 18 个实体。现有 6 个 key **全部沿用**, entity_id 不变、
不影响已有自动化, 空壳不会出现。

═══════════════════════════════════════════════════════
核心决策: 用 fan 平台, 而不是「一个 switch + 两个 select」
═══════════════════════════════════════════════════════

这台设备的「电源 / 风速 / 模式」三件事在 HA 里的正确归宿是 **一个 fan 实体**:

    is_on        <- switch.on            电源
    percentage   <- wind.windSpeed       1~4 档 -> 25/50/75/100
    preset_mode  <- airPurifying.mode    手动 / 自动 / 睡眠

为什么不拆成 switch + select × 2:
拆开的话三个控件互相打架 —— 调风速不知道要不要先开机、切模式不知道会不会改风速,
而且界面上三个平级控件里藏着一个「主开关」, 反而不像一台净化器。
fan 是 HA 里净化器/新风的事实标准: 一个卡片就能开关、拉快慢、切自动睡眠。

**因此刻意不再单独暴露「风速 select」和「模式 select」**, 避免一个功能两个入口。

⚠️ fan 的关键坑(`fan.py` 的实现):
  * state 必须返回 `is_on` / `percentage` / `preset_mode` **这三个键名**,
    写成 `state` / `speed` 之类的**不会报错, 只会永远不显示**。
  * `metadata["supports_percentage"]` 为真才有 SET_SPEED feature,
    `metadata["preset_modes"]` 非空才有 PRESET_MODE feature —— **缺了界面上就没那个控件**。
  * `turn_on` 收到的是 `{"percentage": int|None, "preset_mode": str|None}`,
    两个都可能是 None(用户只是按了开关键), 要判空。
  * `async_send_service` 一次只能写一个 sid, 所以「开机并设为 3 档」要**连发两条**。

═══════════════════════════════════════════════════════
实机上报(2026-09-15, 5 台)
═══════════════════════════════════════════════════════

    switch           {"on": 0/1}
    airPurifying     {"mode": 0/1, "UV": 0/1, "anion": 1, "childLock": 0,
                      "screenSwitch": 0/1, "keytoneSwitch": 1,
                      "CAV": 17611..750460, "CMW": 64..1635,
                      "filterReplaceAlarm": 0}
    pm2p5            {"pm2p5Level": 1, "pm2p5Value": 1..10}
    wind             {"windSpeed": 1}
    temperature      {"currentTemperature": 0}          ← Profile 没有, 5 台恒 0
    faultDetection   {"code": 0, "status": 0}
    filterElement    {"leftTime": 1791..2400, "reset": 1, "leftPer": 74..100}
    stbyMonitor      {"enable": 0, "onPm2p5Value": 0/35, "offPm2p5Value": 0/5}
    timer            {"timer": [], "num": 8}
    netInfo / update

═══════════════════════════════════════════════════════
两个字段的语义是反推出来的
═══════════════════════════════════════════════════════

`CAV` / `CMW` Profile 只写了 `int R`, 没有任何描述。按 5 台数据对出来的关系:

    leftPer == leftTime / 2400 * 100      (1791/2400*100=74.6 -> 74 ✓
                                           1848/2400*100=77   -> 77 ✓
                                           2011/2400*100=83.8 -> 83 ✓
                                           2212/2400*100=92.2 -> 92 ✓)
    => **滤网满寿命 = 2400 小时**, leftTime 单位 h。

    CAV / CMW 落在 17611/64 .. 750460/1635, 比值 ~78..459 —— 不像同一物理量的两种单位。
    取「CAV = 累计净化空气量(m³)、CMW = 累计工作时长(h)」这个解释时,
    折算风量 78~459 m³/h 正落在 KJ500 标称 CADR 500 m³/h 以内(房间与档位不同)。

所以: CAV → m³, CMW → h, leftTime → h。**标注为推断**, 不是 Profile 写的。

═══════════════════════════════════════════════════════
🔴 写入实测(2026-09-15, 两台实机互为对照)
═══════════════════════════════════════════════════════

判据 = HA 实时 state 翻转; 全部改动**已复原到基线**。

    ✅ 电源开关        fan turn_on / turn_off         off -> on -> off 双向都通
    ✅ 风速            fan set_percentage 75          手动模式下 -> 3 档
    ✅ 运行模式        fan set_preset_mode            自动 -> 睡眠 -> 手动 都通
    ✅ 童锁 / UV / 负离子 / 显示屏 / 按键音           五个开关双向都通
    ✅ 待机自动开关    stbyMonitor.enable             off -> on  **可写**
    ✅ 自动开机阈值    stbyMonitor.onPm2p5Value       0 -> 40     **可写**
    ✅ 自动关机阈值    stbyMonitor.offPm2p5Value      0 -> 10     **可写**

最后三条值得一提: **`stbyMonitor` Profile 里根本没声明**, 是实机悄悄上报的
私有服务, 结果不仅可读还完全可写 —— 要是只照 Profile 写, 「PM2.5 超标自动开机、
达标自动关机」这个功能就彻底丢了。

═══════════════════════════════════════════════════════
⚠️ 睡眠模式会把风速锁死在最低档（设备固件行为）
═══════════════════════════════════════════════════════

第一轮探针里风速看起来「写不动」(设 50% 后仍显示 25%), 差点被误判成
又一个「假控件」。真实原因用**顺序实验**才找出来:

    先设 50% -> 再切「睡眠」        => 风速被压回 25%(1 档)
    先切「手动」-> 再设 75%         => 风速到 75%(3 档), 保持
    已到 75% 时再切「睡眠」         => 风速又被压回 25%(1 档)

**结论: 睡眠模式强制锁定最低风速**, 这是有意的设计(睡眠就是要安静),
不是写通道的问题。**想调风速要先切到手动或自动**。

教训: 看到「写入没生效」先怀疑**模式/联动在帮你改回去**, 别急着降级/删除控件。
判据是「换个前置状态下再发一次同样的命令」—— 能生效就是有人覆盖了你的值。

另外这台设备的状态上报有个 ~70 秒的滞后(若相邻两条命令间隔太近会看到
前一拍的值), 探针每条命令之间留了 2 秒, 比对要等足 2 分钟才准。

═══════════════════════════════════════════════════════
刻意不做的事
═══════════════════════════════════════════════════════

  * `netInfo`(IP / RSSI / SSID): 用户一贯偏好, 不映射。
  * `update.*`(OTA): 固件版本设备信息里已有; 而且 `version` 上报是空串。
  * `timer`: `array[object]`, 框架映射不了; 且实机恒为 `[]`。
  * `temperature.currentTemperature`: **Profile 里没有这个服务, 5 台实机恒为 0**
    —— 这台净化器大概率没配温度传感器, 建出来是一条永远 0 的假数据, 不建。
  * `filterElement.reset`: Profile 标 **R**(不是 W), 实机恒 1。
    看上去是「滤网已复位」状态位而非可下发命令, 没有可靠的写语义前不建 button。
  * `pm2p5` / `wind` / `mode` 的第二个入口: 见上, 统一走 fan, 不重复暴露。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


# ------------------------------------------------------------ 服务 / 字段常量

_SWITCH_SID = "switch"
_ON_FIELD = "on"                        # RW bool 电源

_PURIFY_SID = "airPurifying"
_MODE_FIELD = "mode"                    # RW 枚举 0手动 1自动 2睡眠
_FILTER_ALARM_FIELD = "filterReplaceAlarm"   # RW 枚举 0无 1有
_CHILD_LOCK_FIELD = "childLock"         # RW bool
_UV_FIELD = "UV"                        # RW bool
_ANION_FIELD = "anion"                  # RW bool
_SCREEN_FIELD = "screenSwitch"          # RW bool
_KEYTONE_FIELD = "keytoneSwitch"        # RW bool
_CAV_FIELD = "CAV"                      # R 累计净化量
_CMW_FIELD = "CMW"                      # R 累计工作时长

_PM25_SID = "pm2p5"
_PM25_VALUE_FIELD = "pm2p5Value"        # R
_PM25_LEVEL_FIELD = "pm2p5Level"        # R 枚举 1优 2良 3中 4差

_WIND_SID = "wind"
_WIND_SPEED_FIELD = "windSpeed"         # RW 枚举 1..4 档

_FAULT_SID = "faultDetection"
_FAULT_STATUS_FIELD = "status"          # R bool
_FAULT_CODE_FIELD = "code"              # R 枚举

_FILTER_SID = "filterElement"
_FILTER_LEFT_TIME_FIELD = "leftTime"    # R h
_FILTER_LEFT_PER_FIELD = "leftPer"      # R 0..100 %

_STBY_SID = "stbyMonitor"
_STBY_ENABLE_FIELD = "enable"           # RW bool (推断)
_STBY_ON_FIELD = "onPm2p5Value"         # RW 自动开机阈值 (推断)
_STBY_OFF_FIELD = "offPm2p5Value"       # RW 自动关机阈值 (推断)


# windSpeed 只有 4 档 -> HA fan 的百分比(**授 25% 为一档**, slider 步进也是 25)
_WIND_MIN = 1
_WIND_MAX = 4
_STEP_PERCENT = 100 // _WIND_MAX        # 25

# Profile 没给 stbyMonitor 的量程; PM2.5 语义下的保守范围
_STBY_PM25_MIN = 0
_STBY_PM25_MAX = 300


# ------------------------------------------------------------------- 取值工具


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "on"}:
            return True
        if normalized in {"0", "false", "off"}:
            return False
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _number(value: Any) -> float | None:
    """上报值可能是 int / float / 数字字符串; 取不到就 None, 不谎报 0。"""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except (TypeError, ValueError):
            return None
    return None


def _int_or_none(value: Any) -> int | None:
    """整数量值返回 int, 避免 10 µg/m³ 显示成 10.0。"""

    raw = _number(value)
    if raw is None:
        return None
    if abs(raw - round(raw)) < 1e-9:
        return int(round(raw))
    return None


def _has_data(context: DeviceContext, sid: str, field: str | None = None) -> bool:
    """门控: 实机有没有这个服务, 以及有没有这个字段。

    `stbyMonitor` Profile 里没声明, `temperature` Profile 里也没有,
    所以不能纯靠 Profile 门控; 但也不能无脑建 —— 有一台没上报 stbyMonitor,
    建出来就是永远 unknown 的空壳。
    """

    if not context.has_service(sid):
        return False
    if field is None:
        return bool(context.service_state(sid))
    return field in context.service_state(sid)


def _enum_table(profile: Any, sid: str, field: str) -> dict[str, str]:
    """从 Profile 的 enumList 取 "取值 -> 中文描述", 不硬编码。"""

    table: dict[str, str] = {}
    if not isinstance(profile, Mapping):
        return table
    for service in profile.get("services") or []:
        if not isinstance(service, Mapping) or service.get("serviceId") != sid:
            continue
        for characteristic in service.get("characteristics") or []:
            if not isinstance(characteristic, Mapping):
                continue
            if characteristic.get("characteristicName") != field:
                continue
            for item in characteristic.get("enumList") or []:
                if not isinstance(item, Mapping):
                    continue
                raw = item.get("enumVal")
                label = item.get("descCh") or item.get("descEn")
                if raw is None or not label:
                    continue
                table[str(raw)] = str(label)
    return table


def _enum_text(context: DeviceContext, sid: str, field: str) -> str | None:
    """把上报值翻译成 Profile 里写的中文; 查不到返回 None(显示「未知」), 不猜。"""

    value = context.value(sid, field)
    if value is None or isinstance(value, bool):
        return None
    return _enum_table(context.profile, sid, field).get(str(value))


def _coerce_enum(raw: str) -> Any:
    """Profile 的 enumVal 常写成字符串('0'/'1'), 下发时转成数字更稳妥。"""

    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return raw


# ------------------------------------------------------------------ 档位换算


def _percent_to_speed(percent: float) -> int:
    """HA 的百分比 -> 设备档位。0 会被夹到 1 档(设备没有 0 档)。"""

    speed = int(round(percent / _STEP_PERCENT))
    return max(_WIND_MIN, min(_WIND_MAX, speed))


def _speed_to_percent(speed: Any) -> int | None:
    """设备档位 -> HA 的百分比。"""

    raw = _int_or_none(speed)
    if raw is None or raw <= 0:
        return None
    return int(max(_WIND_MIN, min(_WIND_MAX, raw)) * _STEP_PERCENT)


# ------------------------------------------------------------- 实体构造函数


def _switch_spec(
    key: str,
    name: str,
    sid: str,
    field: str,
    icon: str | None = None,
) -> EntitySpec:
    """可读写布尔位。写 1/0(华为协议惯例), 不是 True/False。"""

    async def turn_on(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await device.async_send_service(sid, {field: 1})

    async def turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await device.async_send_service(sid, {field: 0})

    metadata = {"icon": icon} if icon else {}

    return EntitySpec(
        platform="switch",
        key=key,
        name=name,
        state=lambda device: {"is_on": _bool(device.value(sid, field))},
        metadata=metadata,
        actions={"turn_on": turn_on, "turn_off": turn_off},
    )


def _binary_spec(
    key: str,
    name: str,
    sid: str,
    field: str,
    device_class: str,
    icon: str | None = None,
) -> EntitySpec:
    """只读布尔位(故障 / 滤网更换提醒)。"""

    metadata: dict[str, Any] = {"device_class": device_class}
    if icon:
        metadata["icon"] = icon

    return EntitySpec(
        platform="binary_sensor",
        key=key,
        name=name,
        state=lambda device: {"is_on": _bool(device.value(sid, field))},
        metadata=metadata,
    )


def _sensor_spec(
    key: str,
    name: str,
    sid: str,
    field: str,
    unit: str | None = None,
    device_class: str | None = None,
    state_class: str | None = None,
    icon: str | None = None,
) -> EntitySpec:
    """数值型传感器。单位必须按 HA 的 device_class 规范写(不能照抄 Profile 的中文)。"""

    metadata: dict[str, Any] = {}
    if unit:
        metadata["unit"] = unit
    if device_class:
        metadata["device_class"] = device_class
    if state_class:
        metadata["state_class"] = state_class
    if icon:
        metadata["icon"] = icon

    return EntitySpec(
        platform="sensor",
        key=key,
        name=name,
        state=lambda device: {"native_value": _int_or_none(device.value(sid, field))},
        metadata=metadata,
    )


def _enum_sensor_spec(
    key: str,
    name: str,
    sid: str,
    field: str,
    icon: str | None = None,
) -> EntitySpec:
    """枚举型传感器(PM2.5 等级 / 故障码)。"""

    metadata = {"icon": icon} if icon else {}

    return EntitySpec(
        platform="sensor",
        key=key,
        name=name,
        state=lambda device: {"native_value": _enum_text(device, sid, field)},
        metadata=metadata,
    )


def _number_spec(
    key: str,
    name: str,
    sid: str,
    field: str,
    minimum: float,
    maximum: float,
    step: float = 1,
    unit: str | None = None,
) -> EntitySpec:
    """可写数值量。number.py 直接取 metadata["min"]/["max"], 缺了 KeyError。"""

    async def set_value(device: DeviceContext, data: Mapping[str, Any]) -> None:
        raw = _number(data.get("value"))
        if raw is None:
            return
        clamped = max(minimum, min(maximum, raw))
        await device.async_send_service(sid, {field: int(round(clamped))})

    metadata: dict[str, Any] = {"min": minimum, "max": maximum, "step": step}
    if unit:
        metadata["unit"] = unit

    return EntitySpec(
        platform="number",
        key=key,
        name=name,
        state=lambda device: {"native_value": _int_or_none(device.value(sid, field))},
        metadata=metadata,
        actions={"set_value": set_value},
    )


def _purifier_fan_spec(context: DeviceContext) -> EntitySpec:
    """净化器主实体: 一个 fan 管电源 + 风速 + 模式。

    ⚠️ fan.py 读的 state 键是 `is_on` / `percentage` / `preset_mode`,
    写错键名不报错、只会永远不显示。feature 由 metadata 决定:
      * `supports_percentage` -> SET_SPEED
      * `preset_modes` 非空   -> PRESET_MODE
      * 还要配合 `percentage_step`, 否则滑杆是连续的、拖到 37% 会被夹回档位。
    """

    preset_table = _enum_table(context.profile, _PURIFY_SID, _MODE_FIELD)
    preset_modes = list(preset_table.values())

    def read(device: DeviceContext) -> dict[str, Any]:
        return {
            "is_on": _bool(device.value(_SWITCH_SID, _ON_FIELD)),
            "percentage": _speed_to_percent(
                device.value(_WIND_SID, _WIND_SPEED_FIELD)
            ),
            "preset_mode": _enum_text(device, _PURIFY_SID, _MODE_FIELD),
        }

    async def turn_on(device: DeviceContext, data: Mapping[str, Any]) -> None:
        # 一次只能写一个 sid, 所以「开机并设到某档」要连发两条。
        await device.async_send_service(_SWITCH_SID, {_ON_FIELD: 1})
        percent = _number(data.get("percentage"))
        if percent is not None and percent > 0:
            await device.async_send_service(
                _WIND_SID, {_WIND_SPEED_FIELD: _percent_to_speed(percent)}
            )
        preset = data.get("preset_mode")
        if preset:
            for raw, label in preset_table.items():
                if label == preset:
                    await device.async_send_service(
                        _PURIFY_SID, {_MODE_FIELD: _coerce_enum(raw)}
                    )
                    break

    async def turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await device.async_send_service(_SWITCH_SID, {_ON_FIELD: 0})

    async def set_percentage(device: DeviceContext, data: Mapping[str, Any]) -> None:
        percent = _number(data.get("percentage"))
        if percent is None:
            return
        await device.async_send_service(
            _WIND_SID, {_WIND_SPEED_FIELD: _percent_to_speed(percent)}
        )

    async def set_preset_mode(device: DeviceContext, data: Mapping[str, Any]) -> None:
        preset = data.get("preset_mode")
        if not preset:
            return
        for raw, label in preset_table.items():
            if label == preset:
                await device.async_send_service(
                    _PURIFY_SID, {_MODE_FIELD: _coerce_enum(raw)}
                )
                return

    metadata: dict[str, Any] = {
        "supports_percentage": True,
        "percentage_step": _STEP_PERCENT,
    }
    if preset_modes:
        metadata["preset_modes"] = preset_modes

    return EntitySpec(
        platform="fan",
        key="purifier",
        name="空气净化器",
        state=read,
        metadata=metadata,
        actions={
            "turn_on": turn_on,
            "turn_off": turn_off,
            "set_percentage": set_percentage,
            "set_preset_mode": set_preset_mode,
        },
    )


# ------------------------------------------------------------------- 适配器


class Product108TAdapter:
    """108T KJ500F-EP500H 720 全效空气净化器。"""

    prod_id = "108T"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None:
            return ()

        specs: list[EntitySpec] = []

        # ---- 主实体: 电源 + 风速 + 模式 --------------------------------
        # 电源位是整台设备的基本盘, 它不在就没有 fan 这个实体。
        if _has_data(context, _SWITCH_SID, _ON_FIELD):
            specs.append(_purifier_fan_spec(context))

        # ---- airPurifying 的附属开关(沿用旧 key, entity_id 不变) -------
        if _has_data(context, _PURIFY_SID, _CHILD_LOCK_FIELD):
            specs.append(
                _switch_spec(
                    "childLock",
                    "童锁",
                    _PURIFY_SID,
                    _CHILD_LOCK_FIELD,
                    "mdi:lock",
                )
            )
        if _has_data(context, _PURIFY_SID, _UV_FIELD):
            specs.append(
                _switch_spec(
                    "UV", "UV杀菌", _PURIFY_SID, _UV_FIELD, "mdi:weather-sunny"
                )
            )
        if _has_data(context, _PURIFY_SID, _ANION_FIELD):
            specs.append(
                _switch_spec(
                    "anion", "负离子", _PURIFY_SID, _ANION_FIELD, "mdi:atom"
                )
            )
        if _has_data(context, _PURIFY_SID, _SCREEN_FIELD):
            specs.append(
                _switch_spec(
                    "screenSwitch",
                    "显示屏",
                    _PURIFY_SID,
                    _SCREEN_FIELD,
                    "mdi:monitor-small",
                )
            )
        if _has_data(context, _PURIFY_SID, _KEYTONE_FIELD):
            specs.append(
                _switch_spec(
                    "keytoneSwitch",
                    "按键音",
                    _PURIFY_SID,
                    _KEYTONE_FIELD,
                    "mdi:volume-high",
                )
            )

        # ---- 空气质量 ---------------------------------------------------
        if _has_data(context, _PM25_SID, _PM25_VALUE_FIELD):
            specs.append(
                _sensor_spec(
                    "pm2p5",
                    "PM2.5",
                    _PM25_SID,
                    _PM25_VALUE_FIELD,
                    unit="µg/m³",
                    device_class="pm25",
                    state_class="measurement",
                )
            )
        if _has_data(context, _PM25_SID, _PM25_LEVEL_FIELD):
            specs.append(
                _enum_sensor_spec(
                    "pm2p5_level",
                    "PM2.5等级",
                    _PM25_SID,
                    _PM25_LEVEL_FIELD,
                    "mdi:air-filter",
                )
            )

        # ---- 滤网 / 累计量 ----------------------------------------------
        if _has_data(context, _FILTER_SID, _FILTER_LEFT_PER_FIELD):
            specs.append(
                _sensor_spec(
                    "filter_left_percent",
                    "滤网剩余寿命",
                    _FILTER_SID,
                    _FILTER_LEFT_PER_FIELD,
                    unit="%",
                    icon="mdi:air-filter",
                )
            )
        if _has_data(context, _FILTER_SID, _FILTER_LEFT_TIME_FIELD):
            specs.append(
                _sensor_spec(
                    "filter_left_time",
                    "滤网剩余时长",
                    _FILTER_SID,
                    _FILTER_LEFT_TIME_FIELD,
                    unit="h",
                    icon="mdi:timer-outline",
                )
            )
        if _has_data(context, _PURIFY_SID, _FILTER_ALARM_FIELD):
            specs.append(
                _binary_spec(
                    "filter_replace_alarm",
                    "滤网更换提醒",
                    _PURIFY_SID,
                    _FILTER_ALARM_FIELD,
                    "problem",
                    "mdi:air-filter",
                )
            )
        # CAV / CMW 的单位是反推的, 见文件头说明。
        if _has_data(context, _PURIFY_SID, _CAV_FIELD):
            specs.append(
                _sensor_spec(
                    "cumulative_purified",
                    "累计净化量",
                    _PURIFY_SID,
                    _CAV_FIELD,
                    unit="m³",
                    state_class="total_increasing",
                    icon="mdi:air-purifier",
                )
            )
        if _has_data(context, _PURIFY_SID, _CMW_FIELD):
            specs.append(
                _sensor_spec(
                    "cumulative_work",
                    "累计工作时长",
                    _PURIFY_SID,
                    _CMW_FIELD,
                    unit="h",
                    state_class="total_increasing",
                    icon="mdi:clock-check-outline",
                )
            )

        # ---- 故障 --------------------------------------------------------
        if _has_data(context, _FAULT_SID, _FAULT_STATUS_FIELD):
            specs.append(
                _binary_spec(
                    "fault",
                    "故障",
                    _FAULT_SID,
                    _FAULT_STATUS_FIELD,
                    "problem",
                )
            )
        if _has_data(context, _FAULT_SID, _FAULT_CODE_FIELD):
            # ⚠️ 108T 的 Profile 给 `code` **没有声明 enumList**(不像 ZG1M 那台,
            # 它的 code 有 0=正常 / 1=过温保护)。没有官方文本就**不硬编码**
            # —— 编一张表就会把没见过的码译成错的意思。
            # 这里如实把原始码显示成数字: 平时是 0, 真出问题了用户能照着
            # 说明书对。「是否故障」这件事由上面的 `fault` 二进制传感器表达。
            specs.append(
                _sensor_spec(
                    "fault_code",
                    "故障码",
                    _FAULT_SID,
                    _FAULT_CODE_FIELD,
                    icon="mdi:alert-circle-outline",
                )
            )

        # ---- 待机自动开关(Profile 没声明, 有机器也没上报) ----------------
        if _has_data(context, _STBY_SID, _STBY_ENABLE_FIELD):
            specs.append(
                _switch_spec(
                    "standby_monitor",
                    "待机自动开关",
                    _STBY_SID,
                    _STBY_ENABLE_FIELD,
                    "mdi:power-sleep",
                )
            )
        if _has_data(context, _STBY_SID, _STBY_ON_FIELD):
            specs.append(
                _number_spec(
                    "standby_on_pm25",
                    "自动开机PM2.5阈值",
                    _STBY_SID,
                    _STBY_ON_FIELD,
                    _STBY_PM25_MIN,
                    _STBY_PM25_MAX,
                    unit="µg/m³",
                )
            )
        if _has_data(context, _STBY_SID, _STBY_OFF_FIELD):
            specs.append(
                _number_spec(
                    "standby_off_pm25",
                    "自动关机PM2.5阈值",
                    _STBY_SID,
                    _STBY_OFF_FIELD,
                    _STBY_PM25_MIN,
                    _STBY_PM25_MAX,
                    unit="µg/m³",
                )
            )

        return tuple(specs)


ADAPTER = Product108TAdapter()
