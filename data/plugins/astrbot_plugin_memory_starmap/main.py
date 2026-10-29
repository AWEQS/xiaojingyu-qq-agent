"""记忆星图：把已审核的星座记忆按话题注入聊天提示词。"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import urllib.request
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star

DB = Path(__file__).resolve().parent.parent.parent / "plugin_data" / "memory_starmap" / "starmap.db"
TOKEN = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{2,}")



DIM = 320
_VECTOR_CACHE = {"mtime": 0, "count": 0, "claims": [], "vectors": []}
_FASTEMBED_MODEL = None
_FASTEMBED_NAME = ""


def _ngrams(text: str, sizes=(2, 3, 4)):
    text = re.sub(r"\s+", "", str(text or "").lower())
    out = []
    for n in sizes:
        for i in range(0, max(0, len(text) - n + 1)):
            out.append(text[i : i + n])
    for w in re.findall(r"[a-z0-9_]{2,}", text):
        out.append(w)
    return out


def _vector(text: str):
    vec = [0.0] * DIM
    for g in _ngrams(text):
        h = int(hashlib.md5(g.encode("utf-8")).hexdigest()[:12], 16)
        idx = h % DIM
        sign = 1.0 if (h // DIM) % 2 == 0 else -1.0
        # 越长的片段越有信息量
        vec[idx] += sign * (1.0 + 0.25 * min(4, len(g)))
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def _cosine(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


def _claim_text(c: dict) -> str:
    # 主体/客体重复加权
    return f"{c['subject']} {c['subject']} {c['predicate']} {c['object']} {c['object']} {c.get('quote') or ''}"

class MemoryStarmap(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        logger.info(f"[memory-starmap] 星图注入={'开' if self.config.get('inject', True) else '关'} db={DB}")
        if str(self.config.get("embedding_mode", "local")) == "fastembed":
            try:
                import threading

                threading.Thread(target=lambda: self._embed_fastembed(["预热"]), daemon=True).start()
            except Exception:
                pass

    def _tokens(self, text: str) -> list[str]:
        out = []
        stop = {"你还", "记得", "我们", "的吗", "什么", "怎么", "可以", "一个", "这个", "那个", "现在", "就是", "还是", "已经"}
        for run in re.findall(r"[\u4e00-\u9fff]{2,}", text or ""):
            n = len(run)
            candidates = [run] if n <= 4 else []
            for size in (2, 3, 4):
                for i in range(0, max(0, n - size + 1)):
                    candidates.append(run[i : i + size])
            for t in candidates:
                if t in stop or len(t) < 2 or t in out:
                    continue
                out.append(t)
        for t in TOKEN.findall(text or ""):
            if re.fullmatch(r"[A-Za-z0-9_]{2,}", t) and t.lower() not in out:
                out.append(t.lower())
        return out[:36]

    def _embed_config(self):
        return {
            "mode": str(self.config.get("embedding_mode", "local") or "local"),
            "base": str(self.config.get("embedding_base", "") or "").strip(),
            "key": str(self.config.get("embedding_key", "") or "").strip(),
            "model": str(self.config.get("embedding_model", "") or "").strip(),
            "fastembed_model": str(self.config.get("fastembed_model", "BAAI/bge-small-zh-v1.5") or "BAAI/bge-small-zh-v1.5").strip(),
        }

    def _embed_fastembed(self, texts: list[str]):
        global _FASTEMBED_MODEL, _FASTEMBED_NAME
        cfg = self._embed_config()
        name = cfg["fastembed_model"]
        try:
            if _FASTEMBED_MODEL is None or _FASTEMBED_NAME != name:
                from fastembed import TextEmbedding
                cache_dir = DB.parent / "fastembed_cache"
                cache_dir.mkdir(parents=True, exist_ok=True)
                _FASTEMBED_MODEL = TextEmbedding(model_name=name, cache_dir=str(cache_dir))
                _FASTEMBED_NAME = name
                logger.info(f"[memory-starmap] fastembed 已加载: {name}")
            raw = [list(v) for v in _FASTEMBED_MODEL.embed(texts)]
            out = []
            for v in raw:
                norm = math.sqrt(sum(x * x for x in v))
                out.append([x / norm for x in v] if norm else v)
            return out
        except Exception as exc:
            logger.warning(f"[memory-starmap] fastembed 失败，回退本地向量: {exc}")
            return None

    def _embed_remote(self, texts: list[str]):
        cfg = self._embed_config()
        if not cfg["base"] or not cfg["key"] or not cfg["model"]:
            return None
        url = cfg["base"].rstrip("/") + "/embeddings"
        body = json.dumps({"model": cfg["model"], "input": texts}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer " + cfg["key"])
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            vecs = [d["embedding"] for d in data.get("data", [])]
            if len(vecs) != len(texts):
                return None
            out = []
            for v in vecs:
                norm = math.sqrt(sum(x * x for x in v))
                out.append([x / norm for x in v] if norm else v)
            return out
        except Exception as exc:
            logger.warning(f"[memory-starmap] 远程 embedding 失败，回退本地向量: {exc}")
            return None

    def _load_index(self):
        if not DB.exists():
            return []
        try:
            mtime = DB.stat().st_mtime
            con = sqlite3.connect(str(DB), timeout=5)
            con.row_factory = sqlite3.Row
            rows = [
                dict(r)
                for r in con.execute(
                    "SELECT id,subject,predicate,object,category,quote,date,confidence FROM claims WHERE status='approved' ORDER BY id DESC LIMIT 800"
                )
            ]
            con.close()
        except Exception as exc:
            logger.warning(f"[memory-starmap] 读库失败: {exc}")
            return []
        cfg = self._embed_config()
        cache_key = cfg["mode"] + "|" + cfg["base"] + "|" + cfg["model"] + "|" + cfg["fastembed_model"]
        if (
            _VECTOR_CACHE.get("mtime") == mtime
            and _VECTOR_CACHE.get("count") == len(rows)
            and _VECTOR_CACHE.get("mode") == cache_key
        ):
            return _VECTOR_CACHE["vectors"]
        vectors = None
        if cfg["mode"] == "api":
            vectors = self._embed_remote([_claim_text(r) for r in rows])
        elif cfg["mode"] == "fastembed":
            vectors = self._embed_fastembed([_claim_text(r) for r in rows])
        if vectors is None:
            vectors = [_vector(_claim_text(r)) for r in rows]
            mode_used = "local"
        else:
            mode_used = "api"
        _VECTOR_CACHE.update(
            {"mtime": mtime, "count": len(rows), "claims": rows, "vectors": vectors, "mode": cache_key, "used": mode_used}
        )
        return vectors

    def _query_vector(self, query: str):
        cfg = self._embed_config()
        if cfg["mode"] == "api":
            remote = self._embed_remote([query])
            if remote:
                return remote[0], "api"
        elif cfg["mode"] == "fastembed":
            local = self._embed_fastembed([query])
            if local:
                return local[0], "fastembed"
        return _vector(query), "local"

    def _recall(self, query: str, limit: int = 3) -> list[dict]:
        vectors = self._load_index()
        claims = _VECTOR_CACHE["claims"]
        if not claims:
            return []
        qv, qmode = self._query_vector(query)
        tokens = self._tokens(query)
        scored = []
        for c, dv in zip(claims, vectors):
            cos = _cosine(qv, dv)
            subj = str(c["subject"] or "").lower()
            obj = str(c["object"] or "").lower()
            pred = str(c["predicate"] or "").lower()
            quote = str(c.get("quote") or "").lower()
            kw = 0.0
            for t in tokens:
                if t in subj:
                    kw += 2.6
                if t in obj:
                    kw += 2.0
                if t in pred:
                    kw += 1.2
                if t in quote:
                    kw += 0.5
            semantic_mode = qmode in ("api", "fastembed")
            try:
                sem_w = max(0.3, min(0.95, float(self.config.get("semantic_weight", 0.8) or 0.8)))
            except Exception:
                sem_w = 0.8
            base_sem = sem_w if semantic_mode else max(0.5, sem_w - 0.08)
            score = cos * base_sem + min(1.0, kw / 6.0) * (1.0 - base_sem)
            if score > 0.03:
                scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [x[1] for x in scored[:limit]]

    def _format(self, items: list[dict]) -> str:
        lines = []
        for it in items:
            line = f"- {it['subject']} {it['predicate']} {it['object']}"
            if it.get("quote"):
                line += f"（原话：{str(it['quote'])[:80]}）"
            lines.append(line)
        return "【记忆星图（你们之间已确认的事实）】\n" + "\n".join(lines)

    @filter.on_llm_request()
    async def inject_starmap(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        if not bool(self.config.get("inject", True)):
            return
        try:
            query = str(getattr(event, "message_str", "") or "")
            if not query:
                return
            limit = int(self.config.get("top_k", 3) or 3)
            items = self._recall(query, limit)
            if not items:
                return
            block = self._format(items)
            current = req.system_prompt or ""
            if str(self.config.get("position", "append")) == "prepend":
                req.system_prompt = f"{block}\n\n{current}" if current else block
            else:
                req.system_prompt = f"{current}\n\n{block}" if current else block
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[memory-starmap] 注入失败: {exc}")

    @filter.llm_tool(name="starmap_recall")
    async def tool_starmap_recall(self, event: AstrMessageEvent, query: str = ""):
        """从记忆星图里检索和当前话题相关的已确认记忆。

        Args:
            query (string): 要查的话题或关键词。
        """
        items = self._recall(query or getattr(event, "message_str", ""), 6)
        if not items:
            return "记忆星图里没有找到相关记忆。"
        return self._format(items)
