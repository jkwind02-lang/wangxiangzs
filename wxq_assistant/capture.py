"""User-selected visible-window capture only. Windows path must be tested on device."""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path


def _user32():
    if sys.platform != "win32":
        raise RuntimeError("窗口采集只在Windows上可用；当前环境可运行回放和规则测试")
    from ctypes import wintypes
    api = ctypes.WinDLL("user32", use_last_error=True)
    api.IsWindowVisible.argtypes = [wintypes.HWND]
    api.IsWindowVisible.restype = wintypes.BOOL
    api.IsIconic.argtypes = [wintypes.HWND]
    api.IsIconic.restype = wintypes.BOOL
    api.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    api.GetWindowTextLengthW.restype = ctypes.c_int
    api.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    api.GetWindowTextW.restype = ctypes.c_int
    return api


def list_windows() -> list[tuple[int, str]]:
    from ctypes import wintypes
    api = _user32()
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    api.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    api.EnumWindows.restype = wintypes.BOOL
    rows: list[tuple[int, str]] = []
    def collect(hwnd, _):
        if api.IsWindowVisible(hwnd) and not api.IsIconic(hwnd):
            size = api.GetWindowTextLengthW(hwnd)
            if size:
                buff = ctypes.create_unicode_buffer(size + 1)
                api.GetWindowTextW(hwnd, buff, len(buff))
                if buff.value and not buff.value.startswith("万象助手"):
                    rows.append((int(hwnd), buff.value))
        return True
    cb = callback_type(collect)
    if not api.EnumWindows(cb, 0):
        raise OSError("列举窗口失败")
    return rows


def capture_window(hwnd: int, destination: Path) -> Path:
    api = _user32()
    if type(hwnd) is not int or hwnd <= 0 or not api.IsWindowVisible(hwnd) or api.IsIconic(hwnd):
        raise ValueError("请先选择可见且未最小化的游戏窗口")
    try:
        from PIL import ImageGrab, ImageStat
    except ImportError as exc:
        raise RuntimeError("需要安装Pillow>=11.2.1以采集指定窗口") from exc
    # Explicit HWND avoids accidentally falling back to a full-desktop screenshot.
    image = ImageGrab.grab(window=hwnd)
    if image.width < 32 or image.height < 32:
        raise RuntimeError("采集画面尺寸异常")
    stat = ImageStat.Stat(image.convert("RGB"))
    if max(stat.mean) < 2 and max(stat.stddev) < 2:
        raise RuntimeError("采集结果疑似黑屏；请调整窗口模式，不读取或注入游戏进程")
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="PNG")
    return destination
