import customtkinter as ctk
import tkinter as tk
import threading
import time
import sys
import os
import ctypes
import winsound
import json
import datetime
import traceback

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

# === 锁屏检测 ===
def is_workstation_locked():
    """Windows: 检测工作站是否已锁屏。OpenInputDesktop 仅在活动交互桌面上成功。"""
    if not IS_WINDOWS:
        return False
    hdesk = ctypes.windll.user32.OpenInputDesktop(0, False, 0)
    if hdesk:
        ctypes.windll.user32.CloseDesktop(hdesk)
        return False
    return True


# === 路径工具 (核心修复：确保打包后 config.json 读写在 exe 同级目录) ===
if getattr(sys, 'frozen', False):
    # 如果是打包后的 exe，使用 exe 所在的真实目录
    SCRIPT_DIR = os.path.dirname(sys.executable)
else:
    # 如果是直接运行 py 脚本，使用脚本所在目录
    SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))

CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")


# === 模块: PhaseManager ========================================================
class PhaseManager:
    """Work/Rest 阶段 + 倒计时 + 冻结

    interface:
      start_work() | start_rest()        切换阶段并重置倒计时
      freeze() | unfreeze()              暂停/锁屏期间冻结计时
      tick() -> bool                     返回 True 表示倒计时到期
      .phase  .time_left  .max_time      只读属性
    """
    def __init__(self, work_min, rest_min):
        self._work_sec = work_min * 60
        self._rest_sec = rest_min * 60
        self._phase = "Work"
        self._deadline = time.perf_counter() + self._work_sec
        self._frozen_at = None

    # -- 阶段切换 --
    def start_work(self):
        self._phase = "Work"
        self._deadline = time.perf_counter() + self._work_sec
        self._frozen_at = None

    def start_rest(self):
        self._phase = "Rest"
        self._deadline = time.perf_counter() + self._rest_sec
        self._frozen_at = None

    # -- 冻结（暂停/锁屏） --
    def freeze(self):
        if self._frozen_at is None:
            self._frozen_at = time.perf_counter()

    def unfreeze(self):
        if self._frozen_at is not None:
            self._deadline += time.perf_counter() - self._frozen_at
            self._frozen_at = None

    def tick(self):
        """返回 True 表示倒计时已到期（冻结期间始终返回 False）"""
        if self._frozen_at is not None:
            return False
        return time.perf_counter() >= self._deadline

    # -- 只读属性 --
    @property
    def phase(self):
        return self._phase

    @property
    def time_left(self):
        if self._frozen_at is not None:
            return max(0, int(self._deadline - self._frozen_at))
        return max(0, int(self._deadline - time.perf_counter()))

    @property
    def max_time(self):
        return self._work_sec if self._phase == "Work" else self._rest_sec

    @property
    def is_frozen(self):
        return self._frozen_at is not None


# === 模块: ConfigPersistence ==================================================
class ConfigPersistence:
    """配置读写 + Windows 自启管理

    interface:
      load() -> dict
      save(data: dict) -> None
      get_autostart() -> bool
      set_autostart(enable: bool) -> None
    """
    def __init__(self, config_path):
        self._path = config_path

    def load(self):
        if not os.path.exists(self._path):
            return {}
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self, data):
        try:
            tmp_path = self._path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
        except OSError:
            pass

    def get_autostart(self):
        if not IS_WINDOWS:
            return False
        reg_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_READ)
            try:
                winreg.QueryValueEx(key, "EyeCarePro")
                return True
            except (FileNotFoundError, OSError):
                return False
            finally:
                winreg.CloseKey(key)
        except (FileNotFoundError, OSError):
            return False

    def set_autostart(self, enable):
        if not IS_WINDOWS:
            return
        reg_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_WRITE)
            try:
                if enable:
                    app_path = f'"{sys.executable}"' if getattr(sys, "frozen", False) else f'python "{os.path.abspath(sys.argv[0])}"'
                    winreg.SetValueEx(key, "EyeCarePro", 0, winreg.REG_SZ, app_path)
                else:
                    try:
                        winreg.DeleteValue(key, "EyeCarePro")
                    except FileNotFoundError:
                        pass
            finally:
                winreg.CloseKey(key)
        except OSError as e:
            print(f"自启设置失败：{e}")


# === 配置管理 ===
class Config:
    """运行时配置，从 config.json 加载/保存"""
    def __init__(self):
        self.work_min = 20
        self.rest_min = 1
        self.is_running = True
        self.paused = False
        self.auto_start = False
        
        # === 统计字段 ===
        self.total_rest_count = 0       # 总计护眼次数
        self.total_skip_count = 0       # 总计跳过次数
        self.today_rest_count = 0       # 今日护眼次数
        self.today_skip_count = 0       # 今日跳过次数
        self.last_active_date = ""      # 上次活跃日期 (YYYY-MM-DD)
        self.skip_threshold = 3         # 今日跳过提醒阈值
        
        # === 强制模式 ===
        self.force_mode = False             # 强制休息模式开关
        self.force_mode_auto_triggered_date = ""  # 当天自动触发强制模式的日期 (YYYY-MM-DD)

config = Config()


def _get_screen_size():
    """获取主显示器物理像素分辨率"""
    if IS_WINDOWS:
        user32 = ctypes.windll.user32
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    root = tk.Tk()
    root.withdraw()
    w, h = root.winfo_screenwidth(), root.winfo_screenheight()
    root.destroy()
    return w, h


# === 1. 强制休息遮罩窗口 ===
class BreakOverlay:
    def __init__(self, parent, duration_sec, on_close=None, on_skip=None, forced=False):
        self.on_close = on_close
        self.on_skip = on_skip
        self._destroyed = False
        self._forced = forced

        self.window = tk.Toplevel(parent)
        self.window.overrideredirect(True)
        self.window.title("护眼模式")
        self.window.configure(bg="black")

        sw, sh = _get_screen_size()
        self.window.geometry(f"{sw}x{sh}+0+0")

        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", 0.85)
        self.window.resizable(False, False)

        self._force_topmost()

        if self._forced:
            self.window.protocol("WM_DELETE_WINDOW", lambda: None)
        else:
            self.window.protocol("WM_DELETE_WINDOW", self.skip)
            self.window.bind("<Escape>", lambda _e: self.skip())

        # 内容区：用 frame + place 实现全分辨率垂直居中
        self._content_frame = ctk.CTkFrame(self.window, fg_color="transparent")
        self._content_frame.place(relx=0.5, rely=0.5, anchor="center")

        self.lbl_msg = ctk.CTkLabel(
            self._content_frame, text="👀 强制休息中...",
            font=("Microsoft YaHei", 30, "bold"), text_color="white",
        )
        self.lbl_msg.pack(pady=(0, 10))

        self.lbl_time = ctk.CTkLabel(
            self._content_frame, text=str(duration_sec),
            font=("Consolas", 80, "bold"), text_color="#00FF00",
        )
        self.lbl_time.pack()

        if self._forced:
            self.lbl_forced = ctk.CTkLabel(
                self._content_frame, text="🔒 强制休息模式 — 本次无法跳过",
                font=("Microsoft YaHei", 14), text_color="#888888",
            )
            self.lbl_forced.pack(pady=(10, 0))
        else:
            self.btn_skip = ctk.CTkButton(
                self._content_frame, text="结束休息 (返回工作)", width=200, height=40,
                fg_color="transparent", hover_color="#333333", text_color="#888888",
                command=self.skip,
            )
            self.btn_skip.pack(pady=(30, 0))

        self.time_left = duration_sec
        self._after_id = None
        self._topmost_id = None
        self._start_countdown()
        self._start_keep_on_top()

    def _force_topmost(self):
        if not IS_WINDOWS: return
        try:
            hwnd = self.window.winfo_id()
            ctypes.windll.user32.SetWindowPos(
                hwnd, -1, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0040
            )
        except Exception: pass

    def _start_keep_on_top(self):
        def keep():
            if self._destroyed: return
            try:
                self.window.lift()
                self.window.attributes("-topmost", True)
            except Exception: return
            self._topmost_id = self.window.after(2000, keep)
        keep()

    def _start_countdown(self):
        def tick():
            if self._destroyed: return
            if is_workstation_locked() or config.paused:
                self._after_id = self.window.after(500, tick)
                return
            if self.time_left > 0:
                self.time_left -= 1
                self.lbl_time.configure(text=str(self.time_left))
                self._after_id = self.window.after(1000, tick)
            else:
                self.close()
        tick()

    def _cancel_timers(self):
        if self._after_id: self.window.after_cancel(self._after_id)
        if self._topmost_id: self.window.after_cancel(self._topmost_id)

    def close(self):
        if self._destroyed: return
        self._destroyed = True
        self._cancel_timers()
        self.window.destroy()
        if self.on_close: self.on_close()

    def skip(self):
        if self._destroyed: return
        self._destroyed = True
        self._cancel_timers()
        self.window.destroy()
        if self.on_skip: self.on_skip()
        if self.on_close: self.on_close()


# === 2. 主界面 ===
class EyeCareApp(ctk.CTk):
    TITLE = "护眼助手 Windows Pro"
    TRAY_TOOLTIP = "护眼助手 - 工作中"

    def __init__(self):
        super().__init__()

        self.title(self.TITLE)
        self.geometry("400x470")
        self.resizable(False, False)

        self.persistence = ConfigPersistence(CONFIG_PATH)
        self.load_settings()

        self.phases = PhaseManager(config.work_min, config.rest_min)
        self.overlay = None

        self._phase_switch_lock = threading.Lock()
        self._phase_switch_pending = False

        self._tray_icon = None
        self._screen_locked = False

        self.build_ui()
        
        # 窗口居中显示
        self.update_idletasks()
        w, h = 400, 470
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        
        self.start_timer()

        if HAS_SYSTRAY:
            self._setup_tray()

    # ==================== 托盘 ====================
    def _setup_tray(self):
        icon_image = self._create_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("显示/隐藏主窗口", self._tray_toggle, default=True),
            pystray.MenuItem("退出", self._tray_quit),
        )
        self._tray_icon = pystray.Icon("EyeCarePro", icon_image, self.TRAY_TOOLTIP, menu)
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

    @staticmethod
    def _create_tray_image():
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([4, 4, size - 5, size - 5], fill=(0, 150, 80, 255))
        draw.ellipse([14, 20, 50, 46], fill=(255, 255, 255, 255))
        draw.ellipse([26, 24, 38, 42], fill=(30, 30, 30, 255))
        draw.ellipse([30, 26, 34, 32], fill=(255, 255, 255, 200))
        return img

    def _tray_toggle(self, _icon=None, _item=None):
        self.after(0, self._toggle_window)

    def _toggle_window(self):
        if self.state() == "withdrawn":
            self.deiconify()
            self.lift()
            self.focus_force()
        else:
            self.withdraw()

    def _tray_quit(self, _icon=None, _item=None):
        if self._tray_icon: self._tray_icon.stop()
        self.after(0, self._do_quit)

    def _do_quit(self):
        config.is_running = False
        if self.overlay:
            self.overlay.close()
            self.overlay = None
        self.destroy()

    # ==================== 配置 ====================
    def load_settings(self):
        data = self.persistence.load()
        if data:
            config.work_min = max(data.get("work_min", 20), 1)
            config.rest_min = max(data.get("rest_min", 1), 1)
            config.total_rest_count = data.get("total_rest_count", 0)
            config.total_skip_count = data.get("total_skip_count", 0)
            config.today_rest_count = data.get("today_rest_count", 0)
            config.today_skip_count = data.get("today_skip_count", 0)
            config.last_active_date = data.get("last_active_date", "")
            config.skip_threshold = data.get("skip_threshold", 3)
            config.force_mode = data.get("force_mode", False)
            config.force_mode_auto_triggered_date = data.get("force_mode_auto_triggered_date", "")
        else:
            self.save_settings()

        self._check_new_day()
        config.auto_start = self.persistence.get_autostart()

    def _check_new_day(self):
        today_str = datetime.date.today().isoformat()
        if config.last_active_date != today_str:
            config.today_rest_count = 0
            config.today_skip_count = 0
            config.last_active_date = today_str
            
            # 跨日自动关闭强制模式
            if config.force_mode:
                config.force_mode = False
                config.force_mode_auto_triggered_date = ""

    # ==================== UI ====================
    def build_ui(self):
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        self.lbl_title = ctk.CTkLabel(
            self, text="状态：工作中 🖥️", font=("Microsoft YaHei", 20, "bold")
        )
        self.lbl_title.pack(pady=(20, 5))

        mins, secs = divmod(self.phases.time_left, 60)
        self.lbl_time = ctk.CTkLabel(
            self, text=f"{mins:02d}:{secs:02d}", font=("Consolas", 60, "bold")
        )
        self.lbl_time.pack()

        self.progress = ctk.CTkProgressBar(self, width=300, corner_radius=10)
        self.progress.set(0)
        self.progress.pack(pady=10)

        self.lbl_stats = ctk.CTkLabel(
            self, text=self._get_stats_text(),
            font=("Microsoft YaHei", 13), text_color="#AAAAAA", justify="center"
        )
        self.lbl_stats.pack(pady=(5, 5))

        # 健康提示标签（跳过 ≥ 阈值时显示）
        self.lbl_health_tip = ctk.CTkLabel(
            self, text="", font=("Microsoft YaHei", 12),
            text_color="#FF6B6B", justify="center",
        )

        frame_btn = ctk.CTkFrame(self, fg_color="transparent")
        frame_btn.pack(pady=5)

        self.btn_pause = ctk.CTkButton(
            frame_btn, text="⏸ 暂停", width=100, command=self.toggle_pause
        )
        self.btn_pause.pack(side="left", padx=10)

        self.btn_settings = ctk.CTkButton(
            frame_btn, text="⚙️ 设置", width=100,
            fg_color="#444444", hover_color="#555555", command=self.open_settings,
        )
        self.btn_settings.pack(side="left", padx=10)

        self.btn_reset_stats = ctk.CTkButton(
            frame_btn, text="🔄 重置", width=80,
            fg_color="#666666", hover_color="#777777", command=self.reset_stats,
        )
        self.btn_reset_stats.pack(side="left", padx=10)

        # 强制模式开关
        self.switch_force = ctk.CTkSwitch(
            self, text="强制模式", command=self._toggle_force_mode,
        )
        self.switch_force.pack(pady=(5, 10))
        if config.force_mode:
            self.switch_force.select()

        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.update_ui_loop()

    def _get_stats_text(self):
        return (f"今日  ✅ 护眼: {config.today_rest_count} 次   ⏭️ 跳过: {config.today_skip_count} 次\n"
                f"总计  ✅ 护眼: {config.total_rest_count} 次   ⏭️ 跳过: {config.total_skip_count} 次")

    def _update_stats_display(self):
        if hasattr(self, 'lbl_stats'):
            self.lbl_stats.configure(text=self._get_stats_text())
            if config.today_skip_count >= config.skip_threshold:
                self.lbl_stats.configure(text_color="#FF6B6B")
                self._show_health_tip()
            else:
                self.lbl_stats.configure(text_color="#AAAAAA")
                self._hide_health_tip()

    def _show_health_tip(self):
        if hasattr(self, 'lbl_health_tip') and self.lbl_health_tip.winfo_exists():
            self.lbl_health_tip.configure(
                text="⚠️ 长时间用眼请注意休息，每20分钟远眺20秒 🌿"
            )
            self.lbl_health_tip.pack(pady=(0, 5))

    def _hide_health_tip(self):
        if hasattr(self, 'lbl_health_tip') and self.lbl_health_tip.winfo_exists():
            self.lbl_health_tip.configure(text="")
            self.lbl_health_tip.pack_forget()

    def _toggle_force_mode(self):
        config.force_mode = not config.force_mode
        self.save_settings()

    def _sync_force_switch(self):
        """同步 CTkSwitch 状态到 config.force_mode（程序修改配置时调用）"""
        if hasattr(self, 'switch_force'):
            if config.force_mode:
                self.switch_force.select()
            else:
                self.switch_force.deselect()

    # ==================== 窗口隐藏 / 恢复 ====================
    def hide_to_tray(self):
        if HAS_SYSTRAY:
            self.withdraw()
        else:
            self._do_quit()

    # ==================== 计时器 ====================
    def start_timer(self):
        def timer_loop():
            while config.is_running:
                should_freeze = config.paused or is_workstation_locked()

                if should_freeze:
                    self.phases.freeze()
                else:
                    self.phases.unfreeze()
                    if self.phases.tick():
                        with self._phase_switch_lock:
                            if not self._phase_switch_pending:
                                self._phase_switch_pending = True
                                self.after(0, self._safe_phase_switch)

                self._screen_locked = is_workstation_locked()
                time.sleep(1)
        threading.Thread(target=timer_loop, daemon=True).start()

    def _safe_phase_switch(self):
        with self._phase_switch_lock:
            if not self._phase_switch_pending:
                return
        self.phase_switch()

    def phase_switch(self):
        if self.overlay:
            try: self.overlay.close()
            except Exception: pass
            self.overlay = None

        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)

        if self.phases.phase == "Work":
            self.phases.start_rest()
            self.lbl_title.configure(text="状态：休息中 🌿", text_color="green")
            self.overlay = BreakOverlay(
                self, self.phases.max_time,
                on_close=self._on_overlay_closed,
                on_skip=self._on_overlay_skipped,
                forced=config.force_mode,
            )
            self._update_tray_tooltip("休息中")
        else:
            self.phases.start_work()
            self.lbl_title.configure(text="状态：工作中 🖥️", text_color="#3B8ED0")
            self._update_tray_tooltip("工作中")
            
            config.total_rest_count += 1
            config.today_rest_count += 1
            self._update_stats_display()
            self.save_settings()

        with self._phase_switch_lock:
            self._phase_switch_pending = False

    def _on_overlay_closed(self):
        self.overlay = None

    def _on_overlay_skipped(self):
        config.total_skip_count += 1
        config.today_skip_count += 1

        # 检查是否需要自动触发强制模式（当天只触发一次）
        today_str = datetime.date.today().isoformat()
        if (config.today_skip_count >= config.skip_threshold
                and not config.force_mode
                and config.force_mode_auto_triggered_date != today_str):
            config.force_mode = True
            config.force_mode_auto_triggered_date = today_str
            self._sync_force_switch()

        self._update_stats_display()
        self.save_settings()

        self.phases.start_work()
        self.lbl_title.configure(text="状态：工作中 🖥️", text_color="#3B8ED0")
        self._update_tray_tooltip("工作中")

        with self._phase_switch_lock:
            self._phase_switch_pending = False

        if config.today_skip_count >= config.skip_threshold:
            self.after(500, self._show_health_reminder)

    def _show_health_reminder(self):
        reminder = ctk.CTkToplevel(self)
        reminder.withdraw()
        reminder.wm_attributes('-alpha', 0.0)
        reminder.title("⚠️ 用眼健康提醒")
        reminder.resizable(False, False)
        reminder.transient(self)
        reminder.attributes("-topmost", True)
        reminder.configure(fg_color="#2D2D2D")

        # 锚点定位（先隐藏，定位后再显示，避免闪烁）
        self.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 420) // 2
        y = self.winfo_y() + (self.winfo_height() - 220) // 2
        reminder.geometry(f"420x220+{x}+{y}")

        ctk.CTkLabel(reminder, text="⚠️", font=("Segoe UI Emoji", 40)).pack(pady=(20, 5))
        ctk.CTkLabel(
            reminder, text="请注意用眼健康！",
            font=("Microsoft YaHei", 18, "bold"), text_color="#FF6B6B",
        ).pack(pady=(0, 10))

        msg = (
            f"您今天已经跳过 {config.today_skip_count} 次休息了！\n\n"
            "为保护您的用眼健康，已自动开启「强制模式」\n"
            "下次休息时将无法跳过，请做好准备 🌿"
        )
        ctk.CTkLabel(
            reminder, text=msg, font=("Microsoft YaHei", 12),
            text_color="#CCCCCC", justify="center",
        ).pack(pady=(0, 15))

        ctk.CTkButton(
            reminder, text="我知道了，这次好好休息 👀", width=220,
            fg_color="#4CAF50", hover_color="#45A049", command=reminder.destroy,
        ).pack(pady=(0, 10))

        reminder.deiconify()
        reminder.grab_set()
        reminder.after(10, lambda: reminder.wm_attributes('-alpha', 1.0))

        if IS_WINDOWS:
            try: winsound.MessageBeep(winsound.MB_ICONHAND)
            except Exception: pass

    def reset_stats(self):
        confirmation = ctk.CTkToplevel(self)
        confirmation.withdraw()
        confirmation.wm_attributes('-alpha', 0.0)
        confirmation.title("确认重置统计")
        confirmation.resizable(False, False)
        confirmation.attributes("-topmost", True)
        confirmation.transient(self)

        # 锚点定位（先隐藏，定位后再显示，避免闪烁）
        self.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 400) // 2
        y = self.winfo_y() + (self.winfo_height() - 180) // 2
        confirmation.geometry(f"400x180+{x}+{y}")
        
        ctk.CTkLabel(
            confirmation, text="⚠️ 确认重置统计",
            font=("Microsoft YaHei", 18, "bold"), text_color="#FF6B6B",
        ).pack(pady=(20, 10))
        
        ctk.CTkLabel(
            confirmation, text="确定要清空所有（今日和总计）的统计数据吗？",
            font=("Microsoft YaHei", 14), text_color="#CCCCCC", justify="center",
        ).pack(pady=(0, 20))
        
        btn_frame = ctk.CTkFrame(confirmation, fg_color="transparent")
        btn_frame.pack(pady=(0, 15))
        
        def cancel():
            confirmation.destroy()
        
        def confirm():
            config.total_rest_count = 0
            config.total_skip_count = 0
            config.today_rest_count = 0
            config.today_skip_count = 0
            self._update_stats_display()
            self.save_settings()
            confirmation.destroy()
        
        ctk.CTkButton(
            btn_frame, text="取消", width=120,
            fg_color="#555555", hover_color="#666666", command=cancel
        ).pack(side="left", padx=10)
        
        ctk.CTkButton(
            btn_frame, text="确认重置", width=120,
            fg_color="#FF6B6B", hover_color="#FF5252", command=confirm
        ).pack(side="left", padx=10)

        confirmation.deiconify()
        confirmation.grab_set()
        confirmation.after(10, lambda: confirmation.wm_attributes('-alpha', 1.0))

        self.wait_window(confirmation)

    def _update_tray_tooltip(self, phase_text):
        if self._tray_icon and HAS_SYSTRAY:
            self._tray_icon.title = f"护眼助手 - {phase_text}"

    def update_ui_loop(self):
        if not self.winfo_exists():
            return

        today_str = datetime.date.today().isoformat()
        if config.last_active_date != today_str:
            config.today_rest_count = 0
            config.today_skip_count = 0
            config.last_active_date = today_str
            if config.force_mode:
                config.force_mode = False
                config.force_mode_auto_triggered_date = ""
                self._sync_force_switch()
            self._update_stats_display()
            self.save_settings()

        mins, secs = divmod(max(self.phases.time_left, 0), 60)
        self.lbl_time.configure(text=f"{mins:02d}:{secs:02d}")

        if self.phases.max_time > 0:
            progress_val = (self.phases.max_time - self.phases.time_left) / self.phases.max_time
            progress_val = max(0.0, min(1.0, progress_val))
            self.progress.set(progress_val)
            self.progress.configure(
                progress_color="green" if self.phases.phase == "Rest" else "#3B8ED0"
            )

        # 状态显示（优先级：暂停 > 锁屏 > 工作/休息）
        if config.paused:
            self.lbl_title.configure(text="状态：已暂停 ⏸️")
        elif self._screen_locked:
            self.lbl_title.configure(text="状态：已锁屏 🔒", text_color="#888888")
        else:
            self.lbl_title.configure(
                text=f"状态：{'工作中 🖥️' if self.phases.phase == 'Work' else '休息中 🌿'}",
                text_color="#3B8ED0" if self.phases.phase == "Work" else "green"
            )

        self.after(1000, self.update_ui_loop)

    # ==================== 暂停 ====================
    def toggle_pause(self):
        config.paused = not config.paused
        if config.paused:
            self.btn_pause.configure(text="▶️ 继续", fg_color="green")
            self.lbl_title.configure(text="状态：已暂停 ⏸️")
            self._update_tray_tooltip("已暂停")
        else:
            self.btn_pause.configure(text="⏸ 暂停", fg_color="#3B8ED0")
            self._update_tray_tooltip("工作中" if self.phases.phase == "Work" else "休息中")
            if self._screen_locked:
                self.lbl_title.configure(text="状态：已锁屏 🔒", text_color="#888888")
            else:
                self.lbl_title.configure(
                    text=f"状态：{'工作中 🖥️' if self.phases.phase == 'Work' else '休息中 🌿'}"
                )

    # ==================== 设置 ====================
    def open_settings(self):
        dialog = ctk.CTkToplevel(self)
        dialog.withdraw()
        dialog.wm_attributes('-alpha', 0.0)
        dialog.title("设置")
        dialog.resizable(False, False)
        dialog.transient(self)

        # 锚点定位（先隐藏，定位后再显示，避免闪烁）
        self.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 350) // 2
        y = self.winfo_y() + (self.winfo_height() - 380) // 2
        dialog.geometry(f"350x380+{x}+{y}")

        ctk.CTkLabel(dialog, text="工作时长 (分钟，≥1):", anchor="w").pack(fill="x", padx=20, pady=(15, 0))
        entry_work = ctk.CTkEntry(dialog)
        entry_work.insert(0, str(config.work_min))
        entry_work.pack(padx=40, fill="x", pady=5)

        ctk.CTkLabel(dialog, text="休息时长 (分钟，≥1):", anchor="w").pack(fill="x", padx=20, pady=(5, 0))
        entry_rest = ctk.CTkEntry(dialog)
        entry_rest.insert(0, str(config.rest_min))
        entry_rest.pack(padx=40, fill="x", pady=5)

        ctk.CTkLabel(dialog, text="今日跳过提醒阈值 (次):", anchor="w").pack(fill="x", padx=20, pady=(5, 0))
        entry_threshold = ctk.CTkEntry(dialog)
        entry_threshold.insert(0, str(config.skip_threshold))
        entry_threshold.pack(padx=40, fill="x", pady=5)

        lbl_error = ctk.CTkLabel(dialog, text="", text_color="red", font=("Microsoft YaHei", 11))
        lbl_error.pack(pady=(5, 0))

        self.var_autostart = ctk.BooleanVar(value=config.auto_start)
        chk_start = ctk.CTkCheckBox(dialog, text="Windows 开机自启", variable=self.var_autostart)
        chk_start.pack(pady=10, anchor="w", padx=20)

        def save_and_close():
            try:
                w = int(entry_work.get())
                r = int(entry_rest.get())
                t = int(entry_threshold.get())
                if w < 1 or r < 1:
                    lbl_error.configure(text="时长必须 ≥ 1 分钟")
                    return
                if t < 1:
                    lbl_error.configure(text="阈值必须 ≥ 1 次")
                    return
            except ValueError:
                lbl_error.configure(text="请输入有效的整数")
                return

            # 休息中保存设置时，先确认是否中断当前休息
            if self.phases.phase == "Rest" and self.overlay:
                _confirm_rest_interrupt(dialog, w, r, t)
                return

            _apply_settings(w, r, t)
            dialog.destroy()

        def _confirm_rest_interrupt(parent_dlg, w, r, t):
            """休息中改设置：弹确认框，避免误操作打断休息"""
            confirm_dlg = ctk.CTkToplevel(parent_dlg)
            confirm_dlg.withdraw()
            confirm_dlg.wm_attributes('-alpha', 0.0)
            confirm_dlg.title("⚠️ 确认中断休息")
            confirm_dlg.resizable(False, False)
            confirm_dlg.transient(parent_dlg)
            confirm_dlg.attributes("-topmost", True)
            confirm_dlg.configure(fg_color="#2D2D2D")
            confirm_dlg.geometry("380x200+" + str(parent_dlg.winfo_rootx() + 20) + "+" + str(parent_dlg.winfo_rooty() + 40))

            ctk.CTkLabel(
                confirm_dlg, text="⚠️ 当前正在休息中",
                font=("Microsoft YaHei", 16, "bold"), text_color="#FF6B6B",
            ).pack(pady=(20, 5))
            ctk.CTkLabel(
                confirm_dlg, text="修改设置将结束本次休息，\n确定要继续吗？",
                font=("Microsoft YaHei", 13), text_color="#CCCCCC", justify="center",
            ).pack(pady=(0, 15))

            btn_frame = ctk.CTkFrame(confirm_dlg, fg_color="transparent")
            btn_frame.pack()

            def _do_apply():
                _apply_settings(w, r, t)
                confirm_dlg.destroy()
                parent_dlg.destroy()

            def _cancel():
                confirm_dlg.destroy()

            ctk.CTkButton(btn_frame, text="取消", width=110,
                          fg_color="#555555", hover_color="#666666", command=_cancel).pack(side="left", padx=10)
            ctk.CTkButton(btn_frame, text="确认中断休息", width=140,
                          fg_color="#FF6B6B", hover_color="#FF5252", command=_do_apply).pack(side="left", padx=10)

            confirm_dlg.deiconify()
            confirm_dlg.grab_set()
            confirm_dlg.after(10, lambda: confirm_dlg.wm_attributes('-alpha', 1.0))

        def _apply_settings(w, r, t):
            config.work_min = w
            config.rest_min = r
            config.skip_threshold = t
            config.auto_start = self.var_autostart.get()
            self.save_settings()

            # 用新参数重建 PhaseManager
            self.phases = PhaseManager(w, r)

            # 如果当前在休息，关掉遮罩
            if self.overlay:
                self.overlay.close()
                self.overlay = None

            with self._phase_switch_lock:
                self._phase_switch_pending = False

        btn_save = ctk.CTkButton(dialog, text="保存并应用", command=save_and_close)
        btn_save.pack(pady=10)

        dialog.deiconify()
        dialog.grab_set()
        dialog.after(10, lambda: dialog.wm_attributes('-alpha', 1.0))

    def save_settings(self):
        data = {
            "work_min": config.work_min,
            "rest_min": config.rest_min,
            "total_rest_count": config.total_rest_count,
            "total_skip_count": config.total_skip_count,
            "today_rest_count": config.today_rest_count,
            "today_skip_count": config.today_skip_count,
            "last_active_date": config.last_active_date,
            "skip_threshold": config.skip_threshold,
            "force_mode": config.force_mode,
            "force_mode_auto_triggered_date": config.force_mode_auto_triggered_date,
        }
        self.persistence.save(data)
        self.persistence.set_autostart(config.auto_start)


if __name__ == "__main__":
    try:
        # === 单实例锁 ===
        if IS_WINDOWS:
            kernel32 = ctypes.windll.kernel32
            mutex = kernel32.CreateMutexW(None, False, "EyeCarePro_SingleInstance")
            if kernel32.GetLastError() == 183:
                sys.exit(0)

        try:
            app = EyeCareApp()
            app.mainloop()
        finally:
            if IS_WINDOWS:
                kernel32.CloseHandle(mutex)
        
    except Exception as e:
        # === 全局异常捕获：打包后如果闪退，会在桌面生成错误日志 ===
        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
        log_path = os.path.join(desktop_path, "eye_care_error.log")
        
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"护眼助手错误报告 - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*50 + "\n")
            f.write(f"错误类型: {type(e).__name__}\n")
            f.write(f"错误信息: {str(e)}\n")
            f.write("\n堆栈跟踪:\n")
            f.write(traceback.format_exc())
            f.write("\n系统信息:\n")
            f.write(f"Python版本: {sys.version}\n")
            f.write(f"打包状态: {'已打包' if getattr(sys, 'frozen', False) else '未打包'}\n")
            f.write(f"运行目录: {SCRIPT_DIR}\n")
            
        print(f"\n程序启动失败！错误日志已保存至桌面: {log_path}")
        time.sleep(10)  # 保持黑框10秒以便查看