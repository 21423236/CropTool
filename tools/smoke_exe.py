"""Launch the built EXE with an image and verify its native window."""
import ctypes
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

root = Path(__file__).resolve().parents[1]
user32 = ctypes.WinDLL("user32", use_last_error=True)
callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
expected = "demo.png — 图案框选工具"
process = subprocess.Popen([str(root / "dist" / "CutImage.exe"), str(root / "artifacts" / "demo.png")], cwd=root)
found = []

@callback_type
def inspect(hwnd, _):
    text = ctypes.create_unicode_buffer(1024)
    user32.GetWindowTextW(hwnd, text, len(text))
    if user32.IsWindowVisible(hwnd) and text.value == expected:
        found.append(hwnd)
    return True

try:
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        user32.EnumWindows(inspect, 0)
        if found:
            break
        if process.poll() is not None:
            raise RuntimeError(f"EXE exited before window appeared: {process.returncode}")
        time.sleep(0.25)
    if not found:
        raise RuntimeError("EXE native window did not appear")
    print(f"PASS: EXE opened image and displayed native window: {expected}")
    user32.PostMessageW(found[0], 0x0010, 0, 0)
    code = process.wait(timeout=15)
    if code != 0:
        raise RuntimeError(f"EXE exit code {code}")
    print("PASS: EXE closed normally (exit code 0)")
finally:
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=10)
