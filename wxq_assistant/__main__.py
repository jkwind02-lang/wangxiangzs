from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .advisor import Session, analyze
from .client import ModelClient, Settings
from .rules import ROOT
from .state import strict_json


def main() -> int:
    parser = argparse.ArgumentParser(description="万象助手：白歌回放、单次局面建议；不代操作")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("gui", help="打开桌面原型")
    sub.add_parser("demo", help="离线运行合成示例，不调用模型")
    p = sub.add_parser("analyze", help="分析一份局面JSON")
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--mode", choices=["live", "replay"], default="replay")
    p.add_argument("--online", action="store_true", help="明确允许将局面及相关卡文发送到配置的模型服务")
    args = parser.parse_args()
    try:
        if args.command == "gui":
            from .ui import main as gui
            gui()
            return 0
        path = ROOT / "examples" / "baige_demo.json" if args.command == "demo" else args.state
        s = Session()
        s.set_state(strict_json(path.read_text(encoding="utf-8-sig")), getattr(args, "mode", "replay"))
        ticket = s.begin()
        online = getattr(args, "online", False)
        result = analyze(s.state, ModelClient(Settings.from_env()) if online else None)
        if not s.accepts(ticket):
            raise ValueError("分析结果已超时或局面已失效；不发布旧建议")
        result["mode"] = s.mode
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
