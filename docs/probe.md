# Mac 微信 AX 探测记录（2026-11-14）

## 环境

- 本机：`WeChat.app`（`com.tencent.xinWeChat`，pid 例：714）
- 附属：`com.tencent.flue.WeChatAppEx` + `WeChatAppEx Helper (Renderer)`（Chromium）
- `AXIsProcessTrusted()` = true（已开辅助功能）
- 原始 dump：`docs/probe-raw.txt`（gitignore，可本地再生成）

## 结论

**主窗口不向 Accessibility 暴露会话列表、消息列表或输入框。**

`AXWindow "微信"` 的 `AXChildren` 只有三个交通灯按钮（关闭 / 最小化 / 全屏）。  
`AXSections` 里的「内容」(AXContent) 指向同一窗口，无更深业务节点。

对下列进程做 `walk(max_depth=6)` 后，带标签且非菜单的节点只有：

| 进程 | 有意义节点 |
|------|------------|
| xinWeChat | `AXApplication/AXWindow "微信"`，帮助菜单里的 `AXTable "搜索结果"` |
| WeChatAppEx | 仅 `AXApplication "微信"`，无窗口 |
| Renderer helpers | 仅 helper 应用根，无窗口 |

尝试 `AXManualAccessibility` / `AXEnhancedUserInterface` → 错误 `-25205` / `-25208`（不支持）。

## 对 v0.1 的影响

按计划：**不改走 OCR / 剪贴板主路径**。  
在腾讯为 Mac 微信打开可访问树（或提供其它官方 GUI 钩子）之前：

- `ListChats` / `ListMessages` / `WatchMessages` / `SendText` / `ReadLatest` 无法对真实会话工作
- `DumpA11yTree` 仍可用于复测
- 登录态会停在 `unknown` + `chat_list_empty` / `ax_content_missing`

## 复测命令

```bash
source .venv/bin/activate
python scripts/probe_ax.py | tee docs/probe-raw.txt
```

若日后 dump 中出现带「会话 / 消息 / 输入」语义的 `AXList` / `AXTextArea`，再把选择器写进 `agent/chat.py`（`MALUS_CHAT_LIST_TITLE` 等环境变量已预留）。
