## `eyecare/eyecare_windows_pro_v1.0.2.py` — 护眼定时休息提醒

[![GitHub stars](https://img.shields.io/github/stars/head-down/eyecare-windows-pro?style=flat)](https://github.com/head-down/eyecare-windows-pro/stargazers)
[![GitHub license](https://img.shields.io/github/license/head-down/eyecare-windows-pro?style=flat)](https://github.com/head-down/eyecare-windows-pro/blob/master/LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue?style=flat)](https://github.com/head-down/eyecare-windows-pro)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue?style=flat&logo=python)](https://python.org)
[![Status](https://img.shields.io/badge/status-active-brightgreen?style=flat)](https://github.com/head-down/eyecare-windows-pro)

基于 customtkinter 的全屏遮罩式休息提醒工具。

**工作流程：**
1. 启动后通过 `ConfigPersistence.load()` 加载 `config.json`，初始化 `PhaseManager(work_min, rest_min)` 工作/休息计时器
2. 后台线程每秒调用 `PhaseManager.tick()`，到期自动切换：工作 → 休息（弹出 `BreakOverlay` 全屏遮罩），休息 → 工作（关闭遮罩并累计护眼次数）
3. `BreakOverlay` 使用 `overrideredirect(True)` 无边框窗口 + `SetWindowPos(hwnd, -1, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOOWNERZORDER)` 强制置顶，每 2 秒重新 `lift()` + `attributes("-topmost", True)` 防止全屏窗口抢占
4. 遮罩显示倒计时（`Consolas 80px` 绿色数字），倒计时归零自动关闭；可按 `Escape` 键或点击按钮跳过
5. `OpenInputDesktop` 检测锁屏状态，锁屏期间 `PhaseManager.freeze()` 冻结计时，解锁后 `unfreeze()` 补偿冻结时长

**关键依赖：**
- `customtkinter` — 现代 GUI 框架
- `pystray` + `Pillow` — 系统托盘图标
- `winreg` / `winsound` / `ctypes` — Windows API（内置）
- 配置文件：`config.json`（首次运行自动生成，`ConfigPersistence` 先写 `.tmp` 再 `os.replace` 原子写入）

**运行方式：**

```bash
cd eyecare
/d/software/python/python -u eyecare_windows_pro_v1.0.2.py
```

**配置区：**
- `config.work_min = 20` — 工作时长（分钟）
- `config.rest_min = 1` — 休息时长（分钟）
- `config.skip_threshold = 3` — 今日跳过提醒阈值（次）
- `config.auto_start = False` — Windows 开机自启（通过注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 写入 `EyeCarePro` 键值）
- `config.paused = False` — 是否暂停计时

**单实例锁与全局异常捕获：**
- 程序入口通过 `CreateMutexW("EyeCarePro_SingleInstance")` 创建命名 Mutex，`GetLastError() == 183` 时 `sys.exit(0)` 直接退出
- 根因：customtkinter 底层基于 tkinter，同进程重复初始化会导致 Tcl 解释器冲突；用 Windows 命名 Mutex 在系统级别保证互斥
- 全局 `except` 捕获未处理异常，在桌面生成 `eye_care_error.log`（含错误类型、堆栈跟踪、Python 版本、打包状态），防止 exe 模式静默闪退

**打包为 exe：**

```bash
/d/software/python/python -m pip install pyinstaller
cd eyecare
pyinstaller --onefile --windowed --name "护眼助手WindowsPro" eyecare_windows_pro_v1.0.2.py
```
