"""Strict observation schema. Unknown is not zero; recognition is not verification."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

ZONES = ("board", "hand", "shop")
CARD_FIELDS = {"uid", "name", "kind", "card_id", "level", "awakened", "price", "sell_value", "position"}
STATE_FIELDS = {"schema_version", "match_id", "sequence", "observed_at", "phase", "player", "round", "hp", "energy", "player_level", "board", "hand", "shop", "complete", "counters", "talents", "equipment", "banned_faction", "refresh_cost", "upgrade_cost", "provenance", "confirmed"}

class StateError(ValueError):
    pass


def strict_json(text: str) -> Any:
    def bad(value: str) -> None:
        raise StateError(f"JSON不允许 {value}")
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in items:
            if key in obj:
                raise StateError(f"重复JSON字段：{key}")
            obj[key] = value
        return obj
    return json.loads(text, parse_constant=bad, object_pairs_hook=pairs)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def epoch(value: str) -> float:
    if not isinstance(value, str):
        raise StateError("observed_at必须是带时区的ISO时间")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StateError("observed_at格式错误") from exc
    if dt.tzinfo is None:
        raise StateError("observed_at必须带时区")
    return dt.timestamp()


def number(value: Any, label: str, *, maximum: int = 100000, nullable: bool = True) -> None:
    if value is None and nullable:
        return
    if type(value) is not int or not 0 <= value <= maximum:
        raise StateError(f"{label}必须为0..{maximum}的整数" + ("或null" if nullable else ""))


def text(value: Any, label: str, maximum: int = 120) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise StateError(f"{label}必须为不超过{maximum}字符的非空文本")


def validate_state(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise StateError("局面必须为JSON对象")
    extra = set(raw) - STATE_FIELDS
    if extra:
        raise StateError(f"未知局面字段：{sorted(extra)}")
    s = copy.deepcopy(raw)
    if type(s.get("schema_version")) is not int or s["schema_version"] != 1:
        raise StateError("schema_version必须为1")
    text(s.get("match_id"), "match_id")
    number(s.get("sequence"), "sequence", nullable=False)
    epoch(s.get("observed_at"))
    if s.get("phase") not in {"preparation", "combat", "selection", "unknown"}:
        raise StateError("phase无效")
    text(s.get("player"), "player")
    for key in ("round", "hp", "energy", "player_level", "refresh_cost", "upgrade_cost"):
        number(s.get(key), key)
        s.setdefault(key, None)
    if type(s.get("confirmed")) is not bool:
        raise StateError("confirmed必须为布尔值")
    if s.get("provenance") not in {"manual", "vision", "synthetic", "replay"}:
        raise StateError("provenance无效")
    seen: set[str] = set()
    for zone in ZONES:
        cards = s.get(zone)
        if not isinstance(cards, list) or len(cards) > 100:
            raise StateError(f"{zone}必须为不超过100条的列表")
        for c in cards:
            if not isinstance(c, dict) or set(c) - CARD_FIELDS:
                raise StateError(f"{zone}卡牌字段无效")
            for key in ("uid", "name"):
                text(c.get(key), key)
            if c["uid"] in seen:
                raise StateError(f"重复uid：{c['uid']}")
            seen.add(c["uid"])
            if c.get("kind") not in {"hero", "effect", "equipment", "unknown"}:
                raise StateError("卡牌kind无效")
            if c.get("card_id") is not None:
                text(c["card_id"], "card_id")
            for key in ("level", "price", "sell_value"):
                number(c.get(key), key)
            if c.get("awakened") is not None and type(c["awakened"]) is not bool:
                raise StateError("awakened必须为布尔值或null")
            p = c.get("position")
            if p is not None and (not isinstance(p, list) or len(p) != 2 or any(type(x) is not int or not 0 <= x < 100 for x in p)):
                raise StateError("position必须为两项非负整数或null")
    complete = s.get("complete")
    if not isinstance(complete, dict) or set(complete) != set(ZONES) or any(type(v) is not bool for v in complete.values()):
        raise StateError("complete必须明确包含board/hand/shop的布尔值")
    counters = s.get("counters", {})
    if not isinstance(counters, dict) or set(counters) - {"merges_since_reward", "improvisations_since_burst"}:
        raise StateError("counters字段无效")
    for key, value in counters.items():
        number(value, key)
    s["counters"] = counters
    for key in ("talents", "equipment"):
        items = s.setdefault(key, [])
        if not isinstance(items, list) or len(items) > 100:
            raise StateError(f"{key}必须为列表")
        for v in items:
            text(v, key)
    if s.get("banned_faction") is not None:
        text(s["banned_faction"], "banned_faction")
    return s


def snapshot_id(state: dict[str, Any]) -> str:
    payload = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def is_fresh(state: dict[str, Any], now: float, max_age: float) -> bool:
    age = now - epoch(state["observed_at"])
    return math.isfinite(age) and -2 <= age <= max_age
