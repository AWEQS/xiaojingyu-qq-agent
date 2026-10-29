# 小鲸鱼 QQ Agent（AstrBot 版）

在 AstrBot 上搭建的「有活人感」QQ 群友机器人。当前处于 v1 开发中，已跑通「假 QQ ↔ AstrBot ↔ 假模型」全链路。

## 交付说明

完整交付文档见 [docs\v1-delivery.md](docs/v1-delivery.md)（架构/启停/配置/调参/评测/切真 QQ）。

## 快速开始

```powershell
# 启动（E 盘，数据目录 E:\AstrBot\data）
$env:ASTRBOT_ROOT='E:\AstrBot'
& 'E:\AstrBot\bin\astrbot.exe' run

# WebUI
# http://127.0.0.1:6185   用户名 astrbot，初始密码见 run*.log 里的 "Initial password"
# OneBot 反连入口（NapCat/SnowLuma 用）：ws://127.0.0.1:6199/ws
```

## 目录结构

| 路径 | 用途 |
|---|---|
| `E:\AstrBot\bin` | AstrBot 可执行文件（uv 生成） |
| `E:\AstrBot\tools` | AstrBot Python 环境 |
| `E:\AstrBot\data` | 运行数据（配置/插件/会话） |
| `E:\AstrBot\data\plugins\astrbot_plugin_persona_pack` | 人设插件（运行副本） |
| `E:\AstrBot\data\plugins\astrbot_plugin_whale_behavior` | 群聊行为插件（运行副本） |
| `E:\AstrBot\persona-pack` | 人设插件开发源码 + 单元测试 |
| `E:\AstrBot\plugins-src\astrbot_plugin_whale_behavior` | 行为插件开发源码 |
| `E:\AstrBot\mock` | 联调用 mock：OneBot 客户端、mock LLM、测试脚本 |
| `E:\AstrBot\scripts` | install-napcat.ps1（装协议端）、check-env.ps1（环境自检） |
| `E:\AstrBot\docs` | real-qq-checklist.md（切真 QQ 的完整步骤） |

## 插件一：persona-pack（人设热切换）

- 人设文件：`data/plugins/astrbot_plugin_persona_pack/personas/*.md`，**保存即生效**（按 mtime 热重载）
- QQ 指令（需管理员）：`/persona list | use <名字> | default <名字> | show | reload | history | rollback <序号>`
- 每次人设内容变化自动存快照到 `personas/.history/`，可回滚
- 每个群/私聊可绑定不同人设；绑定关系存在插件目录 `state.json`
- 单元测试：`python E:\AstrBot\persona-pack\test_persona_pack.py`

## 插件二：whale-behavior（群聊行为）

| 配置项 | 默认 | 作用 |
|---|---|---|
| `tier_slider` | 60 | 没被 @ 时的插嘴概率（0 只回 @，100 每条都接） |
| `keywords` | 小鲸鱼/鲸鱼/deepseek… | 命中直接触发 |
| `cooldown_sec` | 30 | 同群回复冷却 |
| `burst_enabled` / `burst_window_ms` | 开 / 1500 | 连发合并：等群友说完再一起回 |
| `split_enabled` / `split_marker` | 开 / `||` | 分句发送 |
| `segment_delay_ms` | 900 | 分句间隔 |
| `silence_token` | `[SILENT]` | 模型输出该标记则不发送 |
| `skip_probability` | 0 | 被触发后仍选择不回的百分比（看心情） |
| `jitter_ms` | 0 | 分句间隔随机抖动 |
| `sanitize` | 开 | 清 markdown/列表符号，去 AI 味 |
| `quote_rate` / `at_rate` | 15 / 0 | 引用原消息 / @ 发言者的概率 |

### 群级调档（v0.4）

不同群可以单独调，不影响全局；覆盖存 `data/plugins/astrbot_plugin_whale_behavior/groups.json`：

```
/whale show                 # 看本群当前生效配置
/whale set tier_slider 100  # 本群每条都接
/whale set cooldown_sec 0   # 本群不限冷却
/whale reset                # 清除本群覆盖
```

（需要管理员；实测：tier 设 0 后普通消息不回，设 100 后恢复回复，reset 后 `groups.json` 清空。）

## 插件三：member-memory（群友档案记忆）

- 每次回复后在后台调一次小模型，从发言里提炼稳定事实（偏好/身份/雷点/口癖），按 `(群号, 群友)` 存成 `data/plugins/astrbot_plugin_member_memory/memory/<群号>.json`
- 下轮对话把当前发言者的档案注入为额外上下文（`extra_user_content_parts`，不破坏系统提示缓存）
- 注入策略 `inject_mode`：`changed`（默认，档案变化时才注入，省 token）/ `always` / `off`
- 去重 + 限条数（默认 20）+ 限频率（同人 120s）
- 指令：`/memory show` 看自己的档案，`/memory clear` 清空（管理员）
- 实测：发言「我最近在学 Rust，也喜欢喝冰美式」→ 自动记下两条 → 下一轮日志 `注入 2 条档案（TesterA）`，请求体里出现「群友档案」块

## 插件四：sticker-pack（本地表情包）

- 表情库：`data/plugins/astrbot_plugin_sticker_pack/stickers/`，`index.json` 描述每个表情的适用场景
- 提示词里注入可用表情清单，模型在回复末尾写 `[sticker:<id>]`
- 发送前拆分：文字一条、表情作为图片消息一条（可配置间隔）
- 扩充方式：把图片丢进 `stickers/`，在 `index.json` 加一条 `{id, file, desc}` 即可

## 戳一戳

行为插件 v0.3 起支持：模型输出 `[poke]` 时，通过 OneBot `send_poke` 戳一下发言者（`poke_enabled` 可关）。

## 联调测试（无需真 QQ、无需模型 Key）

```powershell
# mock 模型（18080）
& 'E:\AstrBot\tools\astrbot\Scripts\python.exe' E:\AstrBot\mock\mock_llm.py

# 模拟群友发消息（连发合并场景）
$node = 'E:\QQ Agent\resources\app\snowluma\node.exe'
& $node E:\AstrBot\mock\onebot-mock.mjs --one-shot --no-at --burst 'aaa|deepseek bbb|ccc' --gap 400 --timeout 30000
```

已验证：关键词触发（非 @）、连发 3 条只回 1 次且文本合并、`[SILENT]` 静默、`||` 分句、`[reply][at]` 引用/@、表情图片、`send_poke` 戳一戳。

### 多人群聊回放

```powershell
$node = 'E:\QQ Agent\resources\app\snowluma\node.exe'
$before = (Get-Content E:\AstrBot\mock\llm_requests.jsonl | Measure-Object -Line).Lines
& $node E:\AstrBot\mock\scenario-mock.mjs --scenario E:\AstrBot\mock\scenarios\multi.json --timeout 32000
& 'E:\AstrBot\tools\astrbot\Scripts\python.exe' E:\AstrBot\mock\eval_report.py $before
```

报告见 `mock\scenario-report.md`：人设 4/4、档案按人隔离正确。

## 切真 QQ 前先跑自检

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File E:\AstrBot\scripts\check-env.ps1
```

它会打印端口占用、平台配置、四个插件、mock/NapCat 状态。确认后按 `docs\real-qq-checklist.md` 走。

## 待办

- [ ] 接入真实人设文本（替换从 QQ Agent 提取的草稿版）
- [ ] 接入真实模型 Key（当前指向 mock）
- [x] 记忆体系（按群友档案，v0.1 已跑通）
- [x] 表情包 / 戳一戳（sticker-pack + [poke]）
- [ ] NapCat + 小号真 QQ 联调
- [ ] 真实群调优










## 本地控制台（v0.1）

```powershell
# 启动（自动开浏览器）
powershell -NoProfile -ExecutionPolicy Bypass -File E:\AstrBot\scripts\start-console.ps1
# 或双击桌面「小鲸鱼控制台.bat」
# 地址：http://127.0.0.1:8787
```

面板：概览（状态/启停/机器人信息/消息量/插件）、人设编辑（保存即生效）、群聊行为滑条（保存并重启）、表情包预览、群友档案（可清空）、日志（AstrBot/NapCat 实时查看）、管理端入口（AstrBot 6185 / NapCat 6099 / 登录二维码）。

后端：`console/server.py`（纯 Python 标准库，零依赖，端口 8787）；前端：`console/web/`（原生 HTML/CSS/JS）。

## 桌面版（Electron 壳）

- 快捷方式：桌面「小鲸鱼.lnk」（目标 `E:\AstrBot\desktop\electron\electron.exe`，参数 `E:\AstrBot\desktop\app`）
- 或双击 `E:\AstrBot\desktop\启动小鲸鱼桌面版.bat`
- 它会自动确保 8787 控制台服务在跑，窗口内就是网页控制台；关窗只退出壳，AstrBot/NapCat 后台服务不受影响
- 壳代码：`desktop\app\main.js`（窗口 + 托盘 + 自动拉起控制台后端）；Electron 运行时在 `desktop\electron\`
- 注意：如果从带 `ELECTRON_RUN_AS_NODE=1` 的终端里启动，会被当成 Node 执行；用 bat 启动（已清该变量）或从桌面快捷方式启动即可

## 目录结构补充

```
E:\AstrBot\desktop\
├─ electron\           Electron 40 运行时
├─ app\                壳代码（main.js / package.json / icon）
└─ 启动小鲸鱼桌面版.bat
```

### 桌面壳的启停规则

| 动作 | 结果 |
|---|---|
| 打开桌面版 | 自动确保控制台服务 + 小鲸鱼（AstrBot/NapCat）运行；已运行则跳过 |
| 关闭窗口 | 只退出外壳，小鲸鱼继续在后台运行 |
| 托盘 → 启动/停止小鲸鱼 | 手动控制服务 |
| 托盘 → 退出并停止小鲸鱼 | 二次确认后停止 AstrBot + NapCat 再退出（下次启动需重新扫码） |
| 托盘 → 退出（保留服务） | 只退壳 |

### 表情包管理（控制台）

控制台 →「表情包」：

- **上传**：点「＋ 上传表情」，可多选 png/jpg/gif/webp（单张 ≤ 8MB），填描述/标签后上传
- **删除**：卡片上的「删除」会把图片移到 `stickers/.trash/`（可手动找回），并从 index.json 移除
- **改描述/标签**：直接影响模型挑表情的依据
- **热更新**：插件按 index.json 的 mtime 自动重载，增删后**无需重启 AstrBot**

接口：`POST /api/sticker/add`、`/api/sticker/delete`、`/api/sticker/update`。
注意：`index.json` 必须是无 BOM 的 UTF-8（插件按 utf-8 读；控制台已修正写入方式）。

### AI 自动识别标签（表情包）

控制台 →「表情包」→ 选择图片：

1. 勾选「AI 自动识别标签」（默认开）
2. 选图后会调用模型（DeepSeek vision）看图，自动生成「描述 + 标签」并填进输入框
3. **上传前可以改**描述和标签；上传后还能随时点「改描述」再改
4. 已有表情卡片上的「AI 识别」按钮：重新识别并让你确认/修改后覆盖

接口：`POST /api/sticker/auto-tag`（支持传 `data`（新图）或 `id`（已有表情））。
识别用的是 AstrBot 里已配置的模型 Key（`cmd_config.json` 的 provider），模型需支持图片输入。

### 批量上传

- 「＋ 选择图片」支持多选（Ctrl/Shift），一次选多张
- 每张都会单独调一次 AI 识别，缩略图下方显示识别状态
- 识别完成后，「上传 N 张」按钮启用；批量时每张用各自的 AI 描述/标签
- **点击任意缩略图**可以单独修改这张的描述/标签，再统一上传
- 识别是串行的（一张一调），张数多时需要等十几秒；期间上传按钮不可点
- 上传后仍可对每张点「改描述」二次修改

### 拖拽上传 / 文件夹导入

- 把图片或整个文件夹**拖进「表情包」页**即可：文件夹会递归读取子目录，自动过滤 png/jpg/gif/webp
- 或点「导入文件夹」，选目录后同样批量进队列
- 队列最多 50 张；识别期间上传按钮禁用，识别完可逐张点缩略图改描述/标签

### 标签分组 / 自动压缩 / 设置

**表情包按标签分组**
- 第一个标签决定分组；顶部标签条可筛选（全部 / 各标签计数）
- 改描述时可调标签顺序，第一个标签就是分组名

**上传自动压缩**
- 默认开，设置页可关；超过 512px 或 200KB 的图自动缩到 512px 内，无透明通道转 JPEG（质量 85），有透明转 PNG，动图跳过
- 实测 521KB 的原图压到 67KB

**设置页（控制台 → 设置）**
| 设置 | 作用 |
|---|---|
| 关闭窗口时 | 收到托盘 / 退出软件（都不影响小鲸鱼服务） |
| 开机自启动 | 在用户 Startup 目录创建 / 删除「小鲸鱼」快捷方式 |
| 上传自动压缩 | 控制上传时是否压缩图片 |

设置存在 `desktop\settings.json`，桌面壳关窗时实时读取，改完立即生效。

### 群友档案（控制台）

- 每个群一张卡片：群号、群友数、群笔记、每位群友的笔记
- 「清空」某个群友 → 若该群再无群友且无群笔记，**自动删除该群档案，卡片从 UI 消失**
- 「清空本群」→ 直接删除该群档案文件
- 空壳群档案（无群友、无笔记）在列表加载时自动清理，不会再显示空群

### 群友档案详情

- 列表只显示**群名**（从 NapCat 日志解析并缓存到 `data\console\group_names.json`，无名字时回退群号）和群友数
- 点群卡片 → 详情弹窗：群名称、**完整群号**、群笔记、群友列表
- 点群友 → 详情：昵称、**QQ 号**、所在群、记住的事，可单独清空
- 深链：`#memory/<群号>` 打开群详情，`#memory/<群号>/<QQ号>` 打开个人详情
- 空壳群（无群友无笔记）加载时自动清理

### 插件管理页（控制台 → 插件）

- 列表来自 AstrBot 官方 API（`/api/v1/plugins`），按「我的插件 / 内置插件 / 第三方插件」分组
- 每张卡片：显示名、目录名、版本、作者、描述、运行状态、功能重叠提示
- **开关**：调用 `PATCH /api/v1/plugins/enabled`，即时生效（无需重启 AstrBot）
- **重载**：调用 `POST /api/v1/plugins/reload`
- **设置**：读取插件的 `_conf_schema.json` 生成表单（bool→开关、int+slider→滑条、list→逗号分隔、text→多行），保存后写入配置并自动重载
- **高级面板**：自研插件可一键跳到人设/群聊行为/表情包/群友档案页
- 鉴权：控制台后端用 `data\cmd_config.json` 里的 `dashboard.jwt_secret` 自签 JWT，只在 127.0.0.1 内部调用，不落盘
- 深链：`#plugins/<插件名>` 直接打开该插件的设置弹窗

### 插件卸载

- 插件卡片右下角「卸载」（内置插件 astrbot / builtin_commands 不显示，后端也会拒绝）
- 弹窗里可选：
  - 同时删除插件配置文件（默认不勾）
  - 同时删除插件数据目录（默认不勾，谨慎）
- 卸载走 AstrBot 官方 `DELETE /api/v1/plugins/by-id`，删插件目录并同步列表
- 误删恢复：`plugins-src` 里有自研插件源码，拷回 `data/plugins` 后重启 AstrBot 即可

### 冲突提示（动态）

- 只有在**对方插件确实已安装**时，才在卡片上显示「⚠ 功能重叠」
- 对方已安装且启用 → 显示「禁用对方」一键处理按钮
- 对方未安装 → 不再显示为冲突，只在插件设置弹窗底部标注「同类方案（未安装）」
- 背景：之前用的是静态清单，把没装的插件也标成冲突，属于误报

### 应用图标

- 来源：用户提供的蓝发小鲸鱼形象图，用连通域抠图去掉了对话气泡，人物居中、白底圆角、右侧裁切边做了白渐变过渡
- 生成文件：
  - `desktop\app\icon.png`（512，Electron 窗口/托盘图标）
  - `desktop\app\icon.ico`（16~256 多尺寸，桌面快捷方式）
  - `console\web\logo.png`（控制台侧边栏 logo）
  - `console\web\favicon.ico`（浏览器标签页图标）
- 生成脚本：`mock\make_final_icon.py`（去气泡逻辑在 `mock\make_icon_clean.py`）


### 响应策略（控制台 → 响应策略）

**白名单**
- 开关打开后，只有名单内的群聊 / 私聊会被回复（连 @ 也会被拦截），其他会话完全静默
- 群白名单自动显示群名（来自 NapCat 日志缓存），私聊白名单显示 QQ 号
- 由 `whale_behavior` v0.6.0 在消息入口设置 `is_at_or_wake_command=False` 实现拦截

**峰谷时段分级响应**
- 默认按 DeepSeek 官方规则：北京时间周一至周五（不含法定节假日）9:00-12:00、14:00-18:00 为高峰，其余为空闲（周末全天低谷）；可自行增删时段（支持跨零点）
- 高峰 / 低谷分别选 1-4 级：
  | 等级 | 效果 |
  |---|---|
  | 极省 L1 | 只接受 @ / 关键词，不主动接话；system prompt 限制 ≤15 字 |
  | 省流 L2 | 主动插嘴概率 ×0.5；限制 ≤30 字、最多两条 |
  | 标准 L3 | 按行为插件原配置，无额外限制 |
  | 活跃 L4 | 插嘴概率 ×1.3（上限 100），允许自然多聊 |
- 策略存在 `data/plugins/astrbot_plugin_whale_behavior/policy.json`，插件按 mtime 热加载，保存后下条消息生效
- 接口：`GET /api/policy`、`POST /api/policy/save`

> DeepSeek 高峰/空闲时段与价格（官方）：[模型 & 价格 | DeepSeek API Docs](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)

### 白名单选择器 / 忽略开关

- 「从列表选」：直接读 QQ 真实列表——群聊来自 OneBot HTTP `get_group_list`，好友来自 `get_friend_list`（NapCat 本地 6198 接口）；QQ 未登录时回退到日志记录并在弹窗里提示
- 「忽略白名单」开关：打开后无视白名单全量回复（调试用），关闭则按名单拦截

### QQ 列表接口（白名单选择器）

- NapCat 的 OneBot 配置里启用了本地 HTTP 服务：`127.0.0.1:6198`（`config\onebot11_<QQ>.json` 的 `network.httpServers`，仅监听本机）
- 控制台用它取 `get_group_list` / `get_friend_list`，用于白名单选择器；登录后才监听
- 拿不到时回退扫描 NapCat/AstrBot 日志，并在选择器里提示「当前为日志记录」

### 聊天设置（原「群聊行为」）

- 页面重构为三段：触发 / 节奏 / 互动，带「安静·标准·活跃」预设和未保存提示
- 保存走 AstrBot 插件配置 API（`PUT /api/v1/plugins/config` + reload），不再重启整个 AstrBot
- **私聊同样生效**：总开关、连发合并、分句节奏、静默、去 AI 味、潜水、戳一戳、响应等级；私聊默认必回，不受触发档位/冷却影响
- **不回复群聊消息**（v0.6.1 新增）：打开后群里完全静默（连 @ 也不回），私聊不受影响；与「总开关」（仅停行为插件、被 @ 仍可能回复）区分开

### 语境 / 情绪判断（v0.7.0）

- 开关：聊天设置 → 「是否接话：语境与情绪」
- 触发（概率/关键词）之后、真正回复之前，额外调用一次小模型，带上最近 N 条群聊，判断话题是否严肃/悲伤/争吵、对方情绪、是否适合插话
- 判断结果 `reply=false` 时静默不回复；被 @ 仍会回复；私聊不走这个判断（默认必回）
- 判断失败或返回异常时**默认回复**（fail-open），不会因判断服务异常而集体沉默
- 默认关闭，开启后每条候选回复会多一次小模型调用（少量 token）
- 日志里会打印 `[whale-behavior] 语境判断：不接话（原因）`

### 表情包标签分类（UI 优化）

- 左侧「分类」栏：搜索框 + 全部 + 按数量排序的标签列表（带计数、可滚动、选中高亮）
- 右侧网格平铺显示，不再把 130 个标签挤成一片 chip；图片 `loading="lazy"` 懒加载
- 选中标签后顶部显示「分类 女仆 · 15 个」和「返回全部」
- 深链：`#stickers/<标签名>` 直接打开某个分类（标签需 URL 编码）
- 分类由每个表情的第一个标签决定，卡片「改描述」里调标签顺序即可换分类

### 智能发表情（sticker_pack v0.2.0）

聊天设置 →「表情包：什么时候发表情」：

| 设置 | 作用 |
|---|---|
| 智能发表情 | 每条回复先按频率/冷却筛，再让小模型结合语境和情绪判断"该不该发、发哪张"；严肃/悲伤/争吵时不发 |
| 表情频率上限 | 每条回复尝试发表情的最大概率（0 = 不自动发） |
| 同会话冷却 | 同一群/同一人两次自动表情的最小间隔 |
| 候选表情数 | 按关键词从 291 张库里挑多少张给模型选（太多费 token） |

- 模型仍保留手动 `[sticker:<id>]` 能力，显式指定的表情不受频率限制
- 自动选中后走原有发送逻辑：先发文字，再单独发一张表情
- 关闭时完全不产生额外调用

### 图标文件（当前版）

- `desktop\app\icon.png` / `icon.ico`：Electron 窗口/托盘/任务栏
- `desktop\app\icon-v2.ico`：桌面快捷方式专用（**换图标时用新文件名，绕过 Windows 图标缓存**）
- `console\web\logo.png` / `favicon.ico`：控制台
- 生成脚本：`mock\make_icon_v2.py`

### 主动聊天（whale_behavior v0.8.0）

聊天设置 →「主动聊天：没消息时也会找你」：

| 参数 | 默认 | 说明 |
|---|---|---|
| 主动找人聊天 | 关 | 开启后由后台循环按间隔主动发消息 |
| 生效对象 | 空 | 从 QQ 好友/群列表选，存 `private:QQ` / `group:群号` |
| 话题来源 | 随机混合 | `history` 接旧话题 / `share` 分享相关领域 / `mix` 随机 |
| 活跃时段 | 09:00-23:30 | 支持逗号分隔多段 |
| 最短/最长间隔 | 90/240 分钟 | 每次随机取区间值，避免过于规律 |
| 每个对象每天最多 | 6 条 | 防刷屏 |

- 聊天内容会记录到 `data/plugins/astrbot_plugin_whale_behavior/chat_history.json`（最近 80 条/会话），作为话题来源
- 发送状态/计数存 `proactive_state.json`，重启后不会立刻重复轰炸
- 插件激活时（AstrBot 启动/重载）自动拉起后台循环，不需要先收到消息；插件重载时会取消旧循环避免重复
- 每次主动消息 = 一次 LLM 调用（少量 token）


### 托盘菜单

- 菜单：显示控制台 / 在浏览器打开 / 启动小鲸鱼 / 重启 AstrBot / 退出（先隐藏界面→快速停服务→退出，约 1 秒，无弹窗）
- 该项已按用户要求回退到调整前


### 退出/重启竞态保护

- `isQuitting` 标记：退出过程中再次点启动，不会把隐藏窗口弹回来
- 启动二次确认：检测到端口在听后等 2.2 秒复查，避免「旧进程刚被杀、端口未释放」导致的假健康
- 退出等端口释放：fast-stop 后最多再等 1.5 秒，确认 6099/6199/6185/8787 都释放才 `app.exit`

### 合并判断调用（v0.9 优化）

- 「是否接话 + 是否发表情」合并为**一次**小模型调用：语境判断时顺带从候选表情里挑一张
- 判断结果通过 event extra `context_gate` 传给 sticker_pack，sticker 插件不再单独调用一次模型
- 未被 @ 的主动接话走合并路径；被 @ 的回复仍由 sticker 插件自行判断（不影响体验）
- 效果：每条主动回复少 1 次 API 调用

### 模型管理（管理端）

- 管理端 →「模型管理」：列出已配置模型（模型名/API Base/Key 掩码/当前），支持添加 / 切换 / 删除
- 支持切换默认模型（切换后自动重启 AstrBot，约 15 秒，不影响 QQ 登录）
- 支持添加 OpenAI 兼容接口的模型（ID/模型名/API Base/API Key）
- 正在使用的模型不能删除；至少保留一个模型；增删改后自动重启 AstrBot（约 15 秒）\n- 接口：`GET /api/models`、`POST /api/models/switch`、`POST /api/models/add`、`POST /api/models/delete`

### 语音包插件（astrbot_plugin_voice_pack v0.1.0）

- A+ 方案：Edge TTS（免费）+ 情绪路由 + silk 发送，失败自动回退文字
- 默认：12% 概率、≤20 字、同群冷却 300 秒、语音延迟 800ms 在文字后发
- 情绪来自 whale_behavior 语境判断的 mood（开心/平静/敷衍），映射不同音色与语速
- 配置：AstrBot 插件页 → astrbot_plugin_voice_pack → 设置
- 实测：mp3→wav→silk（5.74s）→ NapCat 发送 retcode 0

### 聊天记忆管理（控制台新页）

- 侧边栏新增「💬 聊天记忆」页
- **会话记忆**：列出 AstrBot 每个群/私聊的上下文（tokens、更新时间），可查看消息、删除单条（可恢复）、保存修改、清空消息、删除整个会话
- **主动聊天历史**：按对象显示条数，可单独清空或全部清空（`chat_history.json`）
- **群友档案**：一键跳转已有的成员长期记忆页
- 数据走 AstrBot 官方会话接口（`/api/v1/conversations`），修改即时生效
- 控制台接口：`/api/memory/chat`、`/chat/detail`、`/chat/save`、`/chat/delete`、`/memory/extra`、`/memory/proactive/clear`

### Angel Memory（长期记忆）与整理计时

- 插件：`astrbot_plugin_angel_memory` v2.0.2（已安装，provider 用 deepseek，未启用向量检索/重排）
- 本地改动：`core/sleep_schedule.py` 整理时间 **04:00 → 22:00**（原因：晚上关机，4 点跑不到）
- 升级插件会覆盖该改动，记录见 `docs/angel-memory-patch.md`
- 记忆数据：`data\plugin_data\astrbot_plugin_angel_memory\memory_center`
- 管理面板：AstrBot WebUI → 插件管理 → 天使之魂 → memory-dashboard
- 控制台概览「运行状态」新增**上次记忆整理**计时：显示距上次整理多久；**超过 48 小时**概览顶部出现黄色提醒横幅
- 接口：`/api/status` → `runtime.memory_sleep`（last_ts / hours_ago / overdue / scheduled_hour）

### 活人感第一批（whale_behavior v0.9.0）

- **作息**：默认 23:30–08:00 为睡觉时间；非 @ 的群消息不主动接话，@ 仍会回但语气困；主动消息在睡眠时段不发
- **每日小状态**：每天随机心情（精神不错/有点困/心情挺好/有点烦/社恐犯了）+ 精力 1-5，注入系统提示词影响语气，状态存 `daily_state.json`
- **迟到回应**：消息间隔超过 `late_ack_gap_sec`（默认 600 秒）后回复，有 `late_ack_probability`（45%）概率先补一句「刚在忙/刚看到」；睡眠时段用「刚醒…」
- 配置：聊天设置 →「作息与状态」分区；也可在插件配置里改
- 字段：sleep_enabled / sleep_start / sleep_end / daily_mood_enabled / late_ack_enabled / late_ack_gap_sec / late_ack_probability

### 活人感第二批（whale_behavior v0.10.0）

- **关系阶段**：亲密度 陌生(<31) / 熟悉(<101) / 亲近(<251) / 黏人(251+)，每收到一条消息 +1，每天上限可配（默认 30）；注入「和对方是什么关系、该怎么说话」
- **记得约定**：主动聊天时读 angel 记忆库（`memory_center/index/simple_memory.db`），挑含「约定/说好/下次/回头/还没…」的未完成记忆，自然提一句
- **发错再撤回**：概率触发（默认 8%，冷却 600 秒），先发一条打错的话，1 秒后撤回
- **随机拍一拍**：回复后有 5% 概率戳一下用户（冷却 300 秒）
- UI：聊天设置 →「关系与约定」「小动作」两个分区
- 字段：relationship_enabled / relationship_daily_gain_cap / promise_enabled / recall_enabled / recall_probability / recall_delay_sec / recall_cooldown_sec / poke_rate / poke_cooldown_sec
- 数据：`relationship.json`（亲密度）；约定读取 angel DB（只读）


### 活人感第三批（whale_behavior v0.11.0）

- **纪念日/生日祝福**：聊天设置里填写「是什么日子」+ 选日期 → 点「添加」；支持完整日期（自动算第几周年）和旧格式 `MM-DD:内容`；当天到 `anniversary_hour` 后主动祝福
- **天气关心提醒**：不再每天播报，改为天气变化时提醒（开始下雨/下雪、骤降 ≥ N℃、高温、低温），带伞/多穿点/多喝水这类关心话；检查间隔、阈值、同类冷却都可配（wttr.in，无需 Key）
- **发图片**：把图片放进插件目录 `images/`，开启 `image_enabled` 后按概率/冷却随机发一张
- 三者都发到「主动聊天 → 生效对象」里的目标；电脑没开机就跳过
- UI：聊天设置 →「纪念日与天气」「发图片」两个分区


### 和风天气（区县级精度）

- 配置：`weather_key`（和风 API Key）、`weather_host`（控制台设置里的 API Host，形如 xxxx.re.qweatherapi.com）、`weather_location`（精确到区县，如 浙江省杭州市余杭区）
- 和风 GeoAPI 当前 Key 无权限（403），改为**本地解析**：使用 QWeather 官方中国城市列表（`data\plugin_data\astrbot_plugin_whale_behavior\qweather_china.csv`，3580 条）把区县名解析成 LocationID，再调用天气接口
- 实测：`浙江省杭州市余杭区` → `101210106` → `晴 14℃，14~20℃`
- 无 Key 时自动回退 wttr.in（城市名）
- 天气变化提醒（下雨/下雪/降温/高温/低温）会自动使用区县级数据


### 自动改 QQ 签名（whale_behavior v0.13.0）

- 开关 `signature_enabled`、间隔 `signature_interval_hours`（默认 12 小时）
- 用当天心情 + 最近聊天记录让模型写一句 ≤20 字签名，通过 OneBot `set_qq_profile` 修改（昵称保持不变）
- 状态存 `signature_state.json`；需要 NapCat HTTP 6198 可用
- 实测：自动生成并更新为「困到灵魂出窍但还要撑住」


### QQ空间偶尔分享（whale_behavior v0.14.0）

- **不按死时间发**：关掉了 Qzone Ultra 自带的定时发说说（`trigger.publish_cron` 置空），改由 whale 插件判断
- **聊天后触发**：聊天结束 `qzone_chat_post_delay_min`（默认 12 分钟）后，AI 根据最近聊天判断「值不值得发」；值得才生成说说并发布，不值得输出 [NO] 跳过；每天上限 `qzone_chat_post_daily_cap`（默认 1 条）
- **每周随机日常**：每周随机挑 `qzone_weekly_days_min`–`max` 天（默认 3–4 天），在 `qzone_post_window_start`–`end`（默认 12:00–22:00）之间随机时间，结合当天心情 + 天气 + 最近聊天生成日常说说
- 发布走 Qzone Ultra daemon（`POST 127.0.0.1:18999/post`，secret 从插件 state.json 读取）
- 状态存 `qzone_post_state.json`（上周计划/已发日期/聊天触发时间）
- UI：聊天设置 →「🌐 QQ空间：偶尔分享」
- 实测：聊天触发发布 ✅、[NO] 跳过 ✅、每周计划 3 个不同日期 ✅、真实发布带天气日常 ✅


### 用量统计（astrbot_plugin_usage_tracker v0.1.0 + 控制台页）

- 新插件在 Provider 层拦截 `text_chat`，记录**所有** LLM 调用：主对话、主动消息、签名、说说生成、记忆整理等（含插件 `context.llm_generate`）
- 记录字段：时间、模型、输入（缓存未命中/命中）、输出；写 `data/plugin_data/usage_tracker/usage.jsonl`
- 控制台新增「📊 用量统计」页：
  - 今日 / 近 7 天 / 近 30 天：tokens、缓存命中率、估算花费（¥ / $）
  - 近 14 天每日花费柱状图
  - 按模型汇总
- 计价：DeepSeek 官方 flash/pro 峰谷价（$/1M tokens），自动判断北京时间峰谷（周一~周五 9-12、14-18 为峰时），汇率 7.1
- 历史数据（tracker 安装前）来自 AstrBot `provider_stats`，只含主对话；新数据来自 tracker
- 接口：`GET /api/usage?days=30`


### 对话记录（每句 token + 实际提示词）

- 新页「🗒 对话记录」：左侧每条 LLM 调用（时间 / tokens / 用户消息预览 / 回复预览）
- 右侧详情：
  - 回复内容
  - 用户消息（prompt）
  - **AI 实际收到的系统提示词**（Provider 层抓取，已包含所有插件注入：人设、记忆、语境、状态、作息等）
  - 上下文（历史消息）
  - 可用工具列表
  - 本条 tokens 明细（命中/未命中/输出、命中率、估算花费）
- 数据：`data/plugin_data/usage_tracker/turns.jsonl`（单条字段超过 2 万字会截断；文件超 30MB 自动轮转）
- 接口：`GET /api/turns`、`GET /api/turns/detail?idx=N`



### 峰谷时段分级响应（policy v1.1）

- 响应策略页新增开关「峰谷时段分级响应」：
  - 开启（默认）：高峰/低谷分别用各自等级
  - 关闭：所有时段使用「固定响应积极度」（L1–L4），不随时间变化
- 固定等级与聊天设置里的「触发档位」独立：前者控制回复长度/接话意愿等级，后者控制主动插嘴概率
- policy.json 新增字段：`peak_valley_enabled`、`fixed_level`
- 接口：`/api/policy` 的 status 会返回当前模式与生效等级

### 模型名与版本显示

- AstrBot 配置里的模型名已从 `deepseek-chat` 改为精确 API id `deepseek-flash`
- 控制台会显示对应版本 **DeepSeek-V4.1-Flash-1017**（概览「当前模型」卡、运行信息、管理端模型管理）
- 原因：DeepSeek API 只接受模型 id（`deepseek-flash`/`deepseek-v4-pro` 等），直接填版本名会请求失败，所以用映射表展示详细版本
- `/api/models` 和 `/api/status` 的 model 信息新增 `version` 字段

### 表情候选与状态提示省 token（whale v0.15）

- 语境判断改为两段式：
  1. 先判断"要不要接话 / 要不要带表情"（不注入表情候选）
  2. 只有判断要带表情时，才第二次调用并注入 18 个候选选图
- 候选数量不变（仍 18），只是大多数消息不再为它付 token
- 新增开关「状态提示去重」（聊天设置 → 作息与状态，默认开）：
  - 开：动态状态/关系提示只在内容变化时注入，重复内容跳过
  - 关：恢复每轮都注入
- 实测：接话不带表情时 gate 只调 1 次、prompt 无候选；要表情时 2 次、第二次 18 条候选；去重开关行为符合预期

### 修复：表情描述无法修改（Electron prompt 不支持）

- 原因：编辑按钮用的是浏览器 `window.prompt()`；桌面壳 Electron 不支持该 API（直接抛错/返回空），所以点了没反应
- 修复：新增通用输入弹窗 `modalPrompt()`（暗色弹窗，支持多字段、Esc 取消、Ctrl+Enter 确定）
- 覆盖所有原先用 prompt 的入口：
  - 表情卡片「改描述」
  - 待上传表情点击编辑
  - 「AI 识别」后编辑结果
  - 人设页「新建人设」文件名
- 实测：点击改描述 → 弹窗出现 → 修改保存 → `/api/stickers` 回读描述已更新

### 控制台移除"发布说说"入口

- 按需求删掉控制台里的「发一条说说」卡片、发布按钮及对应 JS handler
- 后端 `/api/qzone/post` 接口一并移除
- 保留：空间状态、最近说说查看、刷新动态
- 自动发说说仍由 whale 插件 / qzone_ultra 负责，不受影响


### 动态生活时间线（whale v0.16）

- 每天自动生成一张生活时间线（约 8–12 段，07:00–23:30）
- 生成时参考：人设提示词（persona_pack 当前人设节选）、今天的心情/精力、最近聊天记录
- 结果存 `whale_behavior/life_timeline.json`，每天只生成一次（失败 10 分钟后重试）
- 每次对话注入当前状态，例如：
  `【她现在的生活】现在 18:59，她正在煮碗面吃，边看视频边放空。接下来 20:00 会洗个澡瘫床上刷剧不想动。`
- 深夜/时间线之外给「应该在休息或睡觉」的兜底
- 开关：聊天设置 → 作息与状态 →「动态生活时间线」（默认开）
- 控制台概览「运行状态」新增「今日生活」一行，显示当前活动和下一段
- 接口：`GET /api/life`

### 插件市场下放到控制台

- 侧边栏新增「🧩 插件市场」页
- 数据：AstrBot 官方市场 `/api/v1/plugins/market`（控制台代理，缓存 10 分钟）
- 功能：搜索（名字/作者/简介）、分类筛选、按下载量排序、安装按钮、已安装标记
- 安装：控制台调 AstrBot `/api/v1/plugins/install/url`，完成后自动刷新插件列表
- 接口：`GET /api/market?force=1`、`POST /api/market/install {id}`
- 实测：安装 `astrbot_plugin_simple_memory` 成功并可卸载；market 共 2873 个插件
- 注意：个别插件自身依赖缺失/元数据不合法会安装失败，错误会原样提示

### 生活时间线：聊天参考改为「近期私聊」

- 生活时间线生成时，第三处来源从"近期群聊缓冲"改为**只读近期私聊**（`private:*` 桶），群聊内容不再参与
- 按消息时间排序取最近 8 条；日志/提示词里也改为「最近私聊」
- 其余两处来源不变：人设节选、Angel 长期记忆

### 插件市场支持更新 / 卸载

- 已安装插件卡片显示：`已安装 vX`；若市场版本不同出现「更新 vY」；另有「卸载」
- 更新：`POST /api/market/update {id}` → AstrBot `/api/v1/plugins/update`
- 卸载：复用 `POST /api/plugins/uninstall`（删除配置和数据）
- 更新/卸载后自动刷新市场与插件列表
- ⚠️ 本地改过的插件（如 angel_memory 睡眠补丁、sticker_pack 自定义版）点更新会被市场版覆盖，操作前注意

### 本地改动插件标注

- 插件页与插件市场卡片给本地改过的插件加黄色标记「源码已改动，谨慎更新」（悬停显示具体改动）
- 当前标注：`astrbot_plugin_angel_memory`（睡眠整理改 22:00）、`sticker_pack`（自定义表情接口/字段）
- 市场里点「更新」时确认框会额外警告：更新会用市场版覆盖本地改动

### 主动消息优化（参考市场 Proactive Chat，whale v0.16）

- 沉默触发：`proactive_silence_min`（默认 25 分钟），对方最近没说话才允许主动
- 未回复计数与上限：`proactive_max_unanswered`（默认 4），达到后暂停并提示词带失落语气
- 提示词可配置：私聊/群聊各一套，支持 `{{current_time}}` `{{unanswered_count}}` `{{silence_minutes}}` `{{history}}`
- 分段发送：按标点拆 1–3 段，1.5–3.5 秒间隔（可关）
- 上下文包含 bot 自己的回复：`bot_history.json`
- 每对象独立策略：`proactive_overrides.json`（面板「策略」按钮编辑）
- 控制台「主动消息面板」：状态、下次倒计时、未回复数、立即发/策略/暂停/重置
- 接口：`GET /api/proactive/status`、`POST /api/proactive/action`、`POST /api/proactive/override`

### QQ空间优化（评论策略 + 说说配图）

- 评论策略：qzone_ultra 每轮最多评论 2 条（comment_latest_count=2），在最近约 6 条动态里**随机挑选**（本地补丁 random.shuffle），跳过自己的说说和已评论过的；cron 改为每 3 小时一轮（9-21 点，每天 5 轮）
- qzone_ultra 已标注为「源码已改动，谨慎更新」
- 说说配图：whale 发说说时按概率从 `whale_behavior/images/` 随机挑一张图一起发
  - 配置：`qzone_post_image_enabled`（默认开）、`qzone_post_image_rate`（默认 60%）
  - 控制台：聊天设置 → QQ空间 →「说说配图 / 带图概率」
  - 实测：带图发布成功（media_count=1），测试说说已删除

### 说说配图：AI 判断聊天图片（whale v0.16）

- 收到聊天图片时存入 `whale_behavior/chat_images/`（最多 80 张，只收白名单会话）
- 发说说时按「配图来源」策略挑图：
  - auto：优先从最近 24 小时聊天图片里用视觉模型逐张判断，合适就用；都不合适回退 `images/`
  - chat：只用聊天图片
  - local：只用本地 `images/`
- 视觉判断：把说说文本 + 图片一起给模型，输出 `{"usable": bool, "reason": ...}`，会排除隐私图/不相关图
- 控制台：聊天设置 → QQ空间 → 配图来源 / 允许用聊天图片 / 聊天图片时效
- 实测：AI 判断接受/拒绝逻辑通过；带图发布 `media_count=1` 验证通过

### 输入弹窗美化

- 通用输入弹窗（新建人设、改表情描述、主动消息策略等）统一美化：
  - 深色卡片 + 青色描边 + 弹入动画
  - 标签加粗、输入框 44px 高、聚焦青色光环
  - 底部说明做成信息条，主按钮渐变高亮
- 新建人设弹窗补充说明：创建后自动打开编辑器，文件名用于切换人设

### 人设删除

- 人设页编辑器右上角新增「删除」按钮
- 删除前自动备份到 `personas/.history/<name>__deleted-<时间>.md`
- 规则：至少保留一个人设；删除当前使用中的人设会自动切换到另一个并重载插件
- 列表里当前人设标注「使用中」
- 接口：`POST /api/persona/delete {name}`

### 聊天日记插件（memory_diary v0.1.0）

- 新插件 `astrbot_plugin_memory_diary`，与 Angel 长期记忆并行：
  - 每天 23:30 自动写一页日记（今天发生了什么 / 记住的事 / 情绪与约定）
  - 只记录白名单会话消息，保留 30 天
  - 聊到「上次/之前/那天/还记得」等线索时，检索最近日记，注入最多 450 字
  - 提供 `read_diary` 工具，模型可主动按日期/关键词翻日记
  - 数据：`data/plugin_data/memory_diary/diary.db`
- 控制台「聊天记忆」页新增「聊天日记」卡片，可查看/展开日记
- 接口：`GET /api/diary`


### Breeze TTS 2 语音（astrbot_plugin_breeze_tts v0.1.0）

- GPT-SoVITS 方案已完全移除（插件/数据/服务/脚本/桌面守护）
- 新插件调用 BreezeBlue 云端 API：
  - 控制台「聊天设置 → 语音（Breeze TTS 2）」配置 API Key、语音指令、概率/字数/冷却
  - 音色管理：列出账号音色、试听、使用、删除；上传 3–60 秒人声创建克隆音色
  - 回复命中时调 `/v1/text-to-speech/{voice_id}` 生成 wav → silk → QQ 语音
  - 接口：`/api/breeze/voices`、`/api/breeze/clone`、`/api/breeze/switch`、`/api/breeze/delete`、`/api/breeze/preview`
- 计费：$30/百万字符，Free 每天 400 积分（约 4000 字符）

### Breeze TTS 2 已跑通（v0.1.0）

- API：`xi-api-key` 认证，`POST /v1/text-to-speech/{voice_id}?output_format=wav_24000`
- 音色：`GET /v1/voices?language_code=zh`；克隆 `POST /v1/voice-previews/clone`（multipart 字段名 `files`）→ `/{generated_voice_id}/save`
- 实测：
  - 列表获取中文音色 ✅
  - 克隆测试音色成功（voc_ktyvtnv3j8gc），已删除释放槽位 ✅
  - 插件生成 wav → silk → QQ 语音发送 retcode 0（message_id 1164013399）✅
  - 当前使用音色：大肥鱼（迷糊版） voc_8yud7hz7c9q2
- 控制台 API Key 字段已改为密码框，保存后不再明文显示
- 注意：如果 Key 留空保存，会保持原 Key 不变


### 人设核心设定（persona core）

- 人设页新增「核心设定」区域，与完整人设文件分开存储：`personas/.core/<name>.md`
- 每轮 LLM 请求优先注入「核心设定」，再注入完整人设；压缩上下文时核心设定不会被裁掉
- 用户可手动编辑保存；每次修改自动留快照 `personas/.core/.history/`，支持历史查看与一键回滚
- AI 可通过工具 `propose_core_setting` 提交提议，写入 `.core/.pending/<name>.json`
- 提议不会直接生效：控制台「AI 提议」里点「通过」才追加进核心设定，点「忽略」丢弃
- 删除人设时一并清理核心设定、提议和快照

### 运营台（/api/ops/*）

- **她今天**：作息当前活动、心情/精力、最近日记、核心设定更新时间和待确认提议
- **健康自检**：AstrBot / NapCat / 控制台 / QQ空间 / Breeze Key / 插件配置字段 / 日志错误 / 磁盘 / 数据库
- **备份与恢复**：人设、核心设定、配置、插件数据、日记、主数据库打包 zip；保留 7 份；支持整包恢复，恢复前自动备份当前状态
- **成本与预算**：每日 token / 语音字符上限、提醒比例、今日用量与估算成本；Breeze 语音插件会按预算硬拦截
- **AI 味复盘**：扫描最近对外回复，标记「首先/其次/综上/作为 AI/过长」等 AI 味
- **隐私**：开启后全局把 5–12 位 QQ 号/群号显示成 ***
- **新手引导**：首次打开运营台自动出现，可随时重新运行
- **技术债**：功能拆到 `console/features.py` 和 `web/ops.js`；日志轮转；插件配置缺字段体检；桌面壳升级到 Electron 40

### 使用引导（新用户）

- 首次运行自动弹出（`data/console_features.json` 的 `guide_version < 2`），覆盖 8 步：
  1. 启动软件、NapCat 扫码登录 QQ
  2. 注册 DeepSeek、在 AstrBot 添加模型 Key
  3. 设置主人/管理员与白名单
  4. 选人设、写核心设定
  5. Breeze 语音（可选）
  6. QQ 空间（可选）
  7. 首次备份 + 隐私遮罩
  8. 私聊试聊验收
- 每步自动检查状态（QQ 登录、模型、白名单、核心设定、语音、空间、备份）
- 支持「跳过引导」；关闭窗口会缩成右下角「继续引导」浮标，不打断操作
- 设置页新增「使用引导」按钮，可随时重新打开
- 完成后写入 `guide_version=2`，不再自动弹出

### 记忆星图（astrbot_plugin_memory_starmap）

- 控制台新增「记忆星图」页：事实 → 星座 → 篇章，SVG 星图支持缩放/平移/点击看来源
- 后端 `console/starmap.py`：SQLite `data/plugin_data/memory_starmap/starmap.db`
- 数据流：日记 raw_messages → LLM 抽取 claims（待审核）→ 通过后归入星座/篇章
- 「从核心设定初始化」把核心设定里的条目直接点亮成星
- 每条 claim 保留 quote/日期/置信度，审核通过才进入聊天注入
- 插件 `astrbot_plugin_memory_starmap`：按话题关键词注入已审核记忆，并提供 `starmap_recall` 工具
- 抽取模型复用 `data/cmd_config.json` 里的 DeepSeek provider

### 记忆星图 v2：自动抽取 + 篇章摘要

- 自动抽取：控制台启动后每 30 分钟检查一次日记新消息，也可在星图页「自动抽取：开/关」切换
- Episode 摘要：审核通过记忆后自动用 LLM 写一段回忆片段；也可在篇章详情里手动重新生成
- 抽取来源：日记插件 `raw_messages`；LLM 复用 `data/cmd_config.json` 的 DeepSeek provider
- 检索：中文 2–4 字 N-gram 匹配，按命中数 + 置信度排序，注入已审核记忆
- 当前限制：还没做向量语义检索、实体别名合并和 Saga 长弧线

### 记忆星图 v4：别名撤销 + 加权检索

- 实体合并增加「合并记录」：每次合并保存被改动的 claims 快照，可点「撤销」恢复
- 撤销会恢复 subject/object、别名映射和保留项的原始引文；合并后的新记忆不受影响
- 检索权重：subject 2.6 / object 2.0 / predicate 1.2 / quote 0.5 + 置信度 0.5
- 审核通过时会自动生成一次篇章摘要；种子初始化不会逐条触发，避免等待

### 记忆星图 v5：本地向量检索

- 插件 `astrbot_plugin_memory_starmap` 增加本地 hashed n-gram 向量（320 维），不依赖外部 embedding 服务
- 检索分数：余弦相似度 0.72 + 实体加权关键词 0.28
- 向量按 DB mtime/条数缓存，审核新记忆后自动重建
- 仍保留 `starmap_recall` 工具与按话题注入
- 说明：这是本地词形向量，不等于语义 embedding；后续可替换为模型 embedding

### 记忆星图 v7：本地语义模型（fastembed + BGE）

- 安装 `fastembed`（0.9.1）与 `onnxruntime`（1.31.1）
- 模型：`BAAI/bge-small-zh-v1.5`，512 维，CPU 可跑
- 模型缓存固定在 `data/plugin_data/memory_starmap/fastembed_cache`，不随临时目录清理丢失
- 插件配置 `embedding_mode=fastembed`；启动时后台预热，避免第一条消息等待
- 检索：语义余弦 0.8 + 关键词 0.2；失败自动回退本地 hashed 向量
- 仍可切换 `api` 模式接外部 OpenAI 兼容 embedding，或 `local` 备用


### 记忆星图 v9：3D 星空

- 星图改为 Canvas 3D 投影：星点/星座在三维空间分布，默认缓慢自转
- 鼠标拖拽旋转、滚轮缩放、点击星点查看记忆详情
- 「自转 / 聚焦 / 侧栏 / 全屏」控制；全屏支持 Fullscreen API，失败时自动用 CSS 全屏兜底
- 外观改为真实星空：深黑蓝背景、白色/微蓝星点、柔和光晕、白色星座连线，去掉五彩圆点
- 右侧待审核/篇章/长弧线/详情保留，可通过「侧栏」收起，让星图画布占满主区域

### 记忆星图 v10：交互补充

- 双击星图空白处进入全屏，再次双击退出（双击星点不会触发，避免误触）
- 鼠标左右拖动方向已反转（右拖画面向左转）
- 拖动结束后不再暂停 5 秒，而是从 1/3 速度缓慢加速回原速
- 默认自转速度减半
