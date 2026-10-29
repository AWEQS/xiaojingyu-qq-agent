# 切到真 QQ 的 checklist（NapCat + 小号）

> 目标：把当前「mock QQ ↔ AstrBot ↔ mock 模型」换成「真 QQ ↔ AstrBot ↔ 真模型」。
> 预计 10~20 分钟，其中 5 分钟是 QQ 登录和扫码。

## 0. 前提确认

- [ ] 有一个可以牺牲的 **小号 QQ**（非官方协议有风控风险，别用主号）
- [ ] 决定用 **NapCat**（而不是复用 QQ Agent 的 SnowLuma）
- [ ] 小号不要和 QQ Agent 当前登录的号相同（同一时间只能一个协议端）

## 1. 装 NapCat

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File E:\AstrBot\scripts\install-napcat.ps1
```

然后手动：

- [ ] 双击 `E:\AstrBot\napcat-installer\NapCatInstaller.exe`，安装目录填 `E:\AstrBot\napcat`
- [ ] 进 `E:\AstrBot\napcat\NapCat.*.Shell`，双击 `napcat.bat`
- [ ] 扫码登录**小号**
- [ ] 记下 NapCat WebUI 地址（默认 `http://127.0.0.1:6099`）和 token

## 2. 配 OneBot 反连（关键一步）

在 NapCat WebUI → 网络配置 → **新建 WebSocket 客户端（反向 WS）**：

| 项 | 值 |
|---|---|
| URL | `ws://127.0.0.1:6199/ws` |
| 消息格式 | `array` |
| Token | 留空（AstrBot 侧 `ws_reverse_token` 也是空） |
| 重连间隔 | 3000 |

AstrBot 侧对应配置在 `E:\AstrBot\data\cmd_config.json` 的 `platform[0]`：
`type=aiocqhttp, ws_reverse_host=0.0.0.0, ws_reverse_port=6199, ws_reverse_token=""`。

- [ ] 保存后，AstrBot 日志出现 aiocqhttp 连接事件

## 3. 验证

- [ ] 小号 QQ 私聊机器人发一句"在吗" → 应回复（mock 客户端不再需要）
- [ ] 拉小号进一个测试群，群里 @ 机器人 → 应回复
- [ ] 群里不 @、发关键词"小鲸鱼" → 应触发
- [ ] 连发几句 → 只回一次（连发合并）
- [ ] 模型回 `[SILENT]` 时不回（需要真人/真模型才能测）

## 4. 换成真模型

- [ ] WebUI → 服务提供商 → 新建 OpenAI 兼容提供商，填 Base URL + Key（DeepSeek 即可）
- [ ] 设为默认（`provider_settings.default_provider_id`）
- [ ] 发消息验证真实回复

## 5. 上线前收紧

- [ ] 白名单：只允许你的群/好友（`platform_settings.enable_id_white_list` 或插件层）
- [ ] `/whale show` 确认本群 tier/冷却符合预期
- [ ] 建议先用小号在 1 个测试群跑 1~2 天，再拉进真群

## 回滚

- 停 `napcat.bat`；AstrBot 侧可临时把 mock 客户端接回去（`mock\onebot-mock.mjs`）
- 不想动配置就保留 `platform` 里的 aiocqhttp 条目，它连不上不影响 WebUI

## 已知坑

1. **端口冲突**：SnowLuma（QQ Agent 内置）占 `3000/3001`。NapCat 默认也用 3000/3001，务必改（或只配反向 WS，不用正向端口）。
2. **版本匹配**：NapCat 与 QQ 版本强相关；登录失败优先怀疑版本，不是账号。
3. **风控**：非官方协议，别在主号上用；频繁加群/群发更危险。
4. **EULA**：NapCat 开源可改；SnowLuma 是第三方专有组件，别混用/再分发。
