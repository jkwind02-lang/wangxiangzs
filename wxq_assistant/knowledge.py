"""Read upstream source records, not upstream prompts. Preserve provenance per record."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .rules import ROOT, profile

FILES = {
    "hero": "王者万象棋_英雄牌.json",
    "effect": "王者万象棋_效果牌.json",
    "talent": "王者万象棋_天赋牌.json",
    "equipment": "王者万象棋_装备牌.json",
    "player": "王者万象棋棋手详情.json",
}


def names(obj: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in {"名称", "棋手名称", "name"} and isinstance(value, str):
                out.add(value)
            out.update(names(value))
    elif isinstance(obj, list):
        for value in obj:
            out.update(names(value))
    return out


def records(data: Any) -> Iterable[tuple[str, dict[str, Any]]]:
    if isinstance(data, list):
        items = [(f"/{n}", row) for n, row in enumerate(data)]
    elif isinstance(data, dict) and ("name" in data or "名称" in data or "棋手名称" in data):
        items = [("", data)]
    elif isinstance(data, dict):
        items = [("/" + str(k).replace("~", "~0").replace("/", "~1"), row) for k, row in data.items()]
    else:
        raise ValueError("不支持的上游JSON结构")
    for pointer, row in items:
        if not isinstance(row, dict):
            raise ValueError("上游父记录必须为对象")
        yield pointer, row


class Knowledge:
    def __init__(self, root: Path | None = None):
        self.root = root or ROOT / "skills" / "wanxiang-build" / "data" / "documents"

    def for_state(self, state: dict[str, Any], max_characters: int = 32000) -> dict[str, Any]:
        selected: list[dict[str, Any]] = []
        missing_files: list[str] = []
        omitted: list[str] = []
        p = profile()
        selected.append({"source_id": p["id"], "status": p["status"], "source": p["source"], "record": p})
        requested = {kind: set() for kind in FILES}
        requested["player"].add(state["player"])
        for zone in ("board", "hand", "shop"):
            for c in state[zone]:
                if c["kind"] in requested:
                    requested[c["kind"]].add(c["name"])
        requested["talent"].update(state["talents"])
        requested["equipment"].update(state["equipment"])
        # A player's child-card names can satisfy effect-card requests as well.
        found: dict[str, set[str]] = {kind: set() for kind in FILES}
        found["player"].add(p["player"])
        found["effect"].update(p["cards"])
        used = len(json.dumps(selected, ensure_ascii=False))
        for kind, filename in FILES.items():
            path = self.root / filename
            if not path.is_file():
                missing_files.append(filename)
                continue
            raw = path.read_bytes()
            if len(raw) > 8_000_000:
                raise ValueError(f"资料文件异常大：{filename}")
            digest = hashlib.sha256(raw).hexdigest()
            data = json.loads(raw.decode("utf-8-sig"))
            for pointer, row in records(data):
                row_names = names(row)
                targets = requested[kind]
                if kind == "player":
                    targets = targets | requested["effect"]
                if not (targets & row_names):
                    continue
                source_id = f"{kind}:{digest[:12]}:{pointer or '/'}"
                entry = {"source_id": source_id, "status": "upstream_snapshot_not_independently_verified", "source": f"skills/wanxiang-build/data/documents/{filename}#{pointer}", "sha256": digest, "record": row}
                size = len(json.dumps(entry, ensure_ascii=False))
                if used + size > max_characters:
                    omitted.append(source_id)
                    continue
                selected.append(entry)
                found[kind].update(row_names)
                if kind == "player":
                    for child in row.get("关联卡牌", []):
                        if isinstance(child, dict) and child.get("类型") == "效果牌":
                            found["effect"].update(names(child))
                used += size
        missing_names = sorted(f"{kind}:{name}" for kind in FILES for name in requested[kind] - found[kind])
        return {"evidence": selected, "missing_files": missing_files, "missing_names": missing_names, "omitted_records": omitted, "notice": "资料是社区/上游快照。来源存在不等于机制已被当前版本实测；未命中的牌不靠名称臆测能力。"}
