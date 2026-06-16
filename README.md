# 护眼助手 Windows Pro

定时休息提醒工具，基于 customtkinter 的全屏遮罩式护眼提醒。

## 功能

- **定时休息** — 可配置工作/休息时长，时间到弹出全屏遮罩强制休息
- **强制置顶遮罩** — 通过 Windows API `SetWindowPos` 每 2 秒重新抬升，防止其他程序抢占
- **系统托盘** — 最小化到托盘，支持显示/隐藏、退出
- **跳过统计** — 记录今日/总计跳过次数，超过阈值弹出健康提醒
- **锁屏检测** — 检测到锁屏自动冻结计时，解锁后恢复
- **暂停功能** — 手动暂停/恢复计时
- **开机自启** — 支持 Windows 注册表开机启动
- **单实例锁** — Windows Mutex 确保只运行一个实例
- **全局异常捕获** — exe 运行闪退时自动生成桌面错误日志

## 运行方式

### 方式一：直接运行 exe

下载 `eyecare-dist/护眼助手WindowsPro.exe`，双击运行。

### 方式二：Python 运行

```bash
pip install customtkinter pystray Pillow
python eyecare/eyecare_windows_pro_v1.0.2.py
```

## 配置

首次运行后会在同级目录生成 `config.json`：

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `work_minutes` | 工作时长（分钟） | 45 |
| `rest_minutes` | 休息时长（分钟） | 5 |
| `autostart` | 开机自启 | false |
| `total_rest_count` | 总计护眼次数 | 0 |
| `total_skip_count` | 总计跳过次数 | 0 |
| `today_rest_count` | 今日护眼次数 | 0 |
| `today_skip_count` | 今日跳过次数 | 0 |
| `skip_threshold` | 跳过提醒阈值 | 3 |

配置也可通过托盘右键 → 设置 修改。

## 环境要求

- **操作系统**: Windows 10/11
- **Python**: 3.8+（仅源码运行方式需要）

## 版本

- `v1.0.2` — 当前版本：统计功能、跳过提醒阈值、健康提醒弹窗、全局异常捕获
- `v1.0.1` — 基础版：工作/休息切换 + 系统托盘 + 开机自启
