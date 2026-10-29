"""用量统计：拦截所有 Provider 的 text_chat，记录 token 用量（含缓存命中）。

覆盖主对话和插件里 context.llm_generate 的调用（DeepSeek 走 ProviderOpenAIOfficial）。
数据写入 data/plugin_data/usage_tracker/usage.jsonl。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from astrbot.api import logger
from astrbot.api.star import Context, Star

BASE = Path(__file__).resolve().parent.parent.parent / "plugin_data" / "usage_tracker"
USAGE_FILE = BASE / "usage.jsonl"
TURNS_FILE = BASE / "turns.jsonl"
MAX_FIELD = 20000
BASE.mkdir(parents=True, exist_ok=True)

_ORIGINALS: dict[int, tuple[type, object]] = {}


def _usage_of(resp) -> tuple[int, int, int]:
    # AstrBot TokenUsage（ProviderOpenAI 会填到 llm_response.usage）
    usage = getattr(resp, "usage", None)
    if usage is not None and hasattr(usage, "input_cached"):
        return (
            int(getattr(usage, "input_other", 0) or 0),
            int(getattr(usage, "input_cached", 0) or 0),
            int(getattr(usage, "output", 0) or 0),
        )
    # OpenAI raw usage
    raw = getattr(resp, "raw_completion", None)
    usage = getattr(raw, "usage", None) if raw is not None else None
    if usage is None:
        return 0, 0, 0
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    cached = 0
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        cached = int(getattr(details, "cached_tokens", 0) or 0)
    if not cached:
        cached = int(getattr(usage, "cached_tokens", 0) or 0)
    return max(0, prompt - cached), cached, completion


def _record(resp) -> None:
    try:
        miss, cached, out = _usage_of(resp)
        if miss + cached + out <= 0:
            return
        model = ""
        raw = getattr(resp, "raw_completion", None)
        if raw is not None:
            model = str(getattr(raw, "model", "") or "")
        if not model:
            model = "deepseek-chat"
        record = {
            "ts": time.time(),
            "model": model,
            "in_miss": miss,
            "in_cached": cached,
            "out": out,
        }
        with USAGE_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[usage-tracker] 记录失败: {exc}")


def _clip(text: str) -> tuple[str, bool]:
    text = str(text or "")
    if len(text) > MAX_FIELD:
        return text[:MAX_FIELD] + "\n…（已截断）", True
    return text, False


def _content_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(part.get("text") or part.get("content") or ""))
            else:
                parts.append(str(getattr(part, "text", "") or ""))
        return "".join(parts)
    return str(content)


def _ctx_text(contexts) -> str:
    if not contexts:
        return ""
    lines = []
    for item in contexts:
        if isinstance(item, dict):
            role = str(item.get("role") or "")
            text = _content_text(item.get("content"))
        else:
            role = str(getattr(item, "role", "") or "")
            text = _content_text(getattr(item, "content", ""))
        if role or text:
            lines.append(f"[{role}]\n{text}")
    return "\n\n".join(lines)


def _tool_names(func_tool) -> list:
    try:
        names = getattr(func_tool, "tools", None) or getattr(func_tool, "func_list", None)
        if names:
            out = []
            for t in names:
                name = getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else None)
                if name:
                    out.append(str(name))
            return out
    except Exception:
        pass
    return []


def _record_turn(kwargs: dict, result) -> None:
    try:
        reply = ""
        chain = getattr(result, "result_chain", None)
        if chain is not None:
            reply = chain.get_plain_text() or ""
        miss, cached, out = _usage_of(result)
        system_prompt, truncated1 = _clip(kwargs.get("system_prompt") or "")
        prompt, truncated2 = _clip(kwargs.get("prompt") or "")
        contexts, truncated3 = _clip(_ctx_text(kwargs.get("contexts")))
        reply, truncated4 = _clip(reply)
        model = ""
        raw = getattr(result, "raw_completion", None)
        if raw is not None:
            model = str(getattr(raw, "model", "") or "")
        record = {
            "ts": time.time(),
            "model": model or "unknown",
            "session_id": str(kwargs.get("session_id") or ""),
            "system_prompt": system_prompt,
            "prompt": prompt,
            "contexts": contexts,
            "reply": reply,
            "tools": _tool_names(kwargs.get("func_tool")),
            "usage": {"miss": miss, "cached": cached, "out": out},
            "truncated": truncated1 or truncated2 or truncated3 or truncated4,
        }
        with TURNS_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[usage-tracker] 对话记录失败: {exc}")


def _rotate_if_needed() -> None:
    try:
        if TURNS_FILE.exists() and TURNS_FILE.stat().st_size > 30 * 1024 * 1024:
            backup = BASE / f"turns.{int(time.time())}.jsonl"
            TURNS_FILE.rename(backup)
    except Exception:
        pass


def _provider_classes():
    from astrbot.core.provider.provider import Provider

    seen = set()
    stack = [Provider]
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.add(cls)
        yield cls
        stack.extend(cls.__subclasses__())


class UsageTracker(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        logger.info(f"[usage-tracker] 记录文件：{USAGE_FILE}")

    def _wrap_once(self) -> int:
        wrapped = 0
        for cls in _provider_classes():
            if "text_chat" not in cls.__dict__:
                continue
            if id(cls) in _ORIGINALS:
                continue
            original = cls.__dict__["text_chat"]

            async def wrapper(self, *args, __orig=original, **kwargs):
                kwargs_snapshot = dict(kwargs)
                result = await __orig(self, *args, **kwargs)
                _record(result)
                try:
                    if not kwargs_snapshot:
                        import inspect as _inspect

                        bound = _inspect.signature(__orig).bind_partial(self, *args, **kwargs_snapshot)
                        kwargs_snapshot = dict(bound.arguments)
                    _rotate_if_needed()
                    _record_turn(kwargs_snapshot, result)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(f"[usage-tracker] 记录 turn 跳过: {exc}")
                return result

            _ORIGINALS[id(cls)] = (cls, original)
            cls.text_chat = wrapper
            wrapped += 1
        return wrapped

    async def initialize(self) -> None:
        import asyncio

        total = self._wrap_once()
        logger.info(f"[usage-tracker] 首轮拦截 {total} 个 Provider.text_chat")

        async def keep_wrapping():
            # Provider 子类可能是插件加载之后才 import 的，持续补拦
            for _ in range(30):
                await asyncio.sleep(2)
                added = self._wrap_once()
                if added:
                    logger.info(f"[usage-tracker] 补拦 {added} 个 Provider.text_chat")

        self._wrap_task = asyncio.create_task(keep_wrapping())

    async def terminate(self) -> None:
        task = getattr(self, "_wrap_task", None)
        if task is not None:
            task.cancel()
        for cls, original in _ORIGINALS.values():
            try:
                cls.text_chat = original
            except Exception:
                pass
        _ORIGINALS.clear()
        logger.info("[usage-tracker] 已恢复 Provider.text_chat")
