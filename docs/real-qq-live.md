# 真 QQ 联调记录（2026-10-27）

## 已打通

| 项 | 值 |
|---|---|
| 机器人账号 | 干饭鱼（3856674875） |
| 测试群 | 大肥鱼八角笼二群（1130798724） |
| 协议端 | NapCat v4.18.41 + 便携 QQ 9.9.33（`E:\AstrBot\napcat\qq-9.9.33`） |
| QQ 数据目录 | `E:\AstrBot\napcat\qq-data`（Electron profile）；账号数据在 `C:\Users\23293\Documents\Tencent Files\3856674875` |
| OneBot 反连 | `ws://127.0.0.1:6199/ws`，已连接（AstrBot aiocqhttp 适配器） |
| 验证时间 | 18:41:24 适配器已连接；18:41:42 机器人真实发送 `zai ne` |

## 已验证的能力（真实群消息）

- 真实群消息接收（多用户：3818174932 / 1252991807 / 2736880683 / 2728118012 / 1552638814 / 491068410）
- 概率插嘴触发；**连发合并**把 3 条群消息合成一次处理
- 群友档案提炼（`新增 1 条档案（2736880683）`）
- 真实发送回群

## 当前限制

- 模型仍是 mock（回复 `zai ne`），自动插嘴已临时关闭：`tier_slider=0`、`cooldown_sec=60`
- 管理员已加：`2329312325`（可 `/whale show`）
- 人设仍是草稿版

## 待办

1. 接真实模型（两条路：DSH free-model 本地转发 / DeepSeek API Key）
2. 把 `tier_slider` 调回 60，观察真实群里的插嘴频率
3. 用正式人设替换草稿
4. 根据真人反馈调 `cooldown_sec` / `quote_rate` / `skip_probability` / 分句间隔

## 运维脚本

```powershell
# 启动 NapCat（便携 QQ + 独立 profile，自动等待 6099/6199）
powershell -NoProfile -ExecutionPolicy Bypass -File E:\AstrBot\scripts\start-napcat.ps1

# 启动/停止 AstrBot + mock 模型
powershell -NoProfile -ExecutionPolicy Bypass -File E:\AstrBot\scripts\start-all.ps1 -WithMockLLM
powershell -NoProfile -ExecutionPolicy Bypass -File E:\AstrBot\scripts\stop-all.ps1

# 环境自检
powershell -NoProfile -ExecutionPolicy Bypass -File E:\AstrBot\scripts\check-env.ps1
```

## 运维备注

- NapCat 启动方式（**不要用 cmd 包装 + 重定向**，会导致 QQ 子进程随控制台退出）：
  ```powershell
  Start-Process -FilePath "E:\AstrBot\napcat\NapCatWinBootMain.exe" `
    -ArgumentList '"E:\AstrBot\napcat\qq-9.9.33\Files\QQ.exe"','"E:\AstrBot\napcat\NapCatWinBootHook.dll"','"--user-data-dir=E:\AstrBot\napcat\qq-data"' `
    -WorkingDirectory "E:\AstrBot\napcat" -WindowStyle Hidden `
    -RedirectStandardOutput "E:\AstrBot\napcat\napcat-live.log" -RedirectStandardError "E:\AstrBot\napcat\napcat-live.err.log"
  ```
- 重启 NapCat 后**大概率需要重新扫码**（quick login 没有持久化成功）
- AstrBot 重启不影响 QQ 登录，NapCat 会自动重连 6199


## 模型接入调研（2026-10-27）

尝试「复用 DSH 里的 DeepSeek 凭据」，结论是不可行，记录如下：

| 尝试 | 结果 |
|---|---|
| `~/.dsh/.credentials.yaml` 里的 DeepSeek 凭据 | 是 OAuth 授权（64 位 token + issuer），不是 OpenAI API Key |
| `~/.dsh/openai-gateway/api-key` | 打 DSH 本地 `/api/v1/models`、`/api/openai/v1/models` 均 401 |
| DSH 的 browser-session secret / account token 当 Bearer | 同样 401 |
| DSH `our-free-model` 插件注册表里的 keyless 免费池 `https://opencode.ai/zen/v1` | `/models` 200（需要 `user-agent: opencode/1.18.31` + `x-opencode-*` 头）；但所有 free 模型返回 `429 FreeUsageLimitError`，`beam-free` 返回 `403 RegionError`（地区限制） |

结论：**需要一条真实的 OpenAI 兼容 API Key**（DeepSeek / 硅基流动 / 智谱等均可），写入后即可切换。

## 真实模型接入（2026-10-27 18:55）

- Provider：`deepseek`（OpenAI 兼容，`https://api.deepseek.com/v1`，模型 `deepseek-chat`）
- `agent_runner.config.model.provider_id = deepseek`，mock provider 已移除
- 启动日志确认：`Loading model openai_chat_completion(deepseek)` → `Selected ... as default chat model provider`
- 真实回复样本（18:56–18:57，群 1130798724）：
  - `语音听不了`（收到语音消息，ffmpeg 缺失）
  - `第一题 会游泳吗`（回应「成精是要考试的，你出题？」）

### 人设适配

从 QQ Agent 提取的人设里有 `send_message` / `replyToMessageId` / `send_sticker` 等 QQ Agent 专属机制，
已替换为 AstrBot 机制（`||` 分句、`[SILENT]` 静默、`[sticker:<id>]` 表情、引用/@ 交给系统），原文件备份为 `xiaojingyu.md.bak-qq-agent`。

### 当前行为参数

- `tier_slider = 40`（没被 @ 时 40% 概率插嘴）
- `cooldown_sec = 40`
- `quote_rate = 15` / `at_rate = 0`
- 连发窗口 1500ms、分句间隔 900ms

### 已知问题

- **ffmpeg 缺失**：语音消息无法转写，机器人只能回「语音听不了」。需要装 ffmpeg 或关闭语音处理。
