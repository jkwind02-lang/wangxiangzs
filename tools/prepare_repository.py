"""Clone a pinned upstream WITH history, then overlay this upgrade. Never pushes.

Run from a source ZIP: python tools/prepare_repository.py D:\\Projects\\wangxiangzs
Only creates a NEW local destination; refuses existing paths and unexpected collisions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys

UPSTREAM = "https://github.com/Cjy-CN/wanxiang-build.git"
TARGET = "https://github.com/jkwind02-lang/wangxiangzs.git"
COMMIT = "8e854a4fcfe2527d846fa917d51c2c50ebafabb1"
TREE = "cb498d09ed17cdc43271b9000bc9839d77c56e7a"
BRANCH = "feat/baige-live-advisor"
ROOT = Path(__file__).resolve().parents[1]


def git(cwd: Path, *args: str) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    p = subprocess.run(["git", "-C", str(cwd), *args], text=True, encoding="utf-8", capture_output=True,
                       timeout=120, check=False, env=env)
    if p.returncode:
        raise RuntimeError(f"git {' '.join(args[:2])}失败（退出码{p.returncode}）。检查网络与本机Git配置；不会尝试其他凭据。")
    return p.stdout.strip()


def overlay_plan(package: Path, destination: Path) -> list[tuple[Path, Path]]:
    manifest = json.loads((package / "UPGRADE_FILES.json").read_text(encoding="utf-8"))
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ValueError("升级包清单格式无效")
    plan = []
    seen = set()
    for item in entries:
        rel = item["path"]
        p = PurePosixPath(rel)
        if p.is_absolute() or not p.parts or any(x in {".", "..", ".git", ".local", ".env"} for x in p.parts) or "\\" in rel or ":" in rel:
            raise ValueError("清单包含不安全的相对路径")
        folded = rel.casefold()
        if folded in seen:
            raise ValueError("清单包含重复或大小写冲突路径")
        seen.add(folded)
        src = package.joinpath(*p.parts)
        if src.is_symlink() or not src.is_file() or any(x.is_symlink() for x in src.parents if x != package.parent):
            raise ValueError(f"升级源文件不存在或为符号链接：{rel}")
        if hashlib.sha256(src.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"升级文件哈希不符：{rel}")
        dst = destination.joinpath(*p.parts)
        if dst.exists() and rel not in {"README.md", ".gitignore"}:
            raise ValueError(f"目标已有同名文件，拒绝覆盖：{rel}")
        if dst.is_symlink() or any(x.is_symlink() for x in dst.parents if x != destination.parent):
            raise ValueError("目标不能包含符号链接")
        plan.append((src, dst))
    return plan


def apply_overlay(package: Path, destination: Path) -> list[str]:
    plan = overlay_plan(package, destination)  # Validate EVERYTHING before first write.
    archive = destination / "UPSTREAM_README.md"
    if archive.exists():
        raise ValueError("目标已有UPSTREAM_README.md，拒绝覆盖")
    if (destination / "README.md").is_file():
        archive.write_bytes((destination / "README.md").read_bytes())
    for src, dst in plan:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.name == ".gitignore" and dst.exists():
            # Preserve upstream exclusions as well as our secret/session exclusions.
            dst.write_bytes(dst.read_bytes().rstrip() + b"\n\n" + src.read_bytes())
        else:
            shutil.copyfile(src, dst)
    shutil.copyfile(package / "UPGRADE_FILES.json", destination / "UPGRADE_FILES.json")
    return [str(dst.relative_to(destination)).replace("\\", "/") for _, dst in plan] + ["UPSTREAM_README.md", "UPGRADE_FILES.json"]


def prepare(destination: Path) -> None:
    if destination.exists():
        raise ValueError("目标目录已经存在；为保护文件，请提供一个尚不存在的新目录")
    if not shutil.which("git"):
        raise ValueError("本机未找到Git")
    destination.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    p = subprocess.run(["git", "clone", "--no-checkout", "--origin", "upstream", UPSTREAM, str(destination)],
                       timeout=120, check=False, env=env)
    if p.returncode:
        raise RuntimeError("克隆失败，未进行叠加或远端写入")
    actual = git(destination, "rev-parse", f"{COMMIT}^{{commit}}")
    tree = git(destination, "rev-parse", f"{COMMIT}^{{tree}}")
    if actual != COMMIT or tree != TREE:
        raise RuntimeError("上游固定版本校验失败，拒绝继续")
    git(destination, "config", "core.autocrlf", "false")
    git(destination, "checkout", "-B", "main", COMMIT)
    git(destination, "remote", "add", "origin", TARGET)
    git(destination, "checkout", "-b", BRANCH)
    paths = apply_overlay(ROOT, destination)
    git(destination, "add", "--", *paths)
    print(f"本地仓库已准备：{destination}")
    print(f"main保留上游固定版本及原始历史；改动已暂存于{BRANCH}。")
    print("未创建提交，未推送，也未创建PR。先运行测试并检查差异，再使用你本机已经授权的Git身份提交。")
    print("建议命令：")
    for line in ("python -m unittest discover -s tests -v", "git diff --cached --stat", 'git commit -m "feat: add replay-first Baige decision assistant"',
                 "git push origin main", f"git push -u origin {BRANCH}"):
        print("  " + line)
    print("上述push为显式后续操作：没有--force；若远端已有历史，应先检查而非覆盖。")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        prepare(args.destination.resolve())
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"准备失败：{exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
