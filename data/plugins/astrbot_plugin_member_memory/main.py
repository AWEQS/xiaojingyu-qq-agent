"""member_memory：按群友建档的长期记忆。

- 注入：每次 LLM 请求前，把当前发言者的档案放进 extra_user_content_parts（不破坏系统提示缓存）
- 提炼：每次回复后，后台调用一次小模型，从"群友发言 + 机器人回复"里提炼稳定事实
- 存储：memory/<群号>.json，按成员分档；支持 /memory 查看与清理
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star
from astrbot.core.agent.message import TextPart

EXTRACT_PROMPT = """MEMORY_EXTRACT_V1
你是记忆整理器。阅读下面这段 QQ 群聊，提取关于发言人「{name}({uid})」的**稳定事实**：偏好、身份、正在做的事、雷点、口癖。
规则：
- 最多 3 条，每条不超过 30 字
- 只写长期有用的，不写一句一过的心情和寒暄
- 没有值得记的就返回空数组
只输出 JSON，不要解释：{{"facts": ["...", "..."]}}

发言人：{name}（{uid}）
发言：{text}
机器人回复：{reply}
"""


class MemberMemory(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        base = Path(__file__).resolve().parent
        self.mem_dir = base / "memory"
        self.mem_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict] = {}
        self._last_extract: dict[tuple[str, str], float] = {}
        self._extracting: set[tuple[str, str]] = set()
        self._last_inject: dict[tuple[str, str], str] = {}
        logger.info(f"[member-memory] 记忆目录={self.mem_dir}")

    # ---------- 存储 ----------
    def _file(self, group: str) -> Path:
        return self.mem_dir / f"{group or 'private'}.json"

    def _load(self, group: str) -> dict:
        if group in self._cache:
            return self._cache[group]
        path = self._file(group)
        data = {"group": group, "members": {}, "group_notes": []}
        if path.exists():
            try:
                data = json.loads(path.read_text("utf-8"))
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[member-memory] 读取 {path} 失败: {exc}")
        data.setdefault("members", {})
        data.setdefault("group_notes", [])
        self._cache[group] = data
        return data

    def _save(self, group: str) -> None:
        data = self._load(group)
        self._file(group).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), "utf-8"
        )

    def _notes(self, group: str, uid: str) -> list[dict]:
        return self._load(group)["members"].get(uid, {}).get("notes", [])

    def _add_notes(self, group: str, uid: str, name: str, facts: list[str]) -> int:
        data = self._load(group)
        member = data["members"].setdefault(uid, {"name": name, "notes": []})
        if name:
            member["name"] = name
        added = 0
        max_notes = max(1, int(self.config.get("max_notes", 20) or 20))
        for fact in facts:
            fact = str(fact).strip()
            if not fact:
                continue
            if any(fact == n.get("text") or fact in n.get("text", "") for n in member["notes"]):
                continue
            member["notes"].append({"t": int(time.time()), "text": fact})
            added += 1
        member["notes"] = member["notes"][-max_notes:]
        member["updated"] = int(time.time())
        self._save(group)
        return added

    # ---------- 注入 ----------
    @filter.on_llm_request()
    async def inject(self, event: AstrMessageEvent, req: ProviderRequest):
        if not bool(self.config.get("enabled", True)):
            return
        mode = str(self.config.get("inject_mode", "changed") or "changed")
        if mode == "off":
            return
        group = str(event.get_group_id() or "")
        uid = str(event.get_sender_id())
        notes = self._notes(group, uid)
        if not notes:
            return
        limit = max(1, int(self.config.get("inject_max_notes", 8) or 8))
        lines = [f"- {n['text']}" for n in notes[-limit:]]
        name = event.get_sender_name() or uid
        block = (
            f"【群友档案：{name}（{uid}）—— 长期记忆，自然使用，别复述】\n"
            + "\n".join(lines)
        )
        digest = hashlib.sha1(block.encode("utf-8")).hexdigest()
        key = (group, uid)
        if mode == "changed" and self._last_inject.get(key) == digest:
            logger.debug(f"[member-memory] 档案未变化，跳过注入（{name}）")
            return
        try:
            req.extra_user_content_parts.append(TextPart(text=block))
            self._last_inject[key] = digest
            logger.info(f"[member-memory] 注入 {len(lines)} 条档案（{name}，mode={mode}）")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[member-memory] 注入失败: {exc}")

    # ---------- 提炼 ----------
    @filter.on_llm_response()
    async def after_response(self, event: AstrMessageEvent, response: LLMResponse):
        if not bool(self.config.get("enabled", True)):
            return
        group = str(event.get_group_id() or "")
        uid = str(event.get_sender_id())
        key = (group, uid)
        if key in self._extracting:
            return
        min_interval = float(self.config.get("min_interval_sec", 120) or 0)
        if time.time() - self._last_extract.get(key, 0) < min_interval:
            return
        text = (event.message_str or "").strip()
        if len(text) < int(self.config.get("min_text_len", 8) or 8):
            return
        self._extracting.add(key)
        asyncio.create_task(self._extract(event, response, group, uid, key, text))

    async def _extract(self, event, response, group, uid, key, text):
        self._last_extract[key] = time.time()
        try:
            provider_id = await self.context.get_current_chat_provider_id(
                umo=event.unified_msg_origin
            )
            reply = (response.completion_text or "")[:200]
            prompt = EXTRACT_PROMPT.format(
                name=event.get_sender_name() or uid, uid=uid, text=text[:400], reply=reply
            )
            resp = await self.context.llm_generate(
                chat_provider_id=provider_id, prompt=prompt
            )
            facts = self._parse_facts(resp.completion_text or "")
            if facts:
                added = self._add_notes(group, uid, event.get_sender_name(), facts)
                logger.info(f"[member-memory] 新增 {added} 条档案（{uid}）: {facts}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[member-memory] 提炼失败: {exc}")
        finally:
            self._extracting.discard(key)

    @staticmethod
    def _parse_facts(raw: str) -> list[str]:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
            facts = data.get("facts") or []
            return [str(f) for f in facts][:3]
        except Exception:  # noqa: BLE001
            return []

    # ---------- 指令 ----------
    @filter.command("memory")
    async def memory_cmd(self, event: AstrMessageEvent):
        """查看/清空群友档案：/memory show | /memory clear"""
        parts = (event.message_str or "").split()
        sub = parts[1].lower() if len(parts) > 1 else "show"
        group = str(event.get_group_id() or "")
        uid = str(event.get_sender_id())

        if sub == "clear":
            if not event.is_admin():
                yield event.plain_result("只有管理员能清空档案")
                return
            data = self._load(group)
            data["members"].pop(uid, None)
            self._save(group)
            yield event.plain_result("已清空你的档案")
            return

        notes = self._notes(group, uid)
        if not notes:
            yield event.plain_result("这个群还没有你的档案")
            return
        body = "\n".join(f"- {n['text']}" for n in notes)
        yield event.plain_result(f"{event.get_sender_name()} 的档案：\n{body}")
