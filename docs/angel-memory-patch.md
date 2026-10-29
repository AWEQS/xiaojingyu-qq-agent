# Angel Memory 本地改动记录

- 插件版本：astrbot_plugin_angel_memory 2.0.2（2026-10-28 安装）
- 来源：https://github.com/kawayiYokami/astrbot_plugin_angel_memory
- 本地改动：`core/sleep_schedule.py`
  - `SLEEP_HOUR = 4` -> `SLEEP_HOUR = 22`
  - 原因：晚上关机，4:00 整理永远跑不到
- 升级时必须重做此改动（否则整理时间回到 04:00）
- 记忆数据目录：`data\plugin_data\astrbot_plugin_angel_memory\memory_center`
- 整理状态文件：`memory_center\maintenance_state.json`（字段 cleanup_last_sleep_at）
- 控制台概览「上次记忆整理」读取该文件；超过 48 小时显示提醒
