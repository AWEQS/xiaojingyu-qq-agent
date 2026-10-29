"""persona-pack：文件即人设，保存即生效；支持按群绑定、历史快照与回滚。"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star


class PersonaPack(Star):
    """把 personas/*.md 注入系统提示词，改文件即换人设。"""

    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        base = Path(__file__).resolve().parent
        raw = str(self.config.get("personas_dir") or "").strip()
        self.personas_dir = Path(raw) if raw else base / "personas"
        self.personas_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir = self.personas_dir / ".history"
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = base / "state.json"
        self._cache: dict[str, tuple[float, str]] = {}
        self._state = self._load_state()
        logger.info(
            f"[persona-pack] 人设目录={self.personas_dir} "
            f"默认={self._state.get('default')} 可用={self._list_personas()}"
        )

    # ---------- 状态 ----------
    def _load_state(self) -> dict:
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text("utf-8"))
                if isinstance(data, dict):
                    data.setdefault("bindings", {})
                    return data
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[persona-pack] state.json 读取失败: {exc}")
        return {
            "default": str(self.config.get("default_persona") or "").strip(),
            "bindings": {},
        }

    def _save_state(self) -> None:
        self.state_file.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2), "utf-8"
        )

    # ---------- 人设文件 ----------
    def _list_personas(self) -> list[str]:
        return sorted(p.stem for p in self.personas_dir.glob("*.md"))

    def _persona_path(self, name: str) -> Path:
        return self.personas_dir / f"{name}.md"

    def _read_persona(self, name: str) -> str | None:
        path = self._persona_path(name)
        if not path.exists():
            return None
        mtime = path.stat().st_mtime
        cached = self._cache.get(name)
        if cached and cached[0] == mtime:
            return cached[1]
        text = path.read_text("utf-8")
        self._snapshot(name, text)
        self._cache[name] = (mtime, text)
        logger.info(f"[persona-pack] 载入人设 {name}（{len(text)} 字）")
        return text

    def _snapshot(self, name: str, text: str) -> None:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
        if any(digest in p.name for p in self.history_dir.glob(f"{name}__*.md")):
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        (self.history_dir / f"{name}__{stamp}__{digest}.md").write_text(text, "utf-8")
        keep = max(1, int(self.config.get("max_history") or 50))
        files = sorted(self.history_dir.glob(f"{name}__*.md"))
        for old in files[:-keep]:
            old.unlink(missing_ok=True)

    # ---------- 绑定 ----------
    def _chat_key(self, event: AstrMessageEvent) -> str:
        msg = event.message_obj
        group_id = str(getattr(msg, "group_id", "") or "")
        if group_id:
            return f"group:{group_id}"
        sender = ""
        try:
            sender = str(event.get_sender_id())
        except Exception:  # noqa: BLE001
            sender = ""
        return f"private:{sender}"

    def _resolve(self, event: AstrMessageEvent) -> str:
        key = self._chat_key(event)
        return str(
            self._state.get("bindings", {}).get(key)
            or self._state.get("default")
            or ""
        )

    # ---------- 注入 ----------
    @filter.on_llm_request()
    async def inject_persona(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        if not bool(self.config.get("enabled", True)):
            return
        name = self._resolve(event)
        if not name:
            return
        text = self._read_persona(name)
        if not text:
            logger.warning(f"[persona-pack] 找不到人设 {name}")
            return
        block = f"【角色设定（persona: {name}）】\n{text.strip()}"
        current = req.system_prompt or ""
        if str(self.config.get("inject_position", "prepend")) == "append":
            req.system_prompt = f"{current}\n\n{block}" if current else block
        else:
            req.system_prompt = f"{block}\n\n{current}" if current else block

    # ---------- 指令 ----------
    @filter.command("persona")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def persona_cmd(self, event: AstrMessageEvent):
        """人设管理：list / use <名字> / default <名字> / show / reload / history / rollback <序号>"""
        parts = (event.message_str or "").split()
        args = parts[1:] if len(parts) > 1 else []
        sub = args[0].lower() if args else "list"
        key = self._chat_key(event)

        if sub == "list":
            names = self._list_personas()
            cur = self._resolve(event)
            body = "\n".join(f"{'*' if n == cur else ' '} {n}" for n in names) or "（空）"
            yield event.plain_result(f"本会话人设：{cur or '未设置'}\n可用人设：\n{body}")
            return

        if sub in {"use", "bind"} and len(args) >= 2:
            name = args[1]
            if name not in self._list_personas():
                yield event.plain_result(
                    f"没有人设 {name}。可用：{', '.join(self._list_personas()) or '空'}"
                )
                return
            self._state.setdefault("bindings", {})[key] = name
            self._save_state()
            yield event.plain_result(f"本会话已切换为 {name}")
            return

        if sub == "default" and len(args) >= 2:
            name = args[1]
            if name not in self._list_personas():
                yield event.plain_result(f"没有人设 {name}")
                return
            self._state["default"] = name
            self._save_state()
            yield event.plain_result(f"默认人设已设为 {name}")
            return

        if sub == "show":
            name = self._resolve(event)
            text = self._read_persona(name) or "（无）"
            yield event.plain_result(f"人设：{name}\n\n{text[:1200]}")
            return

        if sub == "reload":
            self._cache.clear()
            yield event.plain_result("已清空缓存，下一条消息会重新读盘")
            return

        if sub == "history":
            name = self._resolve(event)
            files = sorted(self.history_dir.glob(f"{name}__*.md"), reverse=True)[:10]
            body = "\n".join(p.name for p in files) or "（无快照）"
            yield event.plain_result(f"{name} 的历史快照：\n{body}")
            return

        if sub == "rollback" and len(args) >= 2:
            name = self._resolve(event)
            files = sorted(self.history_dir.glob(f"{name}__*.md"), reverse=True)
            if not files:
                yield event.plain_result("没有可回滚的快照")
                return
            try:
                idx = int(args[1]) - 1
            except ValueError:
                yield event.plain_result("用法：/persona rollback <序号>（1=最近一次）")
                return
            if not (0 <= idx < len(files)):
                yield event.plain_result(f"序号越界，共 {len(files)} 个快照")
                return
            src = files[idx]
            self._persona_path(name).write_text(src.read_text("utf-8"), "utf-8")
            self._cache.pop(name, None)
            yield event.plain_result(f"已回滚到 {src.name}")
            return

        yield event.plain_result(
            "用法：/persona list | use <名字> | default <名字> | show | reload | history | rollback <序号>"
        )
