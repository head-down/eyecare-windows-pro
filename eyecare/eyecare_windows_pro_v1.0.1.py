import customtkinter as ctk
import tkinter as tk
import threading
import time
import sys
import os
import ctypes
import winsound
import json

# Windows 专属注册表操作库
try:
    import winreg
    IS_WINDOWS = True
except ImportError:
    IS_WINDOWS = False

# 系统托盘
try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_SYSTRAY = True
except ImportError:
    HAS_SYSTRAY = False

# === 路径工具 ===
SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")


# === 配置管理 ===
class Config:
    """运行时配置，从 config.json 加载/保存"""

    def __init__(self):
        self.work_min = 20
        self.rest_min = 1
        self.is_running = True
        self.paused = False
        self.auto_start = False


config = Config()


def _get_screen_size():
    """获取主显示器物理像素分辨率（不受 DPI 缩放影响）"""
    if IS_WINDOWS:
        user32 = ctypes.windll.user32
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    # 非 Windows 回退
    root = tk.Tk()
    root.withdraw()
    w, h = root.winfo_screenwidth(), root.winfo_screenheight()
    root.destroy()
    return w, h


# === 1. 强制休息遮罩窗口 ===
class BreakOverlay:
    """
    全屏强制休息遮罩，倒计时归零自动关闭。
    使用物理像素 + overrideredirect 覆盖整个屏幕，解决高 DPI 缩放问题。

    回调说明：
    - on_close: 无论何种方式关闭都会调用（用于清理引用）
    - on_skip:  仅在用户主动跳过时调用（按钮 / Esc / 关窗）
    """

    def __init__(self, parent, duration_sec, on_close=None, on_skip=None):
        self.on_close = on_close
        self.on_skip = on_skip
        self._destroyed = False

        self.window = tk.Toplevel(parent)
        self.window.overrideredirect(True)  # 无边框，精确控制尺寸
        self.window.title("护眼模式")
        self.window.configure(bg="black")

        # 获取物理分辨率，覆盖全屏
        sw, sh = _get_screen_size()
        self.window.geometry(f"{sw}x{sh}+0+0")

        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", 0.85)
        self.window.resizable(False, False)

        # Windows API 强制置顶（解决 overrideredirect + topmost 层级不可靠问题）
        self._force_topmost()

        # 所有主动关闭操作都走 skip（而非 close）
        self.window.protocol("WM_DELETE_WINDOW", self.skip)
        self.window.bind("<Escape>", lambda _e: self.skip())

        self.lbl_msg = ctk.CTkLabel(
            self.window,
            text="👀 强制休息中...",
            font=("Microsoft YaHei", 30, "bold"),
            text_color="white",
        )
        self.lbl_msg.pack(pady=(150, 10))

        self.lbl_time = ctk.CTkLabel(
            self.window,
            text=str(duration_sec),
            font=("Consolas", 80, "bold"),
            text_color="#00FF00",
        )
        self.lbl_time.pack()

        self.btn_skip = ctk.CTkButton(
            self.window,
            text="结束休息 (返回工作)",
            width=200,
            height=40,
            fg_color="transparent",
            hover_color="#333333",
            text_color="#888888",
            command=self.skip,
        )
        self.btn_skip.pack(pady=50)

        self.time_left = duration_sec
        self._after_id = None       # countdown 的 after ID
        self._topmost_id = None     # keep_on_top 的 after ID
        self._start_countdown()
        self._start_keep_on_top()

    def _force_topmost(self):
        """通过 Windows API 将窗口设为 HWND_TOPMOST（一次性强制）"""
        if not IS_WINDOWS:
            return
        try:
            hwnd = self.window.winfo_id()
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            HWND_TOPMOST = -1
            ctypes.windll.user32.SetWindowPos(
                hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE
            )
        except Exception:
            pass

    def _start_keep_on_top(self):
        """每 2 秒重新抬升一次，防止其他程序抢占最顶层"""

        def keep():
            if self._destroyed:
                return
            try:
                self.window.lift()
                self.window.attributes("-topmost", True)
            except Exception:
                return
            self._topmost_id = self.window.after(2000, keep)

        keep()

    def _start_countdown(self):
        def tick():
            if self._destroyed:
                return
            if self.time_left > 0:
                self.time_left -= 1
                self.lbl_time.configure(text=str(self.time_left))
                self._after_id = self.window.after(1000, tick)
            else:
                self.close()  # 倒计时归零 = 自然结束

        tick()

    def _cancel_timers(self):
        """取消所有 after 回调"""
        if self._after_id is not None:
            self.window.after_cancel(self._after_id)
            self._after_id = None
        if self._topmost_id is not None:
            self.window.after_cancel(self._topmost_id)
            self._topmost_id = None

    def close(self):
        """倒计时归零时调用 — 自然结束，仅通知清理引用"""
        if self._destroyed:
            return
        self._destroyed = True
        self._cancel_timers()
        self.window.destroy()
        if self.on_close:
            self.on_close()

    def skip(self):
        """用户主动跳过 — 同时通知清理引用 + 切回工作状态"""
        if self._destroyed:
            return
        self._destroyed = True
        self._cancel_timers()
        self.window.destroy()
        if self.on_skip:
            self.on_skip()
        if self.on_close:
            self.on_close()


# === 2. 主界面 ===
class EyeCareApp(ctk.CTk):
    TITLE = "护眼助手 Windows Pro"
    TRAY_TOOLTIP = "护眼助手 - 工作中"

    def __init__(self):
        super().__init__()

        self.title(self.TITLE)
        self.geometry("400x350")
        self.resizable(False, False)

        # 1. 加载配置
        self.load_settings()

        # 2. 核心变量
        self.current_phase = "Work"
        self.overlay = None
        self.max_time = max(config.work_min, 1) * 60
        self.time_left = self.max_time

        # 3. 防止重复调度
        self._phase_switch_lock = threading.Lock()
        self._phase_switch_pending = False

        # 4. 托盘引用
        self._tray_icon = None
        self._quitting = False  # 真退出标志，区别于隐藏到托盘

        # 5. 构建 UI
        self.build_ui()

        # 6. 启动计时器
        self.start_timer()

        # 7. 初始化托盘
        if HAS_SYSTRAY:
            self._setup_tray()
        else:
            print("[提示] pystray 未安装，托盘功能不可用")

    # ==================== 托盘 ====================

    def _setup_tray(self):
        """在后台线程启动系统托盘图标"""
        icon_image = self._create_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("显示/隐藏主窗口", self._tray_toggle, default=True),
            pystray.MenuItem("退出", self._tray_quit),
        )
        self._tray_icon = pystray.Icon(
            "EyeCarePro",
            icon_image,
            self.TRAY_TOOLTIP,
            menu,
        )
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

    @staticmethod
    def _create_tray_image():
        """用 Pillow 生成一个 64x64 的护眼图标"""
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # 外圈：深绿
        draw.ellipse([4, 4, size - 5, size - 5], fill=(0, 150, 80, 255))
        # 内圈（眼白）
        draw.ellipse([14, 20, 50, 46], fill=(255, 255, 255, 255))
        # 瞳孔
        draw.ellipse([26, 24, 38, 42], fill=(30, 30, 30, 255))
        # 高光
        draw.ellipse([30, 26, 34, 32], fill=(255, 255, 255, 200))
        return img

    def _tray_toggle(self, _icon=None, _item=None):
        """双击托盘图标 → 显示/隐藏切换"""
        self.after(0, self._toggle_window)

    def _toggle_window(self):
        if self.state() == "withdrawn":
            self.deiconify()
            self.lift()
            self.focus_force()
        else:
            self.withdraw()

    def _tray_quit(self, _icon=None, _item=None):
        """从托盘菜单彻底退出"""
        self._quitting = True
        if self._tray_icon:
            self._tray_icon.stop()
        self.after(0, self._do_quit)

    def _do_quit(self):
        """真正的退出清理"""
        config.is_running = False
        if self.overlay:
            self.overlay.close()
            self.overlay = None
        self.destroy()

    # ==================== 配置 ====================

    def load_settings(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    config.work_min = max(data.get("work_min", 20), 1)
                    config.rest_min = max(data.get("rest_min", 1), 1)
            except (json.JSONDecodeError, OSError):
                pass

        config.auto_start = self._check_autostart()

    def _check_autostart(self):
        if not IS_WINDOWS:
            return False
        reg_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_READ
            )
            winreg.QueryValueEx(key, "EyeCarePro")
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            return False
        except OSError:
            return False

    # ==================== UI ====================

    def build_ui(self):
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        self.lbl_title = ctk.CTkLabel(
            self, text="状态：工作中 🖥️", font=("Microsoft YaHei", 20, "bold")
        )
        self.lbl_title.pack(pady=(20, 5))

        mins, secs = divmod(self.time_left, 60)
        self.lbl_time = ctk.CTkLabel(
            self, text=f"{mins:02d}:{secs:02d}", font=("Consolas", 60, "bold")
        )
        self.lbl_time.pack()

        self.progress = ctk.CTkProgressBar(self, width=300, corner_radius=10)
        self.progress.set(0)
        self.progress.pack(pady=10)

        frame_btn = ctk.CTkFrame(self, fg_color="transparent")
        frame_btn.pack(pady=15)

        self.btn_pause = ctk.CTkButton(
            frame_btn, text="⏸ 暂停", width=100, command=self.toggle_pause
        )
        self.btn_pause.pack(side="left", padx=10)

        self.btn_settings = ctk.CTkButton(
            frame_btn,
            text="⚙️ 设置",
            width=100,
            fg_color="#444444",
            hover_color="#555555",
            command=self.open_settings,
        )
        self.btn_settings.pack(side="left", padx=10)

        # 关闭按钮 → 隐藏到托盘，而不是退出
        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.update_ui_loop()

    # ==================== 窗口隐藏 / 恢复 ====================

    def hide_to_tray(self):
        """点击关闭按钮 → 隐藏到托盘（不退出）"""
        if HAS_SYSTRAY:
            self.withdraw()
        else:
            # 没有托盘功能时，回退到直接退出
            self._quitting = True
            self._do_quit()

    # ==================== 计时器 ====================

    def start_timer(self):
        def timer_loop():
            while config.is_running:
                if not config.paused:
                    if self.time_left > 0:
                        self.time_left -= 1
                    else:
                        with self._phase_switch_lock:
                            if not self._phase_switch_pending:
                                self._phase_switch_pending = True
                                self.after(0, self._safe_phase_switch)
                time.sleep(1)

        threading.Thread(target=timer_loop, daemon=True).start()

    def _safe_phase_switch(self):
        with self._phase_switch_lock:
            if self.time_left > 0:
                self._phase_switch_pending = False
                return
        self.phase_switch()

    def phase_switch(self):
        if self.overlay:
            try:
                self.overlay.close()
            except Exception:
                pass
            self.overlay = None

        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)

        if self.current_phase == "Work":
            self.current_phase = "Rest"
            self.max_time = max(config.rest_min, 1) * 60
            self.time_left = self.max_time
            self.lbl_title.configure(text="状态：休息中 🌿", text_color="green")
            self.overlay = BreakOverlay(
                self, self.max_time,
                on_close=self._on_overlay_closed,
                on_skip=self._on_overlay_skipped,
            )
            self._update_tray_tooltip("休息中")
        else:
            self.current_phase = "Work"
            self.max_time = max(config.work_min, 1) * 60
            self.time_left = self.max_time
            self.lbl_title.configure(text="状态：工作中 🖥️", text_color="#3B8ED0")
            self._update_tray_tooltip("工作中")

        with self._phase_switch_lock:
            self._phase_switch_pending = False

    def _on_overlay_closed(self):
        """遮罩关闭时清除引用（自然到期 or 主动跳过都会调用）"""
        self.overlay = None

    def _on_overlay_skipped(self):
        """用户主动跳过休息 → 立即切回工作状态"""
        self.current_phase = "Work"
        self.max_time = max(config.work_min, 1) * 60
        self.time_left = self.max_time
        self.lbl_title.configure(text="状态：工作中 🖥️", text_color="#3B8ED0")
        self._update_tray_tooltip("工作中")
        # 清除可能已被排队的 phase_switch，防止二次切换
        with self._phase_switch_lock:
            self._phase_switch_pending = False

    def _update_tray_tooltip(self, phase_text):
        """更新托盘图标悬停提示"""
        if self._tray_icon and HAS_SYSTRAY:
            self._tray_icon.title = f"护眼助手 - {phase_text}"

    def update_ui_loop(self):
        if not self.winfo_exists():
            return

        mins, secs = divmod(max(self.time_left, 0), 60)
        self.lbl_time.configure(text=f"{mins:02d}:{secs:02d}")

        if self.max_time > 0:
            progress_val = (self.max_time - self.time_left) / self.max_time
            progress_val = max(0.0, min(1.0, progress_val))
            self.progress.set(progress_val)
            self.progress.configure(
                progress_color="green"
                if self.current_phase == "Rest"
                else "#3B8ED0"
            )

        self.after(200, self.update_ui_loop)

    # ==================== 暂停 ====================

    def toggle_pause(self):
        config.paused = not config.paused
        if config.paused:
            self.btn_pause.configure(text="▶️ 继续", fg_color="green")
            self.lbl_title.configure(text="状态：已暂停 ⏸️")
        else:
            self.btn_pause.configure(text="⏸ 暂停", fg_color="#3B8ED0")
            self.lbl_title.configure(
                text=f"状态：{'工作中 🖥️' if self.current_phase == 'Work' else '休息中 🌿'}"
            )

    # ==================== 设置 ====================

    def open_settings(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("设置")
        dialog.geometry("320x260")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="工作时长 (分钟，≥1):", anchor="w").pack(
            fill="x", padx=20, pady=(15, 0)
        )
        entry_work = ctk.CTkEntry(dialog)
        entry_work.insert(0, str(config.work_min))
        entry_work.pack(padx=40, fill="x", pady=5)

        ctk.CTkLabel(dialog, text="休息时长 (分钟，≥1):", anchor="w").pack(
            fill="x", padx=20, pady=(5, 0)
        )
        entry_rest = ctk.CTkEntry(dialog)
        entry_rest.insert(0, str(config.rest_min))
        entry_rest.pack(padx=40, fill="x", pady=5)

        lbl_error = ctk.CTkLabel(
            dialog, text="", text_color="red", font=("Microsoft YaHei", 11)
        )
        lbl_error.pack(pady=(5, 0))

        self.var_autostart = ctk.BooleanVar(value=config.auto_start)
        chk_start = ctk.CTkCheckBox(
            dialog, text="Windows 开机自启", variable=self.var_autostart
        )
        chk_start.pack(pady=10, anchor="w", padx=20)

        def save_and_close():
            try:
                w = int(entry_work.get())
                r = int(entry_rest.get())
                if w < 1 or r < 1:
                    lbl_error.configure(text="时长必须 ≥ 1 分钟")
                    return
            except ValueError:
                lbl_error.configure(text="请输入有效的整数")
                return

            config.work_min = w
            config.rest_min = r
            config.auto_start = self.var_autostart.get()
            self.save_settings()

            if self.current_phase == "Work":
                self.max_time = config.work_min * 60
                self.time_left = self.max_time
            else:
                if self.overlay:
                    self.overlay.close()
                    self.overlay = None
                self.max_time = config.rest_min * 60
                self.time_left = self.max_time

            with self._phase_switch_lock:
                self._phase_switch_pending = False

            dialog.destroy()

        btn_save = ctk.CTkButton(dialog, text="保存并应用", command=save_and_close)
        btn_save.pack(pady=10)

    def save_settings(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(
                    {"work_min": config.work_min, "rest_min": config.rest_min},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except OSError:
            pass

        self._toggle_startup(config.auto_start)

    def _toggle_startup(self, enable):
        if not IS_WINDOWS:
            return
        reg_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_WRITE
            )
            if enable:
                if getattr(sys, "frozen", False):
                    app_path = sys.executable
                else:
                    app_path = f'python "{os.path.abspath(sys.argv[0])}"'
                winreg.SetValueEx(key, "EyeCarePro", 0, winreg.REG_SZ, app_path)
            else:
                try:
                    winreg.DeleteValue(key, "EyeCarePro")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except OSError as e:
            print(f"自启设置失败：{e}")

    # ==================== 关闭 ====================

    # hide_to_tray 已在「窗口隐藏 / 恢复」区域定义，此处不再重复


if __name__ == "__main__":
    # === 单实例锁：同一时间只允许运行一个护眼程序 ===
    if IS_WINDOWS:
        kernel32 = ctypes.windll.kernel32
        mutex = kernel32.CreateMutexW(None, False, "EyeCarePro_SingleInstance")
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            sys.exit(0)

    app = EyeCareApp()
    app.mainloop()
