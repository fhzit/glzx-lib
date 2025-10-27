import sys
import json
import time
import math
import ctypes
from ctypes import wintypes
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QTextBrowser,
    QLabel,
    QVBoxLayout,
    QWidget,
    QPushButton,
)
try:
    import markdown
except Exception:
    markdown = None

# Windows-only helpers (guarded so the script doesn't crash on non-Windows)
IS_WINDOWS = sys.platform.startswith("win32")

user32 = ctypes.windll.user32 if IS_WINDOWS else None
kernel32 = ctypes.windll.kernel32 if IS_WINDOWS else None

# WinAPI constants/types (keyboard hook)
if IS_WINDOWS:
    WH_KEYBOARD_LL = 13
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    WM_SYSKEYDOWN = 0x0104
    WM_SYSKEYUP = 0x0105

    # LRESULT is LONG_PTR; use wintypes.LRESULT if available
    try:
        LRESULT = wintypes.LRESULT
    except AttributeError:  # fallback
        LRESULT = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long

    # ULONG_PTR may be missing on some Python builds; provide a fallback
    try:
        ULONG_PTR = wintypes.ULONG_PTR  # type: ignore[attr-defined]
    except AttributeError:
        ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

    LowLevelKeyboardProc = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wintypes.DWORD),
            ("scanCode", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]


def load_config():
    # Look for config.json next to this script
    base = Path(__file__).resolve().parent
    cfg_path = base / "config.json"
    default = {
        "title": "电子阅览室规章制度",
        "lock_seconds": 5,
        "window": {"width": 900, "height": 600},
        "font_point_size": 12,
        "requirements_markdown": "rules.md",
    }
    if not cfg_path.exists():
        return default
    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        # merge defaults shallowly
        for k, v in default.items():
            if k not in data:
                data[k] = v
        # ensure nested window defaults
        if "window" not in data or not isinstance(data["window"], dict):
            data["window"] = default["window"]
        else:
            for wk, wv in default["window"].items():
                if wk not in data["window"]:
                    data["window"][wk] = wv
        return data
    except Exception:
        return default


def load_rules_html(markdown_file: str):
    base = Path(__file__).resolve().parent
    md_path = base / markdown_file
    if not md_path.exists():
        return "<p>规则内容未找到。</p>"
    text = md_path.read_text(encoding="utf-8")
    if markdown:
        html_content = markdown.markdown(text)
        # Replace the last paragraph (桂林中学图书馆) with right-aligned version
        html_content = html_content.replace("<p>桂林中学图书馆</p>", '<p style="text-align: right;">桂林中学图书馆</p>')
        # Replace the date paragraph with right-aligned version
        html_content = html_content.replace("<p>2025年10月1日</p>", '<p style="text-align: right;">2025年10月1日</p>')
        # Add CSS to center the first h1 element
        styled_html = f"""
        <style>
            h1 {{ text-align: center; }}
        </style>
        {html_content}
        """
        return styled_html
    # Fallback: simple newline to <p>
    return "<pre>" + (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")) + "</pre>"


CFG = load_config()
RULES_HTML = load_rules_html(CFG.get("requirements_markdown", "rules.md"))


class ReadWindow(QMainWindow):
    def __init__(self, lock_seconds: int = 5) -> None:
        super().__init__()
        # prefer config value, fall back to argument
        cfg_lock = CFG.get("lock_seconds") if isinstance(CFG, dict) else None
        self.lock_seconds = max(1, int(cfg_lock if cfg_lock is not None else lock_seconds))
        self.remaining = self.lock_seconds
        self._deadline = None  # monotonic deadline in seconds
        # Timers (set during enforcement)
        self._mouse_lock_timer = None
        self._countdown_timer = None
        self._kb_hook = None
        self._kb_proc = None  # keep ref to callback to avoid GC
        self._cursor_hidden = False
        # Window properties from config
        title = CFG.get("title", "电子阅览室规章制度") if isinstance(CFG, dict) else "电子阅览室规章制度"
        self.setWindowTitle(title)
        # Set window flags to stay on top and disable minimize button
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | 
            Qt.CustomizeWindowHint | 
            Qt.WindowTitleHint | 
            Qt.WindowCloseButtonHint
        )
        win = CFG.get("window", {}) if isinstance(CFG, dict) else {}
        w = int(win.get("width", 900))
        h = int(win.get("height", 600))
        self.setFixedSize(w, h)

        # Widgets
        self.text = QTextBrowser(self)
        # Rules come from rendered HTML
        try:
            self.text.setHtml(RULES_HTML)
        except Exception:
            # fallback to plain text of markdown file
            self.text.setPlainText("规则内容加载失败")
        self.text.setReadOnly(True)
        self.text.setOpenExternalLinks(False)
        self.text.setFrameStyle(0)
        self.text.setStyleSheet("QTextBrowser { padding: 8px; }")
        font = QFont()
        # allow override via config
        fps = CFG.get("font_point_size", 12) if isinstance(CFG, dict) else 12
        font.setPointSize(int(fps))
        self.text.setFont(font)

        self.info = QLabel(self)
        self.info.setAlignment(Qt.AlignCenter)
        self.info.setText(f"请认真阅读，上述内容将显示 {self.lock_seconds} 秒，期间键鼠被限制…")

        self.close_btn = QPushButton("我已阅读并且同意遵守该规定，关闭窗口", self)
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.safe_close)

        layout = QVBoxLayout()
        layout.addWidget(self.text, 1)
        layout.addWidget(self.info, 0)
        layout.addWidget(self.close_btn, 0)

        container = QWidget(self)
        container.setLayout(layout)
        self.setCentralWidget(container)

    def showEvent(self, event):
        super().showEvent(event)
        self.center_on_screen()
        self.force_topmost()
        self.start_enforcement()

    def changeEvent(self, event):
        # Prevent window from being minimized
        if event.type() == event.Type.WindowStateChange:
            if self.windowState() & Qt.WindowMinimized:
                self.setWindowState(Qt.WindowActive)
                self.force_topmost()
        super().changeEvent(event)

    def center_on_screen(self):
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + (geo.height() - self.height()) // 2
        self.move(x, y)

    def force_topmost(self):
        # Strengthen topmost using WinAPI as well
        if IS_WINDOWS:
            try:
                hwnd = int(self.winId())
                HWND_TOPMOST = -1
                SWP_NOSIZE = 0x0001
                SWP_NOMOVE = 0x0002
                SWP_NOACTIVATE = 0x0010
                user32.SetWindowPos(wintypes.HWND(hwnd), HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            except Exception:
                pass
        self.raise_()
        self.activateWindow()

    def start_enforcement(self):
        # Keyboard hook for the lock period
        if IS_WINDOWS:
            self.install_keyboard_blocker()
        # Mouse center lock via periodic SetCursorPos (safer than ClipCursor)
        self._mouse_lock_timer = QTimer(self)
        self._mouse_lock_timer.timeout.connect(self._hold_cursor_center)
        self._mouse_lock_timer.start(10)  # every 10ms
        # Hide cursor while locked to avoid flicker perception
        if IS_WINDOWS:
            try:
                user32.ShowCursor(False)
                self._cursor_hidden = True
            except Exception:
                self._cursor_hidden = False
        # Countdown timer
        self._deadline = time.monotonic() + self.lock_seconds
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._tick)
        self._countdown_timer.start(250)  # higher refresh to avoid drift and off-by-one
        # Initialize remaining display
        self.remaining = max(0, int(math.ceil(self._deadline - time.monotonic())))
        self.update_info()
        # Immediately move cursor to center
        self._hold_cursor_center()

    def _center_point(self):
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else self.geometry()
        cx = geo.x() + geo.width() // 2
        cy = geo.y() + geo.height() // 2
        return cx, cy

    def _hold_cursor_center(self):
        if not IS_WINDOWS:
            return
        try:
            cx, cy = self._center_point()
            user32.SetCursorPos(int(cx), int(cy))
        except Exception:
            pass

    def _tick(self):
        # Calculate remaining based on monotonic deadline to avoid drift
        if self._deadline is None:
            return
        rem = math.ceil(self._deadline - time.monotonic())
        if rem <= 0:
            self.remaining = 0
            self.release_enforcement()
            return
        # Update label only when value changes
        if int(rem) != self.remaining:
            self.remaining = int(rem)
            self.update_info()

    def update_info(self):
        self.info.setText(f"请认真阅读（{self.remaining} 秒后可关闭），期间键盘与鼠标移动被限制。")

    def release_enforcement(self):
        # Stop timers
        if self._countdown_timer:
            self._countdown_timer.stop()
            self._countdown_timer = None
        self._deadline = None
        if self._mouse_lock_timer:
            self._mouse_lock_timer.stop()
            self._mouse_lock_timer = None
        # Show cursor back
        if IS_WINDOWS and self._cursor_hidden:
            try:
                user32.ShowCursor(True)
            except Exception:
                pass
            self._cursor_hidden = False
        # Unhook keyboard
        if IS_WINDOWS:
            self.uninstall_keyboard_blocker()
        # Enable close
        self.info.setText("阅读时间到，您可以关闭窗口。")
        self.close_btn.setEnabled(True)

    # ----- Keyboard blocking via LL hook -----
    def install_keyboard_blocker(self):
        if not IS_WINDOWS or self._kb_hook:
            return
        try:
            @LowLevelKeyboardProc
            def low_level_proc(nCode, wParam, lParam):
                # While in lock period, swallow everything
                if self.remaining > 0 and nCode == 0 and (wParam in (WM_KEYDOWN, WM_SYSKEYDOWN, WM_KEYUP, WM_SYSKEYUP)):
                    return 1  # block
                # Otherwise pass through
                return user32.CallNextHookEx(self._kb_hook, nCode, wParam, lParam)

            self._kb_proc = low_level_proc
            h_instance = kernel32.GetModuleHandleW(None)
            self._kb_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_proc, h_instance, 0)
        except Exception:
            self._kb_hook = None
            self._kb_proc = None

    def uninstall_keyboard_blocker(self):
        if not IS_WINDOWS:
            return
        try:
            if self._kb_hook:
                user32.UnhookWindowsHookEx(self._kb_hook)
        except Exception:
            pass
        finally:
            self._kb_hook = None
            self._kb_proc = None

    def closeEvent(self, event):
        # Always prevent closing via X button, only allow closing via the button
        event.ignore()
        self.force_topmost()

    def safe_close(self):
        # Cleanup enforcement
        self.release_enforcement()
        # Quit the application and exit the process
        QApplication.quit()
        sys.exit(0)


def main():
    app = QApplication(sys.argv)
    w = ReadWindow(lock_seconds=5)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
