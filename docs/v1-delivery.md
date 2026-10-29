# v1 交付说明（mock 链路）

> 交付状态：**功能 v1 在 mock 链路下完成并联调通过**；真 QQ 接入等待「协议端拍板 + 小号 QQ」。
> 位置：`E:\AstrBot`　WebUI：http://127.0.0.1:6185　OneBot 反连：`ws://127.0.0.1:6199/ws`

## 1. 架构

```
QQ 客户端（现在=mock 客户端 / 真机=NapCat）
   │ OneBot v11 反向 WS（6199）
   ▼
AstrBot v4.29.3（E:\AstrBot）
   ├─ persona_pack      人设文件热切换、按群绑定、快照回滚
   ├─ whale_behavior    触发档位/连发合并/静默/分句/引用@/戳一戳/潜水/去AI味/群级调档
   ├─ member_memory     群友档案提炼（回复后）→ 变化才注入（下轮）
   └─ sticker_pack      表情清单注入 → [sticker:id] → 图片消息
   │
   ▼ OpenAI 兼容 API（现在=mock LLM 18080 / 真机=DeepSeek 等）
LLM
```

## 2. 启停

```powershell
# 启动（带 mock 模型）
powershell -NoProfile -ExecutionPolicy Bypass -File E:\AstrBot\scripts\start-all.ps1 -WithMockLLM

# 只看状态
powershell -NoProfile -ExecutionPolicy Bypass -File E:\AstrBot\scripts\check-env.ps1

# 全部停止（只动 6185/6199/18080，不碰 QQ Agent）
powershell -NoProfile -ExecutionPolicy Bypass -File E:\AstrBot\scripts\stop-all.ps1
```

WebUI 初始账号 `astrbot`，密码见 `E:\AstrBot\run-stdout.log` 里的 `Initial password`。

## 3. 插件与关键配置

| 插件 | 版本 | 配置文件 |
|---|---|---|
| persona_pack | 0.1.0 | `data/config/astrbot_plugin_persona_pack_config.json` |
| whale_behavior | 0.5.0 | `data/config/astrbot_plugin_whale_behavior_config.json` + `groups.json` |
| member_memory | 0.2.0 | `data/config/astrbot_plugin_member_memory_config.json` |
| sticker_pack | 0.1.0 | `data/config/astrbot_plugin_sticker_pack_config.json` |

人设文件：`data/plugins/astrbot_plugin_persona_pack/personas/*.md`（保存即生效）。
表情库：`data/plugins/astrbot_plugin_sticker_pack/stickers/` + `index.json`。
群友档案：`data/plugins/astrbot_plugin_member_memory/memory/<群号>.json`。

## 4. 常用 QQ 指令（管理员）

| 指令 | 作用 |
|---|---|
| `/persona list` / `/persona use <名>` | 查看/切换本会话人设 |
| `/persona show` / `/persona history` / `/persona rollback <n>` | 查看、历史快照、回滚 |
| `/whale show` | 看本群生效配置（是否按群覆盖） |
| `/whale set <key> <value>` | 按群调档（tier_slider/cooldown_sec/quote_rate…） |
| `/whale reset` | 清除本群覆盖 |
| `/memory show` / `/memory clear` | 查看/清空自己的群友档案 |

## 5. 调参指南（"活人感"旋钮）

| 现象 | 调什么 |
|---|---|
| 太吵、每条都接 | 降 `tier_slider`（60→30）；加 `cooldown_sec`；开 `skip_probability` |
| 太冷淡、该说话不说 | 升 `tier_slider`；补 `keywords`；降 `cooldown_sec` |
| 回复像 AI 作文 | 确认 `sanitize` 开；在人设文件里加"短句/口语/别总结"规则；降 `max_segments` |
| 节奏太机械 | 加 `jitter_ms`；调 `segment_delay_ms` |
| 抢话/插话突兀 | 开 `burst_enabled`，调 `burst_window_ms`（1500~2500） |
| 引用太多 | 降 `quote_rate`（15→5） |

## 6. 测试与评测

```powershell
$node = 'E:\QQ Agent\resources\app\snowluma\node.exe'
# 单条
& $node E:\AstrBot\mock\onebot-mock.mjs --one-shot --no-at --send "deepseek zai ma" --timeout 25000
# 连发（测合并）
& $node E:\AstrBot\mock\onebot-mock.mjs --one-shot --no-at --burst "a|b|c" --gap 400 --timeout 25000
# 多人群聊场景 + 自动评测
$before=(Get-Content E:\AstrBot\mock\llm_requests.jsonl | Measure-Object -Line).Lines
& $node E:\AstrBot\mock\scenario-mock.mjs --scenario E:\AstrBot\mock\scenarios\multi.json --timeout 32000
& 'E:\AstrBot\tools\astrbot\Scripts\python.exe' E:\AstrBot\mock\eval_report.py $before
```

已验证项：关键词触发（非 @）、连发 3 条合并成 1 回、`[SILENT]` 静默、`||` 分句、引用/@、表情图片、`send_poke` 戳一戳、潜水概率、去 AI 味、人设 4/4 注入、档案按人隔离。

## 7. 切真 QQ（三步）

1. `scripts\install-napcat.ps1` → 双击 `NapCatInstaller.exe` → `napcat.bat` → 扫码登录**小号**
2. NapCat WebUI 新增反向 WS：`ws://127.0.0.1:6199/ws`，array，token 空
3. WebUI 里把模型 provider 换成真实 Key

详细步骤/回滚/坑：`docs\real-qq-checklist.md`。

## 8. 已知限制

- 模型当前是 mock，**回复内容不是小鲸鱼的真实风格**；需要真 Key 才能调"像不像"。
- 人设是草稿（从 QQ Agent  MIT 源码提取），等你发正式版。
- 档案注入了会留在会话历史里（已做"变化才注入"缓解，仍会缓慢累积）。
- 真 QQ 未接：能力都在 mock 上验证，协议端差异（表情/图片/戳一戳的字段）需真机复核。
- QQ 官方通道有审核/被动消息限制；NapCat 是非官方协议，建议小号。
