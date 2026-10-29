"""memory_diary：每天写一页日记，按线索检索，按需注入。

和 Angel 记忆并行：
- Angel 管长期语义记忆
- 本插件管"某天发生了什么"，只在用户提到过去时检索一小段
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

BASE = Path(__file__).resolve().parent.parent.parent / "plugin_data" / "memory_diary"
DB_PATH = BASE / "diary.db"

CUE_KEYWORDS = [
    "上次", "之前", "那天", "以前", "当时", "还记得", "记得", "我们说过",
    "什么时候", "几号", "最后一次", "前几天", "上周", "昨天", "前天",
]


class MemoryDiary(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        BASE.mkdir(parents=True, exist_ok=True)
        self._task = None
        self._policy_cache = {"at": 0.0, "data": {}}
        self._init_db()
        logger.info(f"[memory-diary] 数据库：{DB_PATH}")

    # ---------- 存储 ----------
    def _conn(self):
        con = sqlite3.connect(str(DB_PATH), timeout=10)
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def _init_db(self) -> None:
        con = self._conn()
        try:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS raw_messages (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  ts REAL, umo TEXT, sender TEXT, name TEXT,
                  text TEXT, processed INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_raw_umo ON raw_messages(umo, ts);
                CREATE TABLE IF NOT EXISTS diary (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  date TEXT, umo TEXT, page TEXT,
                  created_at REAL, msg_count INTEGER
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_diary_date_umo ON diary(date, umo);
                """
            )
            con.commit()
        finally:
            con.close()

    def _policy(self) -> dict:
        now = time.time()
        if now - self._policy_cache["at"] < 60:
            return self._policy_cache["data"]
        path = Path(__file__).resolve().parent.parent / "astrbot_plugin_whale_behavior" / "policy.json"
        data = {}
        try:
            if path.exists():
                data = json.loads(path.read_text("utf-8-sig"))
        except Exception:
            data = {}
        self._policy_cache = {"at": now, "data": data}
        return data

    def _allowed(self, event: AstrMessageEvent) -> bool:
        if not bool(self.config.get("respect_whitelist", True)):
            return True
        policy = self._policy()
        if not bool(policy.get("whitelist_enabled")):
            return True
        gid = str(event.get_group_id() or "")
        uid = str(event.get_sender_id() or "")
        if gid:
            return gid in {str(x) for x in (policy.get("allowed_groups") or [])}
        return uid in {str(x) for x in (policy.get("allowed_private_users") or [])}

    # ---------- 采集 ----------
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def record_message(self, event: AstrMessageEvent) -> None:
        if not bool(self.config.get("enabled", True)):
            return
        try:
            text = (event.message_str or "").strip()
            if len(text) < 2 or text.startswith("/") or text.startswith("【") or text.startswith("["):
                return
            if not self._allowed(event):
                return
            try:
                if event.get_self_id() and str(event.get_self_id()) == str(event.get_sender_id()):
                    return
            except Exception:
                pass
            umo = str(event.unified_msg_origin or "")
            if not umo:
                return
            con = self._conn()
            try:
                con.execute(
                    "INSERT INTO raw_messages(ts, umo, sender, name, text) VALUES(?,?,?,?,?)",
                    (
                        time.time(),
                        umo,
                        str(event.get_sender_id() or ""),
                        str(event.get_sender_name() or ""),
                        text[:500],
                    ),
                )
                con.commit()
            finally:
                con.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[memory-diary] 记录消息失败: {exc}")

    # ---------- 生成 ----------
    def _diary_time_minutes(self) -> int:
        hour = int(self.config.get("diary_hour", 23) or 23)
        minute = int(self.config.get("diary_minute", 30) or 30)
        return hour * 60 + minute

    @staticmethod
    def _today() -> str:
        return time.strftime("%Y-%m-%d")

    async def _generate_for_date(self, date: str) -> None:
        con = self._conn()
        try:
            rows = con.execute(
                "SELECT umo, name, text FROM raw_messages WHERE processed=0 AND date(ts, 'unixepoch', 'localtime')=? ORDER BY ts",
                (date,),
            ).fetchall()
        finally:
            con.close()
        if not rows:
            return
        by_umo: dict[str, list[tuple]] = {}
        for umo, name, text in rows:
            by_umo.setdefault(str(umo), []).append((name, text))
        min_msgs = int(self.config.get("min_messages", 6) or 6)
        for umo, items in by_umo.items():
            if len(items) < min_msgs:
                continue
            lines = "\n".join(f"{name or '对方'}: {text}" for name, text in items[-150:])
            prompt = (
                f"日期：{date}\n"
                f"下面是今天的聊天记录：\n{lines}\n\n"
                "请以小鲸鱼自己的口吻写今天的日记，分三段（用换行分隔，不要用列表符号）：\n"
                "1. 今天发生了什么（3–5 句，具体的事）\n"
                "2. 今天记住的事（对方的偏好、约定、重要信息；没有就写“没什么特别的”）\n"
                "3. 情绪和没做完的事（心情、还没解决的问题）\n"
                f"总字数控制在 {int(self.config.get('max_page_chars', 400) or 400)} 字以内，只写日记内容。"
            )
            system_prompt = (
                "你是日记助手，替小鲸鱼写当天日记。只记录事实与感受，不要编造，不要评价人格，"
                "不要输出标题、解释或 markdown。"
            )
            try:
                provider = self.context.get_using_provider()
                if provider is not None:
                    resp = await provider.text_chat(
                        system_prompt=system_prompt,
                        prompt=prompt,
                        max_tokens=600,
                    )
                else:
                    provider_id = await self.context.get_current_chat_provider_id(umo=umo)
                    resp = await self.context.llm_generate(
                        chat_provider_id=provider_id,
                        system_prompt=system_prompt,
                        prompt=prompt,
                        max_tokens=600,
                    )
                page = (getattr(resp, "completion_text", "") or "").strip()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[memory-diary] 生成日记失败 {umo}: {exc}")
                continue
            if not page:
                continue
            page = page[: int(self.config.get("max_page_chars", 400) or 400) * 3]
            con = self._conn()
            try:
                con.execute(
                    "INSERT INTO diary(date, umo, page, created_at, msg_count) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(date, umo) DO UPDATE SET page=excluded.page, created_at=excluded.created_at, msg_count=excluded.msg_count",
                    (date, umo, page, time.time(), len(items)),
                )
                con.commit()
            finally:
                con.close()
            logger.info(f"[memory-diary] 已生成 {date} 日记（{umo}，{len(items)} 条消息）")
        con = self._conn()
        try:
            con.execute("UPDATE raw_messages SET processed=1 WHERE date(ts, 'unixepoch', 'localtime')=?", (date,))
            con.execute(
                "DELETE FROM raw_messages WHERE processed=1 AND ts < ?",
                (time.time() - int(self.config.get("keep_days", 30) or 30) * 86400,),
            )
            con.execute(
                "DELETE FROM diary WHERE date < ?",
                ((time.strftime("%Y-%m-%d", time.localtime(time.time() - int(self.config.get("keep_days", 30) or 30) * 86400))),),
            )
            con.commit()
        finally:
            con.close()

    async def _catch_up(self) -> None:
        yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
        con = self._conn()
        try:
            has = con.execute("SELECT 1 FROM diary WHERE date=?", (yesterday,)).fetchone()
        finally:
            con.close()
        if not has:
            await self._generate_for_date(yesterday)

    async def _diary_loop(self) -> None:
        await asyncio.sleep(20)
        try:
            await self._catch_up()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[memory-diary] 补写日记失败: {exc}")
        while True:
            now = time.localtime()
            cur = now.tm_hour * 60 + now.tm_min
            target = self._diary_time_minutes()
            wait_min = (target - cur) if target > cur else (24 * 60 - cur + target)
            await asyncio.sleep(max(60, wait_min * 60))
            try:
                await self._generate_for_date(self._today())
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[memory-diary] 定时生成日记失败: {exc}")
            await asyncio.sleep(90)

    # ---------- 检索 / 注入 ----------
    def _search(self, umo: str, query: str, limit: int = 2) -> list[tuple[str, str]]:
        con = self._conn()
        try:
            if query:
                like = f"%{query[:30]}%"
                rows = con.execute(
                    "SELECT date, page FROM diary WHERE umo=? AND page LIKE ? ORDER BY date DESC LIMIT ?",
                    (umo, like, limit),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT date, page FROM diary WHERE umo=? ORDER BY date DESC LIMIT ?",
                    (umo, limit),
                ).fetchall()
        finally:
            con.close()
        return [(str(d), str(p)) for d, p in rows]

    @staticmethod
    def _has_cue(text: str) -> bool:
        return any(k in (text or "") for k in CUE_KEYWORDS)

    @filter.on_llm_request(priority=-40)
    async def inject_diary(self, event: AstrMessageEvent, req) -> None:
        if not bool(self.config.get("enabled", True)):
            return
        text = (event.message_str or "").strip()
        if not self._has_cue(text):
            return
        umo = str(event.unified_msg_origin or "")
        pages = self._search(umo, text[:30], 2)
        if not pages:
            pages = self._search(umo, "", 1)
        if not pages:
            return
        cap = int(self.config.get("cue_inject_chars", 450) or 450)
        blocks = []
        for date, page in pages:
            blocks.append(f"{date}：\n{page[:cap]}")
        block = (
            "【日记摘录（参考，不要逐字复述，也不要提“日记”这个词）】\n"
            + "\n\n".join(blocks)
        )
        current = req.system_prompt or ""
        req.system_prompt = (current + "\n\n" + block) if current else block

    @filter.llm_tool(name="read_diary")
    async def tool_read_diary(self, event: AstrMessageEvent, date: str = "", query: str = ""):
        """翻看聊天日记，回忆某天发生了什么。

        Args:
            date (string): 日期，格式 YYYY-MM-DD；留空表示最近几天。
            query (string): 关键词，例如“火锅”“约定”。
        """
        umo = str(event.unified_msg_origin or "")
        con = self._conn()
        try:
            if date:
                rows = con.execute(
                    "SELECT date, page FROM diary WHERE umo=? AND date=? LIMIT 1", (umo, date)
                ).fetchall()
            elif query:
                rows = con.execute(
                    "SELECT date, page FROM diary WHERE umo=? AND page LIKE ? ORDER BY date DESC LIMIT 3",
                    (umo, f"%{query[:30]}%"),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT date, page FROM diary WHERE umo=? ORDER BY date DESC LIMIT 3", (umo,)
                ).fetchall()
        finally:
            con.close()
        if not rows:
            return "没有找到相关日记。"
        return "\n\n".join(f"{d}：\n{p}" for d, p in rows)

    # ---------- 生命周期 ----------
    async def initialize(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._diary_loop())
            logger.info("[memory-diary] 日记循环已启动")

    async def terminate(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
