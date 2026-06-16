## `eyecare/eyecare_windows_pro_v1.0.2.py` — 护眼定时休息提醒

[![GitHub stars](https://img.shields.io/github/stars/head-down/eyecare-windows-pro?style=flat)](https://github.com/head-down/eyecare-windows-pro/stargazers)
[![GitHub license](https://img.shields.io/github/license/head-down/eyecare-windows-pro?style=flat)](https://github.com/head-down/eyecare-windows-pro/blob/master/LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue?style=flat)](https://github.com/head-down/eyecare-windows-pro)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue?style=flat&logo=python)](https://python.org)
[![Status](https://img.shields.io/badge/status-active-brightgreen?style=flat)](https://github.com/head-down/eyecare-windows-pro)

基于 customtkinter 的全屏遮罩式护眼提醒工具。

**工作流程：**
1. 初始化 `PhaseManager` 工作/休息计时器，后台线程每秒轮询 `tick()` 检查倒计时
2. 工作倒计时到期 → 自动切换到休息，弹出 `BreakOverlay` 全屏遮罩（`overrideredirect(True)` + `SetWindowPos` 强制置顶，每 2 秒重新抬升）
3. 休息倒计时到期 → 自动切换回工作，关闭遮罩，累计护眼次数
4. `OpenInputDesktop` 检测锁屏状态，锁屏期间 `PhaseManager.freeze()` 冻结计时，解锁后补偿时间
5. 跳过休息时累计跳过次数，超过 `skip_threshold` 阈值弹出健康提醒弹窗

**关键依赖：**
- `customtkinter` — 现代 GUI 框架（Dark 主题）
- `pystray` + `Pillow` — 系统托盘图标
- `winreg` / `winsound` / `ctypes` — Windows API（内置）

**运行方式：**

```bash
cd eyecare
/d/software/python/python -u eyecare_windows_pro_v1.0.2.py
```

或直接运行打包好的 exe：

```bash
cd eyecare-dist
./护眼助手WindowsPro.exe
```

**配置区：**
- `config.work_min = 20` — 工作时长（分钟）
- `config.rest_min = 1` — 休息时长（分钟）
- `config.skip_threshold = 3` — 今日跳过提醒阈值（次）
- `config.auto_start = False` — Windows 开机自启（通过注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 写入 `EyeCarePro` 键值）

**单实例锁与全局异常捕获：**
- `CreateMutexW("EyeCarePro_SingleInstance")` 确保只运行一个实例，重复启动时 `GetLastError() == 183` 直接退出
- exe 打包后闪退时，全局 `except` 捕获异常，在桌面生成 `eye_care_error.log`（含错误类型、堆栈跟踪、Python 版本、打包状态）
