"""Desktop prototype: explicit capture, reviewed transcription and event-driven advice."""
from __future__ import annotations

import copy
import json
import queue
import threading
import time
from pathlib import Path

from .advisor import Session, analyze
from .client import ModelClient, Settings
from .rules import ROOT
from .state import is_fresh, strict_json, utc_now, validate_state


def main():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText

    root = tk.Tk()
    root.title("万象助手 · 白歌回放与单次决策原型")
    root.geometry("1120x780")
    root.minsize(880, 580)
    session = Session()
    work = queue.Queue()
    busy = False
    capture_file = None
    capture_at = None
    window_rows = []
    task_generation = 0
    shown_ticket = None
    replay = tk.BooleanVar(value=True)
    log_enabled = tk.BooleanVar(value=False)
    topmost = tk.BooleanVar(value=False)
    status = tk.StringVar(value="未联网。先加载示例或局面文件；回放模式不会当作实时建议。")
    privacy = "文本分析发送局面及相关卡文；截图识别另行确认。无自动买卖或后台持续录屏。"
    ttk.Label(root, text=privacy, wraplength=1050).pack(fill="x", padx=12, pady=(10, 4))
    bar = ttk.Frame(root)
    bar.pack(fill="x", padx=10)
    body = ttk.Panedwindow(root, orient="horizontal")
    body.pack(fill="both", expand=True, padx=10, pady=8)
    left, right = ttk.Frame(body), ttk.Frame(body)
    body.add(left, weight=1)
    body.add(right, weight=1)
    ttk.Label(left, text="局面JSON（识别结果必须检查；修改会撤回旧建议）").pack(anchor="w")
    editor = ScrolledText(left, wrap="none", undo=True)
    editor.pack(fill="both", expand=True)
    ttk.Label(right, text="提示与校验结果（不提供未经验证的胜率）").pack(anchor="w")
    output = ScrolledText(right, wrap="word", state="disabled")
    output.pack(fill="both", expand=True)
    ttk.Label(root, textvariable=status, wraplength=1060).pack(fill="x", padx=12, pady=6)

    def show(value):
        output.configure(state="normal")
        output.delete("1.0", "end")
        output.insert("end", value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2))
        output.configure(state="disabled")

    def invalidate():
        nonlocal task_generation, shown_ticket
        session.invalidate()
        task_generation += 1
        shown_ticket = None
        show("输入或模式已改变，旧建议已撤回。请检查并应用当前局面。")

    def edited(_=None):
        if editor.edit_modified():
            invalidate()
            editor.edit_modified(False)

    editor.bind("<<Modified>>", edited)

    def load_data(data):
        invalidate()
        editor.delete("1.0", "end")
        editor.insert("1.0", json.dumps(data, ensure_ascii=False, indent=2))
        editor.edit_modified(False)

    def load_file():
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if path:
            try:
                load_data(validate_state(strict_json(Path(path).read_text(encoding="utf-8-sig"))))
                replay.set(True)
                status.set("已载入历史局面；默认回放模式，未更新时间。")
            except Exception as exc:
                messagebox.showerror("读取失败", str(exc))

    def apply_state():
        raw = validate_state(strict_json(editor.get("1.0", "end")))
        session.set_state(raw, "replay" if replay.get() else "live")
        return session.state

    def confirm():
        try:
            raw = validate_state(strict_json(editor.get("1.0", "end")))
            if not messagebox.askyesno("确认观察", "你已检查可见卡牌、费用、计数和未知项吗？\n确认不会改变截图原始时间。"):
                return
            raw["confirmed"] = True
            load_data(raw)
            apply_state()
            status.set("已人工确认；原始观察时间保留。")
        except Exception as exc:
            messagebox.showerror("确认失败", str(exc))

    def local():
        try:
            s = apply_state()
            if not replay.get() and not is_fresh(s, time.time(), session.max_age):
                raise ValueError("观察已过期。请重新采集；旧局面请用回放模式。")
            show(analyze(s))
            status.set("仅本地规则提醒，未调用模型。")
        except Exception as exc:
            messagebox.showerror("检查失败", str(exc))

    def start_worker(kind, fn, context):
        nonlocal busy
        if busy:
            messagebox.showinfo("已有请求", "已有一次请求正在进行。可以修改局面使旧请求失效。")
            return False
        busy = True
        def run():
            try:
                work.put((kind, True, fn(), context))
            except Exception as exc:
                work.put((kind, False, str(exc), context))
        threading.Thread(target=run, daemon=True).start()
        return True

    def online():
        try:
            if busy:
                raise ValueError("已有请求正在进行")
            settings = Settings.from_env()
            s = copy.deepcopy(apply_state())
            if not messagebox.askyesno("发送文本局面", f"将当前局面与相关资料发送到 {settings.host}，可能产生模型服务费用。\n本次不发送截图。继续吗？"):
                return
            ticket = session.begin()
            start_worker("advice", lambda: analyze(s, ModelClient(settings)), (ticket, s))
            status.set("正在分析本次局面；编辑输入可使本次结果失效。")
        except Exception as exc:
            messagebox.showerror("无法分析", str(exc))

    capture_bar = ttk.Frame(root)
    capture_bar.pack(fill="x", padx=10, pady=(0, 10))
    chooser = ttk.Combobox(capture_bar, state="readonly", width=45)
    chooser.pack(side="left", padx=3)

    def refresh_windows():
        nonlocal window_rows
        try:
            from .capture import list_windows
            window_rows = list_windows()
            chooser["values"] = [f"{h}: {t}" for h, t in window_rows]
            if window_rows:
                chooser.current(0)
        except Exception as exc:
            messagebox.showerror("窗口列表", str(exc))

    def capture():
        nonlocal capture_file, capture_at
        try:
            i = chooser.current()
            if i < 0 or i >= len(window_rows):
                raise ValueError("请先刷新并选择游戏窗口")
            from .capture import capture_window
            invalidate()
            capture_at = utc_now()
            path = ROOT / ".local" / "screenshots" / f"shot-{time.time_ns()}.png"
            capture_file = capture_window(window_rows[i][0], path)
            status.set(f"已保存指定窗口截图：{capture_file.name}；尚未发送至模型。")
        except Exception as exc:
            messagebox.showerror("采集失败", str(exc))

    def recognize():
        try:
            if busy:
                raise ValueError("已有请求正在进行")
            if capture_file is None:
                raise ValueError("请先采集指定窗口")
            settings = Settings.from_env(vision=True)
            if not messagebox.askyesno("发送截图", f"将所选窗口的完整截图发送到 {settings.host}。截图可能包含昵称或聊天内容，且可能产生费用。\n请确认没有不愿发送的内容。继续吗？"):
                return
            from .vision import blank_snapshot, transcribe
            invalidate()
            template = blank_snapshot("local-session", task_generation, capture_at)
            generation = task_generation
            path = capture_file
            start_worker("vision", lambda: transcribe(path, ModelClient(settings), template), generation)
            status.set("正在转录截图；完成后需人工确认，不会直接变成可执行建议。")
        except Exception as exc:
            messagebox.showerror("无法识别", str(exc))

    def poll():
        nonlocal busy, shown_ticket
        try:
            while True:
                kind, ok, value, context = work.get_nowait()
                busy = False
                if kind == "advice":
                    ticket, s = context
                    valid = session.accepts(ticket)
                else:
                    valid = context == task_generation
                if not valid:
                    status.set("结果已丢弃：局面改变、超时或观察过期。")
                    continue
                if not ok:
                    show("请求未成功：" + value + "\n可继续使用本地检查。")
                    status.set("请求失败，未显示旧建议。")
                elif kind == "vision":
                    load_data(value)
                    status.set("截图转录已载入；请检查JSON并点击“人工确认”，再进行分析。")
                else:
                    show(value)
                    shown_ticket = ticket
                    status.set("回放建议（非实时）" if replay.get() else "当前观察的建议；下一次画面变化必须重新采集。")
                    if log_enabled.get():
                        path = ROOT / ".local" / "sessions.jsonl"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        with path.open("a", encoding="utf-8") as f:
                            f.write(json.dumps({"state": s, "result": value, "mode": session.mode}, ensure_ascii=False) + "\n")
        except queue.Empty:
            pass
        if shown_ticket is not None and not session.display_current(shown_ticket):
            shown_ticket = None
            show("建议已过期，请重新采集或使用回放模式检查历史局面。")
        root.after(150, poll)

    for label, fn in (("加载JSON", load_file), ("示例", lambda: load_data(json.loads((ROOT / "examples" / "baige_demo.json").read_text(encoding="utf-8")))), ("人工确认", confirm), ("本地检查", local), ("模型分析", online)):
        ttk.Button(bar, text=label, command=fn).pack(side="left", padx=3, pady=3)
    ttk.Checkbutton(bar, text="回放模式", variable=replay, command=invalidate).pack(side="left", padx=5)
    ttk.Checkbutton(bar, text="本地记录", variable=log_enabled).pack(side="left")
    ttk.Checkbutton(bar, text="置顶", variable=topmost, command=lambda: root.attributes("-topmost", topmost.get())).pack(side="left")
    ttk.Button(capture_bar, text="刷新窗口", command=refresh_windows).pack(side="left", padx=3)
    ttk.Button(capture_bar, text="单次采集", command=capture).pack(side="left", padx=3)
    ttk.Button(capture_bar, text="模型转录截图", command=recognize).pack(side="left", padx=3)
    root.bind("<Control-Return>", lambda _: local())
    show("先运行回放和本地检查。\n本版没有持续观察、自动牌面跟踪或战斗模拟。\n仅会撤回已知发生变化或超时的建议，不会假装检测到未采集的变化。")
    root.after(150, poll)
    root.mainloop()
