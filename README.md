# MalusCallus

macOS 微信 **GUI 数据抓取桥**（无 AI 大脑）。仓库：[baitang-bt/MalusCallus](https://github.com/baitang-bt/MalusCallus)。

线协议与 [Callus-Bridge](https://github.com/baitang-bt/Callus-Bridge) / WeJamBot 宿主兼容：`package wejam.v1` / `service WeJam`。本机进程监听 `127.0.0.1:7701`，宿主设 `WEJAM_TARGET=127.0.0.1:7701` 即可换桥。

驱动本机已安装的 `WeChat.app`（Accessibility + CGEvent），**不**使用 Docker / Xvfb / OCR / 输入法。

## 第一版能力

| 能力 | 状态 |
|------|------|
| ListChats / ListMessages / WatchMessages / SendText | 实现（依赖 AX 内容树） |
| ReadLatest / DumpA11yTree / InvokeNode | 实现 |
| GetStatus / GetLoginState / WatchLogin | 实现（已登录 = 可读会话列表） |
| GetLoginQRCode / SubmitLogin / Logout | 未实现（人在微信里登录） |
| ReadContext / CaptureMessageMedia / GetBadges / InvokeMessage | 未实现 |

### 本机探测（2026-11-14）

当前 Mac 微信 4（`xinWeChat` + `WeChatAppEx` Chromium）**不向辅助功能暴露会话/消息/输入框**，主窗口 `AXChildren` 仅标题栏按钮。详见 [docs/probe.md](docs/probe.md)。在腾讯开放可访问树之前，收发 RPC 会返回 `ax_content_missing` / 明确失败信息；**不**改用 OCR。

## 权限

运行前必须给**启动本进程的应用**打开：

系统设置 → 隐私与安全性 → **辅助功能**（以及如系统要求则勾选 **输入监控**）

未授权时进程会立即退出并打印说明。

## 快速开始

```bash
cd /Users/max/Documents/Agent/projects/MalusCallus
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 先打开并登录微信，再：
python -m agent.main
```

另开终端：

```bash
WEJAM_TARGET=127.0.0.1:7701 python -m wejam.cli status
WEJAM_TARGET=127.0.0.1:7701 python -m wejam.cli chats
```

探测 AX 树（写选择器用）：

```bash
WEJAM_TARGET=127.0.0.1:7701 python -m wejam.cli dump-a11y > docs/probe-raw.txt
```

## 布局

```
agent/          # macOS AX + CGEvent + gRPC servicer
wejam/          # 线兼容客户端 + 生成 stub
callus/         # CaptureDriver 适配器（宿主可选）
proto/wejam/v1/ # 契约（与 Callus 同线）
tests/          # 纯解析单测（不碰微信）
```

## 与 Callus-Bridge 的关系

- 契约与客户端从 Callus 拷贝，字段号不变。
- Linux：AT-SPI + XTEST + Docker。macOS：AXUIElement + CGEvent + 本机进程。
- 停掉占用 `:7701` 的 `callus-session` 后再启 MalusCallus。
