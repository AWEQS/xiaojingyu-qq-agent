"""breeze_tts：用 Breeze TTS 2 云端 API 发语音。

- 音色（克隆/预设）在控制台管理，active_voice 存在插件配置里
- 回复触发语音时调 Breeze API 生成 wav → silk → QQ 语音
- 失败只记日志，不影响文字回复
"""

from __future__ import annotations

import asyncio
import json
import random
import time
import urllib.request
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Record
from astrbot.api.star import Context, Star
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.utils.tencent_record_helper import wav_to_tencent_silk

BASE = Path(__file__).resolve().parent.parent.parent / "plugin_data" / "breeze_tts"
CACHE = BASE / "cache"


class BreezeTTS(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        CACHE.mkdir(parents=True, exist_ok=True)
        self._last: dict[str, float] = {}
        logger.info(
            f"[breeze-tts] 语音={'开' if self.config.get('enabled', True) else '关'} "
            f"音色={self.config.get('voice_id') or '(未选择)'} "
            f"Key={'已配置' if self.config.get('api_key') else '(未配置)'}"
        )

    def _tts(self, text: str) -> Path | None:
        cfg = self.config
        key = str(cfg.get("api_key") or "").strip()
        voice_id = str(cfg.get("voice_id") or "").strip()
        if not key or not voice_id:
            return None
        base = str(cfg.get("base_url") or "https://api.breeze.blue").rstrip("/")
        payload = {
            "text": text,
            "model_id": str(cfg.get("model_id") or "breeze-tts-2"),
            "instructions": str(cfg.get("instructions") or ""),
            "voice_settings": {"guidance_scale": float(cfg.get("guidance_scale", 4.0) or 4.0)},
        }
        if not payload["instructions"]:
            payload.pop("instructions")
        req = urllib.request.Request(
            f"{base}/v1/text-to-speech/{voice_id}?output_format=wav_24000",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
        )
        req.add_header("xi-api-key", key)
        req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        req.add_header("Accept", "audio/wav")
        req.add_header("Content-Type", "application/json")
        import hashlib

        digest = hashlib.sha1(f"{voice_id}|{text}".encode("utf-8")).hexdigest()[:16]
        out = CACHE / f"{digest}.wav"
        if out.exists() and out.stat().st_size > 1000:
            return out
        try:
            with urllib.request.urlopen(req, timeout=float(cfg.get("timeout_sec", 30) or 30)) as resp:
                data = resp.read()
            if len(data) < 1000:
                logger.warning(f"[breeze-tts] 返回音频过小: {len(data)}")
                return None
            out.write_bytes(data)
            return out
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[breeze-tts] 调用失败: {exc}")
            return None

    async def _to_silk(self, wav: Path) -> Path | None:
        try:
            silk = wav.with_suffix(".silk")
            if silk.exists() and silk.stat().st_size > 0:
                return silk
            await wav_to_tencent_silk(str(wav), str(silk))
            return silk
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[breeze-tts] silk 转换失败: {exc}")
            return None


    def _features(self) -> dict:
        path = BASE.parent.parent / "console_features.json"
        try:
            import json as _json
            return _json.loads(path.read_text("utf-8-sig"))
        except Exception:
            return {}

    def _voice_used_today(self) -> int:
        import datetime as _dt
        import json as _json
        path = BASE / "voice_usage.jsonl"
        if not path.exists():
            return 0
        today = _dt.date.today().isoformat()
        used = 0
        try:
            for line in path.read_text("utf-8", errors="replace").splitlines()[-3000:]:
                d = _json.loads(line)
                if _dt.datetime.fromtimestamp(float(d.get("ts") or 0)).date().isoformat() == today:
                    used += int(d.get("chars") or 0)
        except Exception:
            return used
        return used

    def _voice_budget_ok(self, chars: int) -> bool:
        feat = self._features()
        budget = feat.get("budget") or {}
        limit = float(budget.get("daily_voice_chars") or 0)
        if limit <= 0:
            return True
        used = self._voice_used_today()
        if used + chars <= limit:
            return True
        logger.info(f"[breeze-tts] 今日语音预算已用完 {used:.0f}/{limit:.0f}，跳过语音")
        return False

    def _log_voice_usage(self, chars: int) -> None:
        import json as _json
        import time as _time
        try:
            BASE.mkdir(parents=True, exist_ok=True)
            with (BASE / "voice_usage.jsonl").open("a", encoding="utf-8") as f:
                f.write(_json.dumps({"ts": _time.time(), "chars": chars, "voice": self.config.get("voice_id", "")}, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _should_send(self, event: AstrMessageEvent, text: str) -> bool:
        cfg = self.config
        if not bool(cfg.get("enabled", True)):
            return False
        if not text or len(text) > int(cfg.get("max_chars", 20) or 20):
            return False
        key = str(event.get_group_id() or event.get_sender_id())
        cooldown = float(cfg.get("cooldown_sec", 300) or 0)
        if cooldown > 0 and time.time() - self._last.get(key, 0.0) < cooldown:
            return False
        rate = int(cfg.get("voice_rate", 8) or 0)
        if rate <= 0 or random.random() * 100 >= rate:
            return False
        if not self._voice_budget_ok(len(text)):
            return False
        return True

    @filter.on_decorating_result(priority=-100)
    async def decorate(self, event: AstrMessageEvent):
        try:
            result = event.get_result()
            if result is None or not result.is_llm_result():
                return
            text = ""
            try:
                text = event.get_extra("whale_final_text") or ""
            except Exception:
                text = ""
            if not text:
                text = (result.get_plain_text() or "").strip()
            if not self._should_send(event, text):
                return
            wav = await asyncio.to_thread(self._tts, text)
            if wav is None:
                return
            silk = await self._to_silk(wav)
            if silk is None:
                return
            delay_ms = int(self.config.get("delay_ms", 800) or 0)
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000)
            key = str(event.get_group_id() or event.get_sender_id())
            self._last[key] = time.time()
            await event.send(MessageChain([Record(file=str(silk))]))
            self._log_voice_usage(len(text))
            logger.info(f"[breeze-tts] 发送语音：{text[:30]}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[breeze-tts] 语音发送失败，回退文字: {exc}")
