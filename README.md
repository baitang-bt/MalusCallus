# MalusCallus

macOS 上的微信 **GUI 数据抓取桥**（无 AI 大脑）：本机 `WeChat.app` → Accessibility + CGEvent → gRPC `wejam.v1`（默认 `127.0.0.1:7701`）。

宿主把 `WEJAM_TARGET` 指到本进程即可换桥，与 Linux 侧 [Callus-Bridge](https://github.com/baitang-bt/Callus-Bridge) **线兼容**（`package wejam.v1` / `service WeJam` / 字段号不变）。

**不做**：Docker / Xvfb、OCR、经输入法输入、改微信指纹。扫码登录请在微信客户端完成。

## 相关仓库

| 仓库 | 角色 |
|------|------|
| [baitang-bt/MalusCallus](https://github.com/baitang-bt/MalusCallus) | **本仓**：macOS GUI 桥 |
| [baitang-bt/Callus-Bridge](https://github.com/baitang-bt/Callus-Bridge) | Linux GUI 桥（AT-SPI + Xvfb，日常 `:7701`）+ 搁置的 openclaw `:7702` |
| [Potatoblock-Dev/WeJamBot](https://github.com/Potatoblock-Dev/WeJamBot) | 宿主闲聊脑上游（眼睛/手契约 + bot） |
| [Potatoblock-Dev/WeJambBot_0x02](https://github.com/Potatoblock-Dev/WeJambBot_0x02) | 0x02 推送目标（微信侧产品仓） |
| [baitang-bt/0x01](https://github.com/baitang-bt/0x01) | QQ 官方机器人脑（文本脑谱系参考，非本桥依赖） |

关系简述：

```
WeChat.app (macOS) ──AX/CGEvent──► MalusCallus :7701 ──wejam.v1──► WeJamBot 宿主脑
WeChat (Linux/Docker) ──AT-SPI──► Callus-Bridge :7701 ──同协议──► 同一宿主
```

同一时刻只应有一个进程占用 `:7701`（先停 `callus-session` 再启本仓，或反过来）。

## 能力（v0.1）

| RPC / 能力 | 状态 |
|------------|------|
| ListChats / ListMessages / WatchMessages / SendText | 已实现（**依赖** AX 能暴露会话/消息/输入框） |
| ReadLatest / DumpA11yTree / InvokeNode | 已实现 |
| GetStatus / GetLoginState / WatchLogin | 已实现（「已登录」= 可读到会话列表） |
| GetLoginQRCode / SubmitLogin / Logout | 未实现（人在微信里登录） |
| ReadContext / CaptureMessageMedia / GetBadges / InvokeMessage | 未实现（Callus 有对等能力，本仓待 AX 树可用后再做） |

读消息经 gRPC 推给宿主，**桥进程不把聊天正文落盘**；裁图类路径在 Callus 侧会写媒体目录，本仓尚未实现裁图。

### 本机探测（2026-11-14）

当前 Mac 微信 4（`com.tencent.xinWeChat` + `WeChatAppEx` Chromium）**几乎不向辅助功能暴露业务 UI**：主窗口 `AXChildren` 多为标题栏按钮。详见 [docs/probe.md](docs/probe.md)。

在腾讯开放可访问树（或探测到可用节点）之前，收发会返回 `ax_content_missing` / 明确失败信息；**不**改用 OCR。复测：`python scripts/probe_ax.py`。

## 权限

给**实际启动本进程的应用**（终端 / Cursor / Python）打开：

系统设置 → 隐私与安全性 → **辅助功能**；若系统要求，再勾选 **输入监控**。

未授权时进程退出并打印说明，不空转。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"   # 网络慢可用清华源：-i https://pypi.tuna.tsinghua.edu.cn/simple

# 先打开并登录微信，再：
python -m agent.main
# 或：make serve
```

另开终端：

```bash
WEJAM_TARGET=127.0.0.1:7701 python -m wejam.cli status
WEJAM_TARGET=127.0.0.1:7701 python -m wejam.cli chats
```

接宿主脑（示例，仓在 WeJamBot / 0x02）：

```bash
WEJAM_TARGET=127.0.0.1:7701 python -m bot
```

探测 AX 树：

```bash
python scripts/probe_ax.py
# 或服务已启动时：
WEJAM_TARGET=127.0.0.1:7701 python -m wejam.cli dump-a11y
```

## 布局

```
agent/          # AX 遍历、CGEvent 输入、会话解析、gRPC servicer
wejam/          # 线兼容客户端 + 生成 stub（默认目标 :7701）
callus/         # CaptureDriver 适配器（与 Callus 宿主侧同形）
proto/wejam/v1/ # 契约（自 Callus 拷贝，字段号不变）
docs/probe.md   # Mac 微信 AX 探测结论
tests/          # 纯解析单测（不碰微信）
scripts/        # gen-proto、probe_ax
```

## 与 Callus-Bridge 的差异

| | [Callus-Bridge](https://github.com/baitang-bt/Callus-Bridge) | MalusCallus |
|--|--|--|
| 平台 | Linux 容器 + Xvfb | 本机 macOS |
| 驱动 | AT-SPI + XTEST | AXUIElement + CGEvent |
| 端口 | GUI `:7701`（主） | `:7701`（与 GUI Callus 互换） |
| 微信 | 容器内 Linux 版 | 已安装的 `WeChat.app` |
| 增量 RPC | ReadContext / Capture 等已齐 | v0.1 未实现，返回 `UNIMPLEMENTED` |

契约与 `wejam` / `callus` 客户端自 Callus 拷贝后演进；**不修改** Callus 或 WeJamBot 仓内的 bridge 实现。
