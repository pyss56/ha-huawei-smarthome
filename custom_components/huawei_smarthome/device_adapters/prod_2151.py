"""User-contributed protocol for Huawei product 2151 (圆和四路智能开关).

设备类型: 智能开关 (X9ZK4, 鼎力)
本适配器暴露:
   1. switch 总开关  (switch.on)
   2. switch ×4 路开关 (switch1~switch4.on，名称优先取设备端自定义 name)

说明: timer / delay 定时数组与 update / netInfo 属系统服务，暂不适配。
命名与多路开关的既有实现保持一致（参考 prod_2BN0.py）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

# 四路开关；缺失的档位会自动跳过（只按实际存在的服务建实体）。
_WAY_COUNT = 4


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


def _way_label(context: DeviceContext, index: int) -> str:
    """Return the per-way label, preferring the name stored on the device."""

    raw = context.value(f"switch{index}", "name")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return f"第{index}路"


async def _set_switch(
    context: DeviceContext,
    sid: str,
    on: bool,
) -> None:
    await context.async_send_service(sid, {"on": 1 if on else 0})


class Product2151Adapter:
    """Keep all 2151 entity and command choices in this file."""

    prod_id = "2151"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None or not context.has_service("switch"):
            return ()

        entities: list[EntitySpec] = []

        # 总开关与各路一起组成开关列表，顺序固定：总开关在前。
        targets: list[tuple[str, str]] = [("switch", "总开关")]
        for index in range(1, _WAY_COUNT + 1):
            sid = f"switch{index}"
            if context.has_service(sid):
                targets.append((sid, _way_label(context, index)))

        for sid, name in targets:

            def switch_state(
                device: DeviceContext, _sid: str = sid
            ) -> Mapping[str, Any]:
                return {"is_on": _bool(device.value(_sid, "on")) is True}

            async def turn_on(
                device: DeviceContext,
                _data: Mapping[str, Any],
                _sid: str = sid,
            ) -> None:
                # 默认参数捕获循环变量，避免闭包共享同一个 sid。
                await _set_switch(device, _sid, True)

            async def turn_off(
                device: DeviceContext,
                _data: Mapping[str, Any],
                _sid: str = sid,
            ) -> None:
                await _set_switch(device, _sid, False)

            entities.append(
                EntitySpec(
                    platform="switch",
                    key=f"sw_{sid}",
                    name=name,
                    state=switch_state,
                    actions={"turn_on": turn_on, "turn_off": turn_off},
                )
            )

        return tuple(entities)


ADAPTER = Product2151Adapter()
