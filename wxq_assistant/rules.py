"""Conservative checks for the NEXT action only; not a combat or sequence simulator."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ACTION_TYPES = {"buy", "sell", "play", "use_effect", "refresh", "upgrade", "move", "wait", "inspect"}


def profile() -> dict[str, Any]:
    return json.loads((ROOT / "profiles" / "baige.snapshot.json").read_text(encoding="utf-8"))


def reminders(state: dict[str, Any]) -> list[str]:
    p = profile()
    out = []
    if not state["confirmed"]:
        out.append("局面未人工确认；仅显示观察，不给出买卖等操作建议。")
    for zone, complete in state["complete"].items():
        if not complete:
            out.append(f"{zone}未完整识别，不能将未看到的卡牌当作不存在。")
    if state["player"] != p["player"]:
        out.append("本版只含白歌专项提醒，其他棋手不套用白歌计数。")
        return out
    out.append("以下白歌提醒依据社区快照，当前版本及交互尚未实测。")
    c = state["counters"]
    n = c.get("merges_since_reward")
    if n is not None:
        if n < p["merge_threshold"]:
            out.append(f"若快照规则仍适用，距下一张即兴创作还差{p['merge_threshold']-n}次合成。")
        else:
            out.append("合成计数达到或超过快照阈值；请核对奖励是否发放或计数是否为累计值。")
    n = c.get("improvisations_since_burst")
    if n is not None and n < p["improvisation_threshold"]:
        out.append(f"若快照规则仍适用，距灵感爆发还差{p['improvisation_threshold']-n}次即兴创作使用。")
    names = {c["name"] for c in state["hand"]}
    if "即兴创作" in names:
        out.append("即兴创作看场上目标，不是手牌目标；不因想复制某英雄就假定一定命中。")
    if "灵感爆发" in names:
        eligible = [c for c in state["hand"] if c["kind"] == "hero" and c.get("awakened") is False]
        unknown = [c for c in state["hand"] if c["kind"] == "unknown" or (c["kind"] == "hero" and c.get("awakened") is None)]
        out.append(f"灵感爆发：可见且明确非觉醒英雄牌{len(eligible)}张；目标资格未知{len(unknown)}张。未核实抽样方式，不给精确概率。")
    return out


def check_action(state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    blocked: list[str] = []
    unchecked: list[str] = []
    checked: list[str] = []
    if not isinstance(action, dict) or set(action) - {"type", "uid", "target_uid"}:
        return {"status": "blocked", "blocked": ["操作格式错误"], "checked": [], "unchecked": []}
    kind = action.get("type")
    if kind not in ACTION_TYPES:
        return {"status": "blocked", "blocked": ["未知操作类型"], "checked": [], "unchecked": []}
    for k in ("uid", "target_uid"):
        if action.get(k) is not None and not isinstance(action[k], str):
            blocked.append(f"{k}必须是字符串或null")
    if blocked:
        return {"status": "blocked", "blocked": blocked, "checked": [], "unchecked": []}
    if kind in {"wait", "inspect"}:
        return {"status": "informational", "blocked": [], "checked": ["不建议改变游戏状态"], "unchecked": []}
    if not state["confirmed"]:
        blocked.append("局面未确认")
    if state["phase"] != "preparation":
        blocked.append("不是已确认的备战阶段")
    zones = {c["uid"]: (z, c) for z in ("board", "hand", "shop") for c in state[z]}
    uid = action.get("uid")
    target_uid = action.get("target_uid")
    card = None
    cost = None
    allowed_zone = {"buy": {"shop"}, "sell": {"board", "hand"}, "play": {"hand"}, "use_effect": {"hand"}, "move": {"board"}}
    if kind in allowed_zone:
        if uid not in zones:
            blocked.append("操作对象不在当前已见局面中")
        else:
            zone, card = zones[uid]
            if zone not in allowed_zone[kind]:
                blocked.append("操作对象所在区域不符")
            else:
                checked.append("操作对象可见且区域正确")
    elif uid is not None or target_uid is not None:
        blocked.append("此操作不应包含卡牌目标")
    if target_uid is not None and target_uid not in zones:
        blocked.append("指定目标不在已见局面中")
    if kind == "buy" and card:
        cost = card.get("price")
        if cost is None:
            blocked.append("购买价格未确认")
        unchecked.append("手牌容量及其他购买限制未建模")
    elif kind in {"refresh", "upgrade"}:
        cost = state.get("refresh_cost" if kind == "refresh" else "upgrade_cost")
        if cost is None:
            blocked.append("当前操作费用未确认")
        unchecked.append("升阶生效时点、锁格和其他特殊限制未模拟")
    if cost is not None:
        if state["energy"] is None:
            blocked.append("当前能量未知")
        elif state["energy"] < cost:
            blocked.append("当前能量不足")
        else:
            checked.append(f"观察到的能量可支付{cost}点费用")
    if kind == "play" and card and card["kind"] != "hero":
        blocked.append("play只用于英雄牌；效果牌须使用use_effect")
    if kind == "use_effect" and card:
        if card["kind"] != "effect":
            blocked.append("该对象不是已确认的效果牌")
        name = card["name"]
        if name in {"即兴创作", "灵感爆发"}:
            zone = "board" if name == "即兴创作" else "hand"
            if target_uid is not None:
                blocked.append("随机效果不能写成指定命中目标")
            if not state["complete"][zone]:
                blocked.append("随机目标集合不完整")
            candidates = [c for c in state[zone] if c["kind"] == "hero" and (zone == "board" or c.get("awakened") is False)]
            if not candidates:
                blocked.append("没有明确可用的目标")
            if zone == "hand" and any(c["kind"] == "unknown" or (c["kind"] == "hero" and c.get("awakened") is None) for c in state[zone]):
                blocked.append("手牌中仍有目标资格未确认的牌")
            unchecked.append("随机分布、转瞬处理和当前正式服交互尚未验证")
        else:
            unchecked.append("此效果的完整目标限制与费用未建模")
    if kind in {"sell", "play", "move"}:
        unchecked.append("卖出损失、合成连锁、人口与站位效果未做完整模拟")
    unchecked.append("不代表战斗胜率、最优性或完整合法性证明")
    return {"status": "blocked" if blocked else "conditional", "blocked": blocked, "checked": checked, "unchecked": unchecked}
