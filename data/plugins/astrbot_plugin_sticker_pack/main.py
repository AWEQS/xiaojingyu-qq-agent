"""sticker-pack：给机器人一套本地表情包，让它在回复里"发表情"。

- 人设/提示词里注入可用表情清单（id + 描述），模型在回复末尾写 [sticker:<id>]
- 发送前解析标记：拆掉标记，文字和表情分条发出（表情作为图片消息）
- 表情库放 stickers/ 目录，index.json 描述每个表情的适用场景，方便扩充
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star
from astrbot.core.agent.message import TextPart
from astrbot.core.message.message_event_result import MessageChain

MARKER_RE = re.compile(r"\[sticker:([^\]]+)\]")


class StickerPack(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        base = Path(__file__).resolve().parent
        raw = str(self.config.get("stickers_dir") or "").strip()
        self.dir = Path(raw) if raw else base / "stickers"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.dir / "index.json"
        self._index = self._load_index()
        self._index_mtime = self._index_path.stat().st_mtime if self._index_path.exists() else 0
        self._last_auto: dict[str, float] = {}
        logger.info(f"[sticker-pack] 表情库={self.dir} 共 {len(self._index)} 个")

    def _load_index(self) -> list[dict]:
        path = self.dir / "index.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text("utf-8-sig"))
            return [d for d in data if d.get("id") and d.get("file")]
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[sticker-pack] index.json 解析失败: {exc}")
            return []

    def _ensure_index(self) -> None:
        """index.json 变化时热重载，控制台增删后无需重启。"""
        try:
            mtime = self._index_path.stat().st_mtime if self._index_path.exists() else 0
        except Exception:
            return
        if mtime != self._index_mtime:
            self._index = self._load_index()
            self._index_mtime = mtime
            logger.info(f"[sticker-pack] 表情库热更新，共 {len(self._index)} 个")

    def _by_id(self, sid: str) -> dict | None:
        for entry in self._index:
            if entry["id"] == sid:
                return entry
        return None


    # ---------- 语境/情绪驱动的自动表情 ----------
    def _candidate_stickers(self, snippet: str) -> list[dict]:
        cfg = self.config
        n = max(5, int(cfg.get("auto_sticker_candidates", 28) or 28))
        words = set(re.findall(r"[\u4e00-\u9fff]{1,4}|[a-zA-Z]{2,}", snippet.lower()))
        scored = []
        for e in self._index:
            hay = (str(e.get("desc") or "") + " " + " ".join(str(t) for t in (e.get("tags") or []))).lower()
            score = sum(1 for w in words if w in hay)
            scored.append((score, random.random(), e))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in scored[:n]]

    def _sticker_allowed(self, event: AstrMessageEvent) -> bool:
        """只做频率/冷却检查（不调用模型）。"""
        cfg = self.config
        if not bool(cfg.get("auto_sticker_enabled", False)):
            return False
        key = str(event.get_group_id() or event.get_sender_id())
        now = time.time()
        cooldown = float(cfg.get("auto_sticker_cooldown_sec", 120) or 0)
        if cooldown > 0 and now - self._last_auto.get(key, 0.0) < cooldown:
            return False
        rate = int(cfg.get("auto_sticker_rate", 35) or 0)
        if rate <= 0 or random.random() * 100 >= rate:
            return False
        return True

    def _mark_sticker_sent(self, event: AstrMessageEvent) -> None:
        key = str(event.get_group_id() or event.get_sender_id())
        self._last_auto[key] = time.time()

    async def _auto_pick_sticker(self, event: AstrMessageEvent, reply_text: str) -> str | None:
        """根据语境/情绪决定是否发表情、发哪张；返回表情 id 或 None。"""
        cfg = self.config
        if not bool(cfg.get("auto_sticker_enabled", False)):
            return None
        if not self._index:
            return None
        key = str(event.get_group_id() or event.get_sender_id())
        now = time.time()
        cooldown = float(cfg.get("auto_sticker_cooldown_sec", 120) or 0)
        if cooldown > 0 and now - self._last_auto.get(key, 0.0) < cooldown:
            return None
        rate = int(cfg.get("auto_sticker_rate", 35) or 0)
        if rate <= 0 or random.random() * 100 >= rate:
            return None

        candidates = self._candidate_stickers(
            (event.message_str or "") + "\n" + reply_text
        )
        if not candidates:
            return None
        lines = "\n".join(
            f"- {e['id']}：{e.get('desc', '')}（{'/'.join(str(t) for t in (e.get('tags') or []))}）"
            for e in candidates
        )
        system_prompt = (
            "你是表情包挑图助手。根据当前聊天语境、双方情绪和机器人刚要说的话，"
            "判断这时候发一张表情包是否自然；如果合适，从候选里挑最贴切的一张。"
            "话题严肃、悲伤、争吵、正经回答时不要发表情。"
            '只输出 JSON，不要解释：{"use": true 或 false, "id": "候选里的id", "reason": "一句话"}'
        )
        prompt = (
            f"【对方的消/上下文】\n{(event.message_str or '')[:300]}\n\n"
            f"【机器人准备回复】\n{reply_text[:300]}\n\n"
            f"【候选表情】\n{lines}\n\n现在要发表情吗？发哪张？"
        ).replace("消/", "消息")
        try:
            provider_id = await self.context.get_current_chat_provider_id(umo=event.unified_msg_origin)
            resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                system_prompt=system_prompt,
                prompt=prompt,
                max_tokens=120,
            )
            text = (getattr(resp, "completion_text", "") or "").strip()
            m = re.search(r"\{.*\}", text, re.S)
            data = json.loads(m.group(0)) if m else {}
            use = bool(data.get("use", False))
            sid = str(data.get("id") or "").strip()
            reason = str(data.get("reason") or "").strip()
            entry = self._by_id(sid)
            if use and entry is not None:
                self._last_auto[key] = now
                logger.info(f"[sticker-pack] 自动发表情 {sid}（{reason or '语境合适'}）")
                return sid
            logger.info(f"[sticker-pack] 判断不发表情（{reason or '语境不合适'}）")
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[sticker-pack] 自动表情判断失败: {exc}")
            return None

    @filter.on_llm_request()
    async def inject_list(self, event: AstrMessageEvent, req: ProviderRequest):
        if not bool(self.config.get("enabled", True)):
            return
        self._ensure_index()
        if not self._index:
            return
        limit = max(1, int(self.config.get("list_limit", 10) or 10))
        entries = self._index[-limit:]
        lines = [f"- {e['id']}：{e.get('desc', '')}" for e in entries]
        block = (
            "【可用表情包】想发表情时，在回复末尾写 [sticker:<id>]，只写一个，别解释。\n"
            + "\n".join(lines)
        )
        try:
            req.extra_user_content_parts.append(TextPart(text=block))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[sticker-pack] 注入失败: {exc}")

    @filter.on_decorating_result()
    async def decorate(self, event: AstrMessageEvent):
        result = event.get_result()
        if result is None or not result.is_llm_result():
            return
        self._ensure_index()
        text = (result.get_plain_text() or "").strip()
        if not MARKER_RE.search(text) and text:
            gate = None
            try:
                gate = event.get_extra("context_gate")
            except Exception:
                gate = None
            if gate and gate.get("ran"):
                # 语境判断已经顺带挑过表情，不再单独调用模型
                sid = gate.get("sticker_id")
                if sid and self._by_id(str(sid)) and self._sticker_allowed(event):
                    text = f"{text} [sticker:{sid}]"
                    self._mark_sticker_sent(event)
            else:
                auto_id = await self._auto_pick_sticker(event, text)
                if auto_id:
                    text = f"{text} [sticker:{auto_id}]"
        if not MARKER_RE.search(text):
            return

        limit = max(1, int(self.config.get("max_per_reply", 1) or 1))
        ids = MARKER_RE.findall(text)[:limit]
        clean = MARKER_RE.sub("", text).strip()
        delay_ms = int(self.config.get("delay_ms", 500) or 0)

        result.chain.clear()
        if clean:
            await event.send(event.plain_result(clean))
        for sid in ids:
            entry = self._by_id(sid.strip())
            if not entry:
                logger.warning(f"[sticker-pack] 未找到表情 {sid}")
                continue
            path = self.dir / entry["file"]
            if not path.exists():
                logger.warning(f"[sticker-pack] 文件不存在 {path}")
                continue
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000)
            await event.send(MessageChain([Image.fromFileSystem(str(path))]))
            logger.info(f"[sticker-pack] 发送表情 {sid}")
