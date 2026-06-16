# 护眼助手 (EyeCare)

[![GitHub stars](https://img.shields.io/github/stars/head-down/eyecare-windows-pro?style=flat-square&color=gold)](https://github.com/head-down/eyecare-windows-pro/stargazers)
[![GitHub license](https://img.shields.io/github/license/head-down/eyecare-windows-pro?style=flat-square&color=blue)](https://github.com/head-down/eyecare-windows-pro/blob/master/LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows-0078D6?style=flat-square&logo=windows)](https://github.com/head-down/eyecare-windows-pro)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue?style=flat-square&logo=python)](https://www.python.org/)
[![Status](https://img.shields.io/badge/status-working-brightgreen?style=flat-square)](https://github.com/head-down/eyecare-windows-pro)

基于 customtkinter 的全屏遮罩式休息提醒工具。定时弹出遮罩强制休息，防止长时间盯屏。

## 星标趋势

[![Star History Chart](https://api.star-history.com/svg?repos=head-down/eyecare-windows-pro&type=Date)](https://star-history.com/#head-down/eyecare-windows-pro&Date)

## 原理

- 后台线程每秒轮询倒计时，到期自动弹出全屏遮罩强制休息
- 遮罩使用 `overrideredirect(True)` 无边框窗口 + `SetWindowPos` 强制置顶，每 2 秒重新抬升防止全屏窗口抢占
- 锁屏期间自动冻结计时（`OpenInputDesktop` 检测），解锁后补偿冻结时长
- 跳过休息累计次数，超过阈值弹出健康提醒防止过度跳过

## 运行

```bash
cd eyecare
python eyecare_windows_pro_v1.0.2.py
```

## 依赖

```bash
pip install customtkinter pystray Pillow
```

## 配置

编辑 `eyecare_windows_pro_v1.0.2.py` 底部配置区，或通过托盘右键菜单 → 设置修改：

| 配置项 | 说明 |
|--------|------|
| `config.work_min` | 工作时长（分钟） |
| `config.rest_min` | 休息时长（分钟） |
| `config.skip_threshold` | 今日跳过提醒阈值（次） |
| `config.auto_start` | 是否开机自启 |

## 平台

仅限 Windows（依赖 `winreg`、`winsound`、`ctypes` 等 Windows 专属 API）。

## 许可证

MIT License - 眼睛是自己的，代码是公司的。
