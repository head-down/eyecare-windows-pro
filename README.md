# `eyecare/eyecare_windows_pro_v1.0.2.py` — 护眼定时休息提醒

[![GitHub stars](https://img.shields.io/github/stars/head-down/eyecare-windows-pro?style=flat)](https://github.com/head-down/eyecare-windows-pro/stargazers)
[![GitHub license](https://img.shields.io/github/license/head-down/eyecare-windows-pro?style=flat)](https://github.com/head-down/eyecare-windows-pro/blob/master/LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue?style=flat)](https://github.com/head-down/eyecare-windows-pro)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue?style=flat&logo=python)](https://python.org)
[![Status](https://img.shields.io/badge/status-active-brightgreen?style=flat)](https://github.com/head-down/eyecare-windows-pro)

基于 customtkinter 的全屏遮罩式护眼提醒工具。

**工作流程：**
1. 初始化 `PhaseManager` 工作/休息阶段计时器，启动后台线程每秒轮询
2. 工作倒计时到期 → 自动切换为休息，弹出 `BreakOverlay` 全屏遮罩强制休息
3. 休息倒计时到期 → 自动切换为工作，关闭遮罩，累计护眼次数
4. `BreakOverlay` 使用 `overrideredirect(True)` 无边框 + Windows API `SetWindowPos` 每 2 秒重新抬升，防止其他程序抢占
5. `OpenInputDesktop` 检测锁屏时自动冻结计时，解锁后恢复
6. 跳过休息时累计跳过次数，超过阈值弹出健康提醒弹窗

**关键依赖：**
- `customtkinter` — 现代 GUI 框架（Dark 主题 UI）
- `pystray` + `Pillow` — 系统托盘图标
- `winreg` / `winsound` / `ctypes` — Windows API（内置）

**运行方式：**

```bash
/d/software/python/python -u eyecare/eyecare_windows_pro_v1.0.2.py
```

或直接运行打包好的 exe：

```
eyecare-dist/护眼助手WindowsPro.exe
```

**核心机制：**
- `BreakOverlay` 全屏遮罩窗口：使用 `overrideredirect` + `SetWindowPos` 强制置顶，**每 2 秒重新抬升**防止其他程序抢占
- 锁屏冻结：`OpenInputDesktop` 检测工作站锁屏状态，锁屏期间 `PhaseManager.freeze()` 暂停倒计时，解锁后补偿时间
- 单实例锁：Windows `CreateMutexW` Mutex 确保只运行一个实例
- 系统托盘：pystray + Pillow 实现，支持显示/隐藏主窗口、退出
- 配置持久化：`ConfigPersistence` 原子写入（先写 `.tmp` 再 `os.replace`），运行时自动生成 `config.json`
- 统计功能：今日/总计护眼次数、跳过次数，跨天自动清零今日统计
- 全局异常捕获：exe 打包后闪退时，自动在桌面生成 `eye_care_error.log` 错误日志

**配置区：**
- `config.work_min = 20` — 工作时长（分钟）
- `config.rest_min = 1` — 休息时长（分钟）
- `config.skip_threshold = 3` — 今日跳过提醒阈值（次）
- `config.auto_start = False` — Windows 开机自启（通过注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 写入 `EyeCarePro` 键值）

**版本差异：**
- v1.0.1：基础工作/休息切换 + 系统托盘 + 开机自启
- v1.0.2：增加统计、跳过提醒阈值、健康提醒弹窗、全局异常捕获

**依赖安装：**

```bash
/d/software/python/python -m pip install customtkinter pystray Pillow
```
