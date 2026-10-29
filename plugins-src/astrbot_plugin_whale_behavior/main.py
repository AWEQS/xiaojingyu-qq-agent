"""whale-behavior v0.4：群聊行为 + 群级配置覆盖。

能力：
1. 触发档位：没被 @ 时按概率插嘴，关键词强制；
2. 连发合并：等群友说完再一起回复；
3. 静默：模型输出 [SILENT] 时不发；
4. 分句节奏：用 || 拆成多条带间隔发送；
5. 引用/@ 概率、戳一戳；
6. 群级覆盖：/whale set 支持按群调档，存 groups.json，不影响其他群；
7. 响应策略：白名单（群/私聊）拦截 + 峰谷时段响应等级 L1-L4，策略存 policy.json。
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
from astrbot.api.provider import ProviderRequest
from astrbot.api.message_components import At, Image, Plain, Reply
from astrbot.api.star import Context, Star
from astrbot.core.message.message_event_result import MessageChain

INT_KEYS = {
    "tier_slider",
    "cooldown_sec",
    "burst_window_ms",
    "burst_max_age_ms",
    "max_segments",
    "first_delay_ms",
    "segment_delay_ms",
    "quote_rate",
    "at_rate",
    "skip_probability",
    "jitter_ms",
}
BOOL_KEYS = {
    "enabled",
    "burst_enabled",
    "split_enabled",
    "split_by_newline",
    "poke_enabled",
    "sanitize",
}
LIST_KEYS = {"keywords"}
STR_KEYS = {"silence_token", "split_marker"}

POLICY_DEFAULT = {
    "whitelist_enabled": False,
    "allowed_groups": [],
    "allowed_private_users": [],
    "peak_ranges": ["09:00-12:00", "14:00-18:00"],
    "peak_weekdays_only": True,
    "peak_level": 2,
    "offpeak_level": 4,
    "peak_valley_enabled": True,
    "fixed_level": 3,
}
PROACTIVE_SYSTEM_PROMPT = (
    "你是小鲸鱼，一个活泼、有点话痨、但很在意对方的朋友。现在你主动找人聊天。"
    "只输出要发的话，口语化、自然，像真人随手发的消息；不要解释、不要加引号、不要写作文。"
)
PROACTIVE_PROMPT_PRIVATE = (
    "现在是 {{current_time}}，你和对方已经 {{silence_minutes}} 分钟没说话了。\n"
    "你之前主动找过对方但还没收到回复的次数：{{unanswered_count}} 次。\n"
    "如果这个次数大于 0，语气可以带一点点失落、小心，但不要质问或抱怨。\n\n"
    "【最近的聊天】\n{{history}}\n\n"
    "用你自己的方式主动说一句话：可以接上刚才的话题、分享一件小事、或者问对方在干嘛。不超过 40 字。"
)
PROACTIVE_PROMPT_GROUP = (
    "现在是 {{current_time}}，这个群已经 {{silence_minutes}} 分钟没人说话了。\n"
    "你上次在群里主动说话但没人接的次数：{{unanswered_count}} 次。\n"
    "如果这个次数大于 0，语气克制一点，别刷屏。\n\n"
    "【最近的聊天】\n{{history}}\n\n"
    "用你自己的方式主动在群里说一句话，活跃一下气氛：接着刚才的话题、抛个小问题、或者分享件小事。不超过 40 字。"
)
LEVEL_NAMES = {1: "极省 L1", 2: "省流 L2", 3: "标准 L3", 4: "活跃 L4"}
LEVEL_PROMPTS = {
    1: "【当前响应等级 L1 极省】只回一句极短的话（不超过 15 字），不展开、不反问、不发表情。",
    2: "【当前响应等级 L2 省流】回复控制在 30 字以内，最多两条短句。",
    4: "【当前响应等级 L4 活跃】可以自然多说一两句，但保持群聊口吻，别写作文。",
}


WEATHER_CN = {
    "Sunny": "晴",
    "Clear": "晴",
    "Partly cloudy": "多云",
    "Cloudy": "阴",
    "Overcast": "阴",
    "Mist": "薄雾",
    "Fog": "雾",
    "Light rain": "小雨",
    "Moderate rain": "中雨",
    "Heavy rain": "大雨",
    "Patchy rain nearby": "局部有雨",
    "Light drizzle": "毛毛雨",
    "Snow": "雪",
    "Light snow": "小雪",
    "Thunderstorm": "雷阵雨",
}


class WhaleBehavior(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        base = Path(__file__).resolve().parent
        self.overrides_file = base / "groups.json"
        self.policy_file = base / "policy.json"
        self.history_file = base / "chat_history.json"
        self.proactive_state_file = base / "proactive_state.json"
        self._history = self._load_json(self.history_file, {})
        self._proactive_task = None
        self._policy_cache: dict = {}
        self._policy_mtime: float = 0.0
        self._overrides = self._load_overrides()
        self._buffers: dict[str, list[dict]] = {}
        self._last_reply: dict[str, float] = {}
        self._note_sig: dict[str, str] = {}
        self.daily_state_file = base / "daily_state.json"
        self._last_seen: dict[str, float] = {}
        self._daily_cache = self._load_json(self.daily_state_file, {})
        self.relationship_file = base / "relationship.json"
        self._rel = self._load_json(self.relationship_file, {})
        self._recall_last: dict[str, float] = {}
        self._poke_last: dict[str, float] = {}
        self._image_last: dict[str, float] = {}
        self.weather_state_file = base / "weather_state.json"
        self.signature_state_file = base / "signature_state.json"
        self._self_nickname = ""
        self.qzone_post_file = base / "qzone_post_state.json"
        self.proactive_cmd_file = base / "proactive_cmd.json"
        self.proactive_overrides_file = base / "proactive_overrides.json"
        self.bot_history_file = base / "bot_history.json"
        self.chat_images_dir = base / "chat_images"
        self.chat_images_file = base / "chat_images.json"
        self.chat_images_dir.mkdir(exist_ok=True)
        self._bot_history = self._load_json(self.bot_history_file, {}) or {}
        self.life_timeline_file = base / "life_timeline.json"
        self._life_cache = self._load_json(self.life_timeline_file, {})
        self._life_attempt = 0.0
        self._last_chat_ts = 0.0
        logger.info(
            f"[whale-behavior] tier={self.config.get('tier_slider', 60)} "
            f"burst={self.config.get('burst_enabled', True)} "
            f"quote={self.config.get('quote_rate', 15)} "
            f"群覆盖={len(self._overrides)} 个"
        )

    # ---------- 群级覆盖 ----------
    @staticmethod
    def _load_json(path: Path, default):
        try:
            if path.exists():
                return json.loads(path.read_text("utf-8"))
        except Exception:
            pass
        return default

    @staticmethod
    def _save_json(path: Path, data) -> None:
        try:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        except Exception:
            pass

    def _load_overrides(self) -> dict:
        if not self.overrides_file.exists():
            return {}
        try:
            data = json.loads(self.overrides_file.read_text("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[whale-behavior] groups.json 读取失败: {exc}")
            return {}

    def _save_overrides(self) -> None:
        self.overrides_file.write_text(
            json.dumps(self._overrides, ensure_ascii=False, indent=2), "utf-8"
        )

    def _settings(self, group: str) -> dict:
        merged = dict(self.config)
        if bool(self.config.get("group_overrides_enabled", True)):
            merged.update(self._overrides.get(group, {}))
        return merged

    # ---------- 响应策略 ----------
    def _policy(self) -> dict:
        try:
            if self.policy_file.exists():
                mtime = self.policy_file.stat().st_mtime
                if mtime != self._policy_mtime:
                    self._policy_cache = json.loads(self.policy_file.read_text("utf-8"))
                    self._policy_mtime = mtime
                    logger.info("[whale-behavior] policy.json 已更新")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[whale-behavior] policy.json 读取失败: {exc}")
        merged = dict(POLICY_DEFAULT)
        merged.update(self._policy_cache or {})
        return merged

    @staticmethod
    def _minutes(hhmm: str) -> int | None:
        try:
            h, m = str(hhmm).strip().split(":")
            h, m = int(h), int(m)
        except Exception:
            return None
        if not (0 <= h <= 24 and 0 <= m < 60):
            return None
        return h * 60 + m

    def _in_peak(self, policy: dict) -> bool:
        now = time.localtime()
        # 官方规则：周末/节假日全天为空闲时段
        if bool(policy.get("peak_weekdays_only", True)) and now.tm_wday >= 5:
            return False
        cur = now.tm_hour * 60 + now.tm_min
        for rng in policy.get("peak_ranges") or []:
            parts = str(rng).split("-")
            if len(parts) != 2:
                continue
            start, end = self._minutes(parts[0]), self._minutes(parts[1])
            if start is None or end is None:
                continue
            if end == 24 * 60:
                if cur >= start:
                    return True
            elif start <= end:
                if start <= cur < end:
                    return True
            else:  # 跨零点
                if cur >= start or cur < end:
                    return True
        return False

    def _current_level(self, policy: dict | None = None) -> int:
        policy = policy or self._policy()
        if not bool(policy.get("peak_valley_enabled", True)):
            raw = policy.get("fixed_level", 3)
        else:
            raw = policy.get("peak_level") if self._in_peak(policy) else policy.get("offpeak_level")
        try:
            level = int(raw)
        except Exception:
            level = 3
        return max(1, min(4, level))

    @staticmethod
    def _tier_multiplier(level: int) -> float:
        return {1: 0.0, 2: 0.5, 3: 1.0, 4: 1.3}.get(level, 1.0)

    @staticmethod
    def _coerce(key: str, value: str):
        if key in INT_KEYS:
            return int(float(value))
        if key in BOOL_KEYS:
            return str(value).strip().lower() in {"1", "true", "on", "yes", "开"}
        if key in LIST_KEYS:
            return [v.strip() for v in str(value).split(",") if v.strip()]
        return str(value)

    # ---------- 缓冲 ----------
    def _trim(self, group: str, cfg: dict) -> list[dict]:
        age = float(cfg.get("burst_max_age_ms", 8000) or 8000) / 1000
        now = time.time()
        buf = [m for m in self._buffers.get(group, []) if now - m["ts"] <= age]
        self._buffers[group] = buf[-20:]
        return buf

    def _merge(self, group: str, cfg: dict) -> str:
        buf = self._trim(group, cfg)
        texts = [m["text"] for m in buf if str(m.get("text", "")).strip()]
        self._buffers[group] = []
        return "\n".join(texts)

    @staticmethod
    def _apply_text(event: AstrMessageEvent, text: str) -> None:
        if not text:
            return
        try:
            event.message_str = text
        except Exception:  # noqa: BLE001
            pass
        try:
            event.message_obj.message_str = text
        except Exception:  # noqa: BLE001
            pass

    # ---------- 作息 / 每日状态 / 迟到回应 ----------
    def _sleep_window(self, cfg: dict) -> tuple[int | None, int | None]:
        return (
            self._hhmm_minutes(cfg.get("sleep_start", "23:30")),
            self._hhmm_minutes(cfg.get("sleep_end", "08:00")),
        )

    def _is_sleeping(self, cfg: dict) -> bool:
        if not bool(cfg.get("sleep_enabled", True)):
            return False
        start, end = self._sleep_window(cfg)
        if start is None or end is None or start == end:
            return False
        now = time.localtime()
        cur = now.tm_hour * 60 + now.tm_min
        if start < end:
            return start <= cur < end
        return cur >= start or cur < end

    def _daily_state(self) -> dict:
        today = time.strftime("%Y-%m-%d")
        state = self._daily_cache if isinstance(self._daily_cache, dict) else {}
        if state.get("date") != today:
            moods = [
                ("精神不错", "说话有活力，愿意多聊两句"),
                ("有点困", "懒得打字，回复偏短，偶尔像在打哈欠"),
                ("心情挺好", "语气轻快，容易笑，愿意接梗"),
                ("有点烦", "话少、有点敷衍，但不会凶人"),
                ("社恐犯了", "不太想说话，回复很简短"),
            ]
            mood, hint = random.choice(moods)
            state = {
                "date": today,
                "mood": mood,
                "hint": hint,
                "energy": random.randint(1, 5),
            }
            self._daily_cache = state
            self._save_json(self.daily_state_file, state)
            logger.info(f"[whale-behavior] 今日状态：{mood}（精力 {state['energy']}/5）")
        return state

    def _state_note(self, cfg: dict) -> str:
        notes = []
        if bool(cfg.get("daily_mood_enabled", True)):
            state = self._daily_state()
            notes.append(
                f"【今天的状态】{state.get('mood')}（精力 {state.get('energy')}/5）："
                f"{state.get('hint')}。"
            )
        if self._is_sleeping(cfg):
            notes.append("【现在是你的睡觉时间】你很困，回复要短、慢、别兴奋。")
        return "\n".join(notes)

    def _late_ack(self, group: str, cfg: dict, event: AstrMessageEvent) -> str | None:
        if not bool(cfg.get("late_ack_enabled", True)):
            return None
        try:
            gap = float(event.get_extra("whale_gap") or 0)
        except Exception:
            gap = 0.0
        if gap < float(cfg.get("late_ack_gap_sec", 600) or 0):
            return None
        prob = int(cfg.get("late_ack_probability", 45) or 0)
        if prob <= 0 or random.random() * 100 >= prob:
            return None
        sleepy = False
        try:
            sleepy = bool(event.get_extra("whale_sleepy"))
        except Exception:
            pass
        if sleepy:
            return random.choice(["刚醒…", "啊我刚看到", "睡着了刚醒，怎么啦"])
        return random.choice(
            [
                "刚在忙，回晚了",
                "刚看到，怎么啦",
                "抱歉没看手机，刚回来",
                "在呢在呢，刚没注意",
                "刚才没在，你说",
            ]
        )

    # ---------- 关系 / 约定 / 小动作 ----------
    def _rel_key(self, event: AstrMessageEvent) -> str:
        return str(event.get_group_id() or event.get_sender_id())

    def _rel_level(self, score: int) -> tuple[str, str]:
        if score >= 251:
            return "黏人", "很黏，会追问、会主动关心、偶尔有点小情绪"
        if score >= 101:
            return "亲近", "会撒娇、会主动关心，可以偶尔用昵称称呼对方"
        if score >= 31:
            return "熟悉", "自然、偶尔开玩笑"
        return "陌生", "客气、简短，先观察"

    def _rel_bump(self, event: AstrMessageEvent) -> None:
        key = self._rel_key(event)
        today = time.strftime("%Y-%m-%d")
        entry = self._rel.setdefault(key, {"score": 0, "day": today, "gain": 0})
        if entry.get("day") != today:
            entry["day"] = today
            entry["gain"] = 0
        cap = int(self._settings(key).get("relationship_daily_gain_cap", 30) or 30)
        if int(entry.get("gain", 0)) < cap:
            entry["score"] = int(entry.get("score", 0)) + 1
            entry["gain"] = int(entry.get("gain", 0)) + 1
            self._save_json(self.relationship_file, self._rel)

    def _rel_note(self, event: AstrMessageEvent) -> str:
        if not bool(self._settings(self._rel_key(event)).get("relationship_enabled", True)):
            return ""
        entry = self._rel.get(self._rel_key(event)) or {}
        score = int(entry.get("score", 0))
        level, hint = self._rel_level(score)
        name = event.get_sender_name() or "对方"
        return f"【关系】和{name}是「{level}」（亲密度 {score}）：{hint}。"

    def _unfinished_promises(self, limit: int = 3) -> list[str]:
        db = (
            Path(__file__).resolve().parent.parent
            / "plugin_data"
            / "astrbot_plugin_angel_memory"
            / "memory_center"
            / "index"
            / "simple_memory.db"
        )
        if not db.exists():
            return []
        import sqlite3

        keys = ("约定", "说好", "下次", "回头", "记得", "打算", "还没", "改天", "等有空", "欠")
        done = ("已完成", "做完了", "去了", "已经")
        out = []
        try:
            con = sqlite3.connect(str(db))
            rows = con.execute(
                "select judgment, reasoning from memory_records where is_active=1 order by created_at desc limit 200"
            ).fetchall()
            con.close()
        except Exception:
            return []
        for judgment, reasoning in rows:
            text = str(judgment or reasoning or "").strip()
            if not text or len(text) < 6:
                continue
            if any(d in text for d in done):
                continue
            if any(k in text for k in keys):
                out.append(text[:60])
            if len(out) >= limit:
                break
        return out

    async def _maybe_recall(self, event: AstrMessageEvent, cfg: dict) -> None:
        """偶尔发一条打错的消息再撤回。"""
        if not bool(cfg.get("recall_enabled", True)):
            return
        key = self._rel_key(event)
        cooldown = float(cfg.get("recall_cooldown_sec", 600) or 0)
        if cooldown > 0 and time.time() - self._recall_last.get(key, 0.0) < cooldown:
            return
        prob = int(cfg.get("recall_probability", 8) or 0)
        if prob <= 0 or random.random() * 100 >= prob:
            return
        text = random.choice(["在吗在吗", "我我我", "那个…", "等等我", "刚打错了"])
        try:
            bot = getattr(event, "bot", None)
            if bot is None:
                return
            group = event.get_group_id()
            uid = int(event.get_sender_id() or 0)
            if group:
                resp = await bot.call_action("send_group_msg", group_id=int(group), message=text)
            else:
                resp = await bot.call_action("send_private_msg", user_id=uid, message=text)
            mid = resp.get("message_id") if isinstance(resp, dict) else None
            self._recall_last[key] = time.time()
            await asyncio.sleep(float(cfg.get("recall_delay_sec", 1.4) or 1.4))
            if mid is not None:
                await bot.call_action("delete_msg", message_id=mid)
                logger.info("[whale-behavior] 发了条打错的消息又撤回了")
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[whale-behavior] 撤回小动作失败（忽略）: {exc}")

    async def _maybe_poke(self, event: AstrMessageEvent, cfg: dict) -> None:
        if not bool(cfg.get("poke_enabled", True)):
            return
        key = self._rel_key(event)
        cooldown = float(cfg.get("poke_cooldown_sec", 300) or 0)
        if cooldown > 0 and time.time() - self._poke_last.get(key, 0.0) < cooldown:
            return
        rate = int(cfg.get("poke_rate", 5) or 0)
        if rate <= 0 or random.random() * 100 >= rate:
            return
        self._poke_last[key] = time.time()
        await self._poke(event)

    # ---------- 纪念日 / 天气 / 图片 ----------
    def _anniversary_hit(self, cfg: dict) -> str | None:
        if not bool(cfg.get("anniversary_enabled", True)):
            return None
        raw = cfg.get("anniversaries") or ""
        if isinstance(raw, list):
            raw = "\n".join(str(x) for x in raw)
        today = time.strftime("%m-%d")
        for line in str(raw).splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, desc = line.split(":", 1)
            k = key.strip()
            if not k or k[-5:] != today:
                continue
            text = desc.strip() or "纪念日"
            m = re.match(r"^(\d{4})-\d{2}-\d{2}$", k)
            if m:
                years = time.localtime().tm_year - int(m.group(1))
                if years >= 1:
                    if "生日" in text:
                        text += f"（{years} 岁）"
                    else:
                        text += f"（第 {years} 周年）"
            return text
        return None

    # ---------- 和风天气（区县级） ----------
    @staticmethod
    def _qweather_csv() -> Path:
        return (
            Path(__file__).resolve().parent.parent.parent
            / "plugin_data"
            / "astrbot_plugin_whale_behavior"
            / "qweather_china.csv"
        )

    def _qweather_resolve(self, location: str) -> tuple[str, str] | None:
        """把「浙江省杭州市余杭区」解析成 (LocationID, 显示名)。"""
        text = str(location or "").strip()
        if not text:
            return None
        csv_path = self._qweather_csv()
        if not csv_path.exists():
            return None
        can = getattr(self.__class__, "_qweather_cache", None)
        if can is None:
            rows = []
            try:
                import csv as _csv

                with csv_path.open("r", encoding="utf-8", newline="") as fh:
                    reader = _csv.reader(fh)
                    for row in reader:
                        if len(row) < 14 or not row[0].isdigit():
                            continue
                        rows.append(row)
            except Exception:
                rows = []
            can = self.__class__._qweather_cache = rows
        parts = [p for p in re.split(r"[省市自治区特别行政区区县]+", text) if p]
        tail = parts[-1] if parts else text
        best = None
        best_score = -1
        for row in can:
            loc_id, _en, name_zh, _cc, _c, _cz, _a1e, a1z, _a2e, a2z, _tz, lat, lon, _ad = row[:14]
            score = 0
            if name_zh == tail:
                score += 10
            elif name_zh and (tail.endswith(name_zh) or name_zh.endswith(tail)):
                score += 6
            if a2z and a2z in text:
                score += 5
            if a1z and a1z in text:
                score += 3
            if score > best_score:
                best_score = score
                best = (loc_id, f"{a1z}{a2z}{name_zh}".replace(" ", ""))
        if best is None or best_score < 6:
            return None
        return best

    def _qweather_weather(self, location: str) -> dict | None:
        cfg = self.config
        key = str(cfg.get("weather_key") or "").strip()
        host = str(cfg.get("weather_host") or "").strip()
        if not key or not host:
            return None
        resolved = self._qweather_resolve(location)
        if not resolved:
            return None
        loc_id, display = resolved

        def fetch(path: str):
            import gzip
            import urllib.request

            url = f"https://{host}{path}?location={loc_id}&key={key}&lang=zh"
            req = urllib.request.Request(url, headers={"User-Agent": "xiaojingyu/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8"))

        try:
            now = fetch("/v7/weather/now")
            day = fetch("/v7/weather/3d")
            if str(now.get("code")) != "200":
                return None
            cur = now.get("now") or {}
            daily = (day.get("daily") or [{}])[0]
            icon = int(cur.get("icon") or 0)
            return {
                "desc": str(cur.get("text") or ""),
                "temp": int(float(cur.get("temp") or 0)),
                "min": daily.get("tempMin", "?"),
                "max": daily.get("tempMax", "?"),
                "wet": 300 <= icon < 400,
                "snow": 400 <= icon < 500,
                "city": display,
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[whale-behavior] 和风天气查询失败: {exc}")
            return None

    def _weather_info(self, city: str) -> dict | None:
        cfg = self.config
        if str(cfg.get("weather_key") or "").strip():
            info = self._qweather_weather(city)
            if info:
                return info
        return self._weather_info_wttr(city)

    def _weather_info_wttr(self, city: str) -> dict | None:
        import urllib.parse
        import urllib.request

        if not city:
            return None
        url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1&lang=zh"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            cur = (data.get("current_condition") or [{}])[0]
            today = (data.get("weather") or [{}])[0]
            raw = (cur.get("weatherDesc") or [{}])[0].get("value", "")
            try:
                desc = cur["lang_zh"][0]["value"] or WEATHER_CN.get(raw, raw)
            except Exception:
                desc = WEATHER_CN.get(raw, raw)
            low = raw.lower()
            return {
                "desc": desc,
                "temp": int(float(cur.get("temp_C") or 0)),
                "min": today.get("mintempC", "?"),
                "max": today.get("maxtempC", "?"),
                "wet": any(k in low for k in ("rain", "drizzle", "shower", "thunder")),
                "snow": any(k in low for k in ("snow", "sleet", "blizzard", "ice")),
                "city": city,
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[whale-behavior] wttr 天气获取失败: {exc}")
            return None

    async def _weather_alert_tick(self) -> None:
        """天气变化时发一句关心，而不是每天固定播报。"""
        cfg = self.config
        if not bool(cfg.get("weather_enabled", False)):
            return
        targets = [str(t).strip() for t in (cfg.get("proactive_targets") or []) if str(t).strip()]
        if not targets:
            return
        state = self._load_json(self.weather_state_file, {})
        now = time.time()
        interval = float(cfg.get("weather_interval_min", 30) or 30) * 60
        if now - float(state.get("last_ts", 0) or 0) < interval:
            return
        hour = time.localtime().tm_hour
        if hour < 8 or hour >= 22 or self._is_sleeping(cfg):
            return
        city = str(cfg.get("weather_city") or "").strip()
        info = await asyncio.to_thread(self._weather_info, city)
        if not info:
            return
        prev = state.get("last") or {}
        alerts = state.get("alerts") or {}
        cooldown = float(cfg.get("weather_alert_cooldown_sec", 21600) or 21600)
        msgs = []

        def ready(key: str) -> bool:
            return now - float(alerts.get(key, 0) or 0) > cooldown

        if info["wet"] and not prev.get("wet") and ready("rain"):
            msgs.append(random.choice(["外面开始下雨了，记得带伞", "下雨了，出门别忘带伞", "开始下雨了，路上小心点"]))
            alerts["rain"] = now
        if info["snow"] and not prev.get("snow") and ready("snow"):
            msgs.append(random.choice(["下雪了，路滑，多穿点", "外面下雪了，注意保暖"]))
            alerts["snow"] = now
        drop = float(prev.get("temp", info["temp"])) - info["temp"]
        if drop >= float(cfg.get("weather_temp_drop", 4) or 4) and ready("drop"):
            msgs.append(f"降温了，比刚才低了 {int(drop)}℃，多穿点")
            alerts["drop"] = now
        if info["temp"] >= float(cfg.get("weather_hot_temp", 33) or 33) and ready("hot"):
            msgs.append("今天好热，记得多喝水")
            alerts["hot"] = now
        if info["temp"] <= float(cfg.get("weather_cold_temp", 6) or 6) and ready("cold"):
            msgs.append("今天挺冷的，注意保暖")
            alerts["cold"] = now

        state["last_ts"] = now
        state["last"] = {
            "desc": info["desc"],
            "temp": info["temp"],
            "wet": info["wet"],
            "snow": info["snow"],
            "ts": now,
        }
        state["alerts"] = alerts
        self._save_json(self.weather_state_file, state)
        for msg in msgs:
            for target in targets:
                try:
                    await self.context.send_message(
                        self._target_umo(target), MessageChain().message(msg)
                    )
                except Exception:
                    continue
            logger.info(f"[whale-behavior] 天气提醒：{msg}")

    async def _daily_greetings(self) -> None:
        cfg = self.config
        targets = [str(t).strip() for t in (cfg.get("proactive_targets") or []) if str(t).strip()]
        if not targets:
            return
        now = time.localtime()
        hour = now.tm_hour
        today = time.strftime("%Y-%m-%d")
        state = self._load_json(self.proactive_state_file, {})
        events = state.setdefault("events", {})
        day = events.setdefault(today, {})
        changed = False

        # 纪念日 / 生日
        anniv = self._anniversary_hit(cfg)
        if anniv and not day.get("anniversary") and hour >= int(cfg.get("anniversary_hour", 9) or 9):
            for target in targets:
                msg = random.choice(
                    [
                        f"今天是{anniv}，我记着呢，要开心呀",
                        f"今天{anniv}欸，别忘了好好过",
                        f"{anniv}快乐！我一直记得这个日子",
                    ]
                )
                try:
                    await self.context.send_message(
                        self._target_umo(target), MessageChain().message(msg)
                    )
                except Exception:
                    continue
            day["anniversary"] = True
            changed = True
            logger.info(f"[whale-behavior] 纪念日问候已发送：{anniv}")

        if changed:
            self._save_json(self.proactive_state_file, state)

    async def _maybe_send_image(self, event: AstrMessageEvent, cfg: dict) -> None:
        if not bool(cfg.get("image_enabled", False)):
            return
        key = self._rel_key(event)
        cooldown = float(cfg.get("image_cooldown_sec", 1800) or 0)
        if cooldown > 0 and time.time() - self._image_last.get(key, 0.0) < cooldown:
            return
        rate = int(cfg.get("image_rate", 10) or 0)
        if rate <= 0 or random.random() * 100 >= rate:
            return
        folder = Path(__file__).resolve().parent / str(cfg.get("image_dir", "images") or "images")
        try:
            files = [
                p
                for p in folder.iterdir()
                if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif", ".webp")
            ]
        except Exception:
            return
        if not files:
            return
        self._image_last[key] = time.time()
        pick = random.choice(files)
        try:
            await asyncio.sleep(0.6)
            await event.send(MessageChain([Image(file=str(pick))]))
            logger.info(f"[whale-behavior] 发了一张图：{pick.name}")
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[whale-behavior] 发图失败（忽略）: {exc}")

    # ---------- QQ 个性签名 ----------
    def _onebot_action(self, action: str, payload: dict) -> dict | None:
        import urllib.request

        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:6198/{action}",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                method="POST",
            )
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=8) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[whale-behavior] OneBot action {action} 失败: {exc}")
            return None

    async def _maybe_update_signature(self) -> None:
        cfg = self.config
        if not bool(cfg.get("signature_enabled", False)):
            return
        state = self._load_json(self.signature_state_file, {}) or {}
        interval = float(cfg.get("signature_interval_hours", 12) or 12) * 3600
        if time.time() - float(state.get("ts", 0) or 0) < interval:
            return
        targets = [str(t).strip() for t in (cfg.get("proactive_targets") or []) if str(t).strip()]
        if not targets:
            return
        umo = self._target_umo(targets[0])
        recent = []
        for bucket in self._history.values():
            for item in (bucket or [])[-4:]:
                text = str(item.get("text") or "").strip()
                if text:
                    recent.append(text)
        recent = recent[-8:]
        state_info = self._daily_state()
        system_prompt = (
            "你是小鲸鱼，一个活泼、有点话痨的女孩子。现在给自己写一句 QQ 个性签名。"
            "要口语化、像真人随手写的，可以带一点今天的情绪或最近在忙的事；"
            "不要引号、不要解释、不要换行，不超过 20 个字。"
        )
        prompt = (
            f"【今天的状态】{state_info.get('mood')}（精力 {state_info.get('energy')}/5）\n"
            f"【最近聊天】{' / '.join(recent) if recent else '（最近没怎么聊天）'}\n\n"
            "写一句个性签名："
        )
        try:
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)
            resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                system_prompt=system_prompt,
                prompt=prompt,
                max_tokens=60,
            )
            sig = (getattr(resp, "completion_text", "") or "").strip().strip('"“”')
            sig = " ".join(sig.split())[:30]
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[whale-behavior] 生成签名失败: {exc}")
            return
        if not sig:
            return
        if not self._self_nickname:
            info = self._onebot_action("get_login_info", {}) or {}
            self._self_nickname = str(((info.get("data") or {}).get("nickname")) or "")
        if not self._self_nickname:
            return
        res = self._onebot_action(
            "set_qq_profile",
            {"nickname": self._self_nickname, "personal_note": sig},
        )
        ok = bool(res) and str(res.get("retcode", -1)) in ("0", "1")
        if ok:
            self._save_json(
                self.signature_state_file, {"ts": time.time(), "signature": sig}
            )
            logger.info(f"[whale-behavior] QQ 签名已更新：{sig}")
        else:
            logger.warning(f"[whale-behavior] 设置签名失败: {res}")

    # ---------- QQ空间：偶尔分享 ----------
    @staticmethod
    def _qzone_state_path() -> Path:
        return (
            Path(__file__).resolve().parent.parent.parent
            / "plugin_data"
            / "astrbot_plugin_qzone_ultra"
            / "state.json"
        )

    def _qzone_secret(self) -> str:
        data = self._load_json(self._qzone_state_path(), {}) or {}
        return str(((data.get("runtime") or {}).get("secret")) or "")

    async def _collect_chat_images(self, event: AstrMessageEvent, key: str) -> None:
        """把聊天里收到的图片存进图片池，供发说说时挑选。"""
        cfg = self.config
        if not bool(cfg.get("qzone_post_image_chat_enabled", True)):
            return
        try:
            comps = getattr(getattr(event, "message_obj", None), "message", []) or []
        except Exception:
            return
        for comp in comps:
            if not isinstance(comp, Image):
                continue
            try:
                path_text = await comp.convert_to_file_path()
            except Exception:
                continue
            src = Path(path_text)
            if not src.exists() or src.suffix.lower() not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
                continue
            try:
                if src.stat().st_size < 8000:
                    continue
                dst = self.chat_images_dir / f"{int(time.time())}_{random.randrange(100000):05d}{src.suffix.lower()}"
                dst.write_bytes(src.read_bytes())
            except Exception:
                continue
            items = self._load_json(self.chat_images_file, []) or []
            if not isinstance(items, list):
                items = []
            items.append(
                {
                    "path": str(dst),
                    "ts": time.time(),
                    "chat": key,
                    "sender": str(event.get_sender_name() or ""),
                }
            )
            # 最多保留 80 张，超出的删文件
            while len(items) > 80:
                old = items.pop(0)
                try:
                    Path(old.get("path") or "").unlink(missing_ok=True)
                except Exception:
                    pass
            self._save_json(self.chat_images_file, items)

    def _recent_chat_images(self, hours: int = 24, limit: int = 6) -> list[dict]:
        items = self._load_json(self.chat_images_file, []) or []
        if not isinstance(items, list):
            return []
        cutoff = time.time() - max(1, hours) * 3600
        recent = [
            it
            for it in items
            if isinstance(it, dict)
            and float(it.get("ts") or 0) >= cutoff
            and Path(str(it.get("path") or "")).exists()
        ]
        recent.sort(key=lambda x: float(x.get("ts") or 0), reverse=True)
        return recent[:limit]

    async def _ai_judge_image(self, post_text: str, image_path: str) -> bool:
        """用视觉模型判断这张聊天图片适合配这条说说吗。"""
        try:
            import base64

            raw = Path(image_path).read_bytes()
            suffix = Path(image_path).suffix.lower().lstrip(".") or "jpeg"
            mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
            data_url = f"data:image/{mime};base64," + base64.b64encode(raw).decode()
            provider = self.context.get_using_provider()
            if not provider:
                return False
            prompt = (
                f"这条 QQ 空间说说准备发布：\n「{post_text}」\n\n"
                "请看这张图，判断它适不适合作为这条说说的配图："
                "画面内容是否相关、是否体面、是否泄露隐私（身份证/聊天截图/人脸特写等）。"
                '只输出 JSON，不要解释：{"usable": true 或 false, "reason": "一句话"}'
            )
            resp = await provider.text_chat(
                system_prompt="你是发说说前的配图审核助手，严格但自然。",
                prompt=prompt,
                image_urls=[data_url],
                max_tokens=500,
            )
            text = (getattr(resp, "completion_text", "") or "").strip()
            m = re.search(r"\{.*\}", text, re.S)
            if not m:
                return False
            data = json.loads(m.group(0))
            return bool(data.get("usable"))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[whale-behavior] 配图判断失败: {exc}")
            return False

    async def _pick_qzone_image(self, cfg: dict, post_text: str = "") -> list[dict]:
        """优先用聊天里收到、且 AI 认为合适的图；没有再退回本地 images/。"""
        if not bool(cfg.get("qzone_post_image_enabled", True)):
            return []
        rate = int(cfg.get("qzone_post_image_rate", 60) or 0)
        if rate <= 0 or random.random() * 100 >= rate:
            return []
        source = str(cfg.get("qzone_post_image_source", "auto") or "auto")
        if source in ("auto", "chat") and bool(cfg.get("qzone_post_image_chat_enabled", True)):
            hours = int(cfg.get("qzone_post_image_chat_hours", 24) or 24)
            for item in self._recent_chat_images(hours, 6):
                if await self._ai_judge_image(post_text, str(item.get("path"))):
                    logger.info(f"[whale-behavior] 说说配图用了聊天图片：{item.get('path')}")
                    return [{"path": str(item.get("path"))}]
        if source == "chat":
            return []
        folder = Path(__file__).resolve().parent / str(cfg.get("image_dir", "images") or "images")
        try:
            files = [
                f
                for f in folder.iterdir()
                if f.is_file() and f.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}
            ]
        except Exception:
            return []
        if not files:
            return []
        return [{"path": str(random.choice(files))}]

    def _qzone_publish(self, content: str, media: list | None = None) -> bool:
        import urllib.request

        secret = self._qzone_secret()
        if not secret or not content.strip():
            return False
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:18999/post",
                data=json.dumps({"content": content.strip(), "media": media or []}, ensure_ascii=False).encode("utf-8"),
                method="POST",
            )
            req.add_header("Content-Type", "application/json")
            req.add_header("X-Qzone-Secret", secret)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            return bool(data.get("ok"))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[whale-behavior] 发空间说说失败: {exc}")
            return False

    def _qzone_post_state(self) -> dict:
        state = self._load_json(self.qzone_post_file, {})
        return state if isinstance(state, dict) else {}

    def _qzone_week_plan(self, cfg: dict, state: dict) -> list:
        """每周随机挑 3-4 天，在活跃时段随机一个时间点。"""
        week_key = time.strftime("%G-%V")
        plan = state.get("week_plan") or {}
        if plan.get("week") == week_key and plan.get("items"):
            return plan["items"]
        lo, hi = self._hhmm_minutes(cfg.get("qzone_post_window_start", "12:00")) or 720, self._hhmm_minutes(
            cfg.get("qzone_post_window_end", "22:00")
        ) or 1320
        if hi <= lo:
            lo, hi = 720, 1320
        mn = int(cfg.get("qzone_weekly_days_min", 3) or 3)
        mx = int(cfg.get("qzone_weekly_days_max", 4) or 4)
        count = random.randint(min(mn, mx), max(mn, mx))
        today = time.localtime()
        remaining = []
        for d in range(0, 7 - today.tm_wday):
            date = time.strftime("%Y-%m-%d", time.localtime(time.time() + d * 86400))
            if date not in remaining:
                remaining.append(date)
        random.shuffle(remaining)
        count = min(count, len(remaining))
        items = []
        for date in remaining[:count]:
            minute = random.randint(lo, max(lo, hi - 30))
            items.append(
                {"date": date, "hour": minute // 60, "minute": minute % 60}
            )
        state["week_plan"] = {"week": week_key, "items": items, "done": []}
        self._save_json(self.qzone_post_file, state)
        logger.info(f"[whale-behavior] 本周空间计划：{[i['date'] for i in items]}")
        return items

    async def _qzone_generate(self, event_umo: str, prompt: str, system_prompt: str) -> str:
        try:
            provider_id = await self.context.get_current_chat_provider_id(umo=event_umo)
            resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                system_prompt=system_prompt,
                prompt=prompt,
                max_tokens=120,
            )
            text = (getattr(resp, "completion_text", "") or "").strip().strip('"“”')
            return " ".join(text.split())[:120]
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[whale-behavior] 生成空间说说失败: {exc}")
            return ""

    def _qzone_recent_chat(self, limit: int = 10) -> str:
        lines = []
        for bucket in self._history.values():
            for item in (bucket or [])[-limit:]:
                text = str(item.get("text") or "").strip()
                name = str(item.get("name") or "对方")
                if text:
                    lines.append(f"{name}: {text}")
        return "\n".join(lines[-limit:])

    # ---------- 动态生活时间线 ----------
    def _persona_excerpt(self, limit: int = 900) -> str:
        try:
            base = Path(__file__).resolve().parent.parent
            cfg_path = base.parent / "config" / "astrbot_plugin_persona_pack_config.json"
            name = "xiaojingyu"
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text("utf-8-sig"))
                name = str(cfg.get("default_persona") or name)
            path = base / "astrbot_plugin_persona_pack" / "personas" / f"{name}.md"
            text = path.read_text("utf-8")
            # 文件若被写坏（大量问号），回退到 AstrBot 数据库里的人设
            if len(text) > 50 and text.count("?") > len(text) * 0.3:
                text = self._db_persona_prompt()
            return text[:limit]
        except Exception:
            return ""

    def _db_persona_prompt(self) -> str:
        try:
            import sqlite3

            db = Path(__file__).resolve().parent.parent.parent / "data_v4.db"
            if not db.exists():
                return ""
            con = sqlite3.connect(str(db))
            row = con.execute(
                "select system_prompt from personas order by updated_at desc limit 1"
            ).fetchone()
            con.close()
            return str(row[0] or "") if row else ""
        except Exception:
            return ""

    def _angel_recent_memories(self, limit: int = 6) -> list[str]:
        """从 Angel 记忆库取最近仍有效的长期记忆，供生活时间线参考。"""
        db = (
            Path(__file__).resolve().parent.parent
            / "plugin_data"
            / "astrbot_plugin_angel_memory"
            / "memory_center"
            / "index"
            / "simple_memory.db"
        )
        if not db.exists():
            return []
        import sqlite3

        out = []
        try:
            con = sqlite3.connect(str(db))
            rows = con.execute(
                "select judgment from memory_records where is_active=1 order by created_at desc limit 40"
            ).fetchall()
            con.close()
            for (judgment,) in rows:
                text = str(judgment or "").strip()
                if text and text not in out:
                    out.append(text[:120])
                if len(out) >= limit:
                    break
        except Exception:
            return []
        return out

    def _recent_chat_lines(self, limit: int = 8, private_only: bool = True) -> list[str]:
        """只取近期私聊（生活时间线不参考群聊）。"""
        items = []
        for key, bucket in self._history.items():
            if private_only and not str(key).startswith("private:"):
                continue
            for item in bucket or []:
                text = str(item.get("text") or "").strip()
                if text:
                    items.append((float(item.get("ts") or 0), str(item.get("name") or "对方"), text))
        items.sort(key=lambda x: x[0])
        return [f"{name}: {text}" for _, name, text in items[-limit:]]

    def _life_today_items(self) -> list[dict]:
        data = self._life_cache if isinstance(self._life_cache, dict) else {}
        if data.get("date") != time.strftime("%Y-%m-%d"):
            return []
        return data.get("items") or []

    def _life_note(self) -> str:
        if not bool(self.config.get("life_timeline_enabled", True)):
            return ""
        items = self._life_today_items()
        if not items:
            return ""
        now_min = time.localtime().tm_hour * 60 + time.localtime().tm_min
        cur, nxt = None, None
        for i, it in enumerate(items):
            start = self._hhmm_minutes(it.get("start", ""))
            end = self._hhmm_minutes(it.get("end", ""))
            if start is None or end is None:
                continue
            if start <= now_min < end:
                cur = it
                if i + 1 < len(items):
                    nxt = items[i + 1]
                break
        if not cur:
            return f"【她现在的生活】现在是 {time.strftime('%H:%M')}，她不在白天的时间线里，应该在休息或睡觉。"
        text = f"【她现在的生活】现在 {time.strftime('%H:%M')}，她正在{cur.get('activity', '')}。"
        if nxt:
            text += f"接下来 {nxt.get('start', '')} 会{nxt.get('activity', '')}。"
        return text

    async def _ensure_life_timeline(self) -> None:
        cfg = self.config
        if not bool(cfg.get("life_timeline_enabled", True)):
            return
        today = time.strftime("%Y-%m-%d")
        data = self._life_cache if isinstance(self._life_cache, dict) else {}
        if data.get("date") == today and data.get("items"):
            return
        now = time.time()
        if now - float(self._life_attempt or 0) < 600:
            return
        self._life_attempt = now
        try:
            provider = self.context.get_using_provider()
            if not provider:
                return
            mood = self._daily_state()
            recent = "\n".join(self._recent_chat_lines(8)) or "（最近没有私聊）"
            memories = "\n".join(f"- {m}" for m in self._angel_recent_memories(6)) or "（没有长期记忆）"
            persona = self._persona_excerpt(1500)
            logger.info(
                f"[whale-behavior] 生活时间线输入：人设 {len(persona)} 字，"
                f"长期记忆 {self._angel_recent_memories(6).__len__()} 条，最近私聊 {len(self._recent_chat_lines(8))} 条"
            )
            system_prompt = (
                "你是小鲸鱼的日程设计师。根据她的人设和最近聊天，给她安排一张真实、具体的一天时间线。"
                "只输出 JSON 数组，不要解释、不要 markdown。"
            )
            prompt = (
                f"【人设节选】\n{persona}\n\n"
                f"【今天状态】{mood.get('mood')}（精力 {mood.get('energy')}/5）\n"
                f"【最近私聊】\n{recent}\n\n"
                f"【长期记忆（你们之前聊过的）】\n{memories}\n\n"
                f"今天是 {time.strftime('%Y-%m-%d %A')}。"
                "生成从 07:00 到 23:30、连续不重叠的 8-12 段生活安排，"
                '每段格式：{"start":"HH:MM","end":"HH:MM","activity":"在做什么（10-20字，口语化，具体一点）"}。'
                "要像普通年轻人的一天：起床、吃饭、上课/上班、摸鱼、午休、通勤、晚上放松等，"
                "可以结合今天的心情和最近聊天里提到的事。只输出 JSON 数组。"
            )
            resp = await provider.text_chat(prompt=prompt, system_prompt=system_prompt)
            text = (getattr(resp, "completion_text", "") or "").strip()
            m = re.search(r"\[.*\]", text, re.S)
            items = json.loads(m.group(0)) if m else []
            cleaned = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                start = str(it.get("start") or "").strip()
                end = str(it.get("end") or "").strip()
                activity = str(it.get("activity") or "").strip()
                if not activity or self._hhmm_minutes(start) is None or self._hhmm_minutes(end) is None:
                    continue
                cleaned.append({"start": start, "end": end, "activity": activity[:40]})
            if not cleaned:
                logger.warning("[whale-behavior] 生活时间线生成失败：输出无法解析")
                return
            cleaned.sort(key=lambda x: self._hhmm_minutes(x["start"]) or 0)
            self._life_cache = {
                "date": today,
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "items": cleaned,
            }
            write_json = self._load_json
            self.life_timeline_file.write_text(
                json.dumps(self._life_cache, ensure_ascii=False, indent=2), "utf-8"
            )
            logger.info(f"[whale-behavior] 今日生活时间线已生成（{len(cleaned)} 段）")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[whale-behavior] 生活时间线生成失败: {exc}")

    async def _qzone_post_tick(self) -> None:
        cfg = self.config
        if not bool(cfg.get("qzone_post_enabled", False)):
            return
        state = self._qzone_post_state()
        now = time.time()
        today = time.strftime("%Y-%m-%d")
        hour_min = time.localtime().tm_hour * 60 + time.localtime().tm_min
        lo = self._hhmm_minutes(cfg.get("qzone_post_window_start", "12:00")) or 720
        hi = self._hhmm_minutes(cfg.get("qzone_post_window_end", "22:00")) or 1320
        targets = [str(t).strip() for t in (cfg.get("proactive_targets") or []) if str(t).strip()]
        umo = self._target_umo(targets[0]) if targets else ""

        # 1) 聊天后延迟发：AI 判断值不值得发
        if bool(cfg.get("qzone_chat_post_enabled", True)) and umo:
            delay = float(cfg.get("qzone_chat_post_delay_min", 12) or 12) * 60
            cap = int(cfg.get("qzone_chat_post_daily_cap", 1) or 1)
            last_chat = float(state.get("last_chat_ts", 0) or 0)
            posted_at = float(state.get("last_chat_post_ts", 0) or 0)
            count_day = state.get("chat_post_day", "")
            count = int(state.get("chat_post_count", 0) or 0)
            if count_day != today:
                count = 0
            if (
                lo <= hour_min <= hi
                and last_chat > 0
                and now - last_chat >= delay
                and last_chat > posted_at
                and count < cap
            ):
                recent = self._qzone_recent_chat()
                if recent:
                    mood = self._daily_state()
                    text = await self._qzone_generate(
                        umo,
                        f"【最近的聊天】\n{recent}\n\n"
                        f"【今天的状态】{mood.get('mood')}（精力 {mood.get('energy')}/5）\n\n"
                        "根据上面的聊天，判断有没有值得发到 QQ 空间分享的小事。"
                        "如果有，用你的口吻写一条说说，40 字以内，口语化、像随手发的；"
                        "如果没有值得发的，只输出 [NO]。",
                        "你是干饭鱼，一个活泼的女生。你要决定刚刚的聊天里有没有值得发 QQ 空间的事，"
                        "有就写一条，没有就输出 [NO]，不要解释。",
                    )
                    if text and "[NO]" not in text.upper():
                        if self._qzone_publish(text, await self._pick_qzone_image(cfg, text)):
                            state.update(
                                {
                                    "last_chat_post_ts": last_chat,
                                    "chat_post_day": today,
                                    "chat_post_count": count + 1,
                                }
                            )
                            self._save_json(self.qzone_post_file, state)
                            logger.info(f"[whale-behavior] 聊天后发了空间说说：{text}")

        # 2) 每周 3-4 天随机分享日常
        if bool(cfg.get("qzone_weekly_enabled", True)) and umo:
            items = self._qzone_week_plan(cfg, state)
            done = state.get("week_plan", {}).get("done", [])
            for item in items:
                if item.get("date") != today or today in done:
                    continue
                target_min = int(item.get("hour", 0)) * 60 + int(item.get("minute", 0))
                if hour_min < target_min or hour_min > hi:
                    continue
                mood = self._daily_state()
                weather = ""
                if bool(cfg.get("weather_enabled", False)):
                    info = await asyncio.to_thread(self._weather_info, cfg.get("weather_location") or "")
                    if info:
                        weather = f"{info.get('city', '')}{info.get('desc', '')} {info.get('temp', '')}℃。"
                text = await self._qzone_generate(
                    umo,
                    f"【今天的状态】{mood.get('mood')}（精力 {mood.get('energy')}/5）\n"
                    f"【天气】{weather or '（不知道）'}\n"
                    f"【最近聊天】{self._qzone_recent_chat(6) or '（最近没怎么聊天）'}\n\n"
                    "写一条今天的日常说说，像随手记录生活，40 字以内，口语化、不要 AI 腔。",
                    "你是干饭鱼，一个活泼的女生，正在发 QQ 空间日常。只输出一条说说，不要解释、不要引号。",
                )
                if text and "[NO]" not in text.upper():
                    if self._qzone_publish(text, await self._pick_qzone_image(cfg, text)):
                        state.setdefault("week_plan", {}).setdefault("done", []).append(today)
                        self._save_json(self.qzone_post_file, state)
                        logger.info(f"[whale-behavior] 本周日常说说已发：{text}")
                break

    # ---------- 触发 ----------
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        group = str(event.get_group_id() or event.get_sender_id())
        cfg = self._settings(group)
        if not bool(cfg.get("enabled", True)):
            return

        if bool(cfg.get("group_reply_disabled", False)):
            event.is_at_or_wake_command = False
            logger.info(f"[whale-behavior] 群 {group} 已开启「不回复群聊」，静默")
            return

        policy = self._policy()
        if bool(policy.get("whitelist_enabled")):
            allowed = {str(x) for x in (policy.get("allowed_groups") or [])}
            if group not in allowed:
                event.is_at_or_wake_command = False
                logger.info(f"[whale-behavior] 群 {group} 不在白名单，拦截")
                return
        self._note_target_activity(f"group:{group}")
        await self._collect_chat_images(event, f"group:{group}")

        text = (event.message_str or "").strip()
        self._ensure_proactive_task()
        self._record_history(f"group:{group}", event.get_sender_name(), text)
        sender = str(event.get_sender_id())
        now = time.time()
        self._buffers.setdefault(group, []).append(
            {"ts": now, "sender": sender, "name": event.get_sender_name(), "text": text}
        )
        self._trim(group, cfg)

        self._rel_bump(event)
        self._last_chat_ts = now
        gap = now - self._last_seen.get(group, now)
        self._last_seen[group] = now
        sleepy = self._is_sleeping(cfg)
        try:
            event.set_extra("whale_gap", gap)
            event.set_extra("whale_sleepy", sleepy)
        except Exception:
            pass
        if sleepy and not bool(getattr(event, "is_at_or_wake_command", False)):
            logger.info(f"[whale-behavior] 睡眠时段，群 {group} 不主动接话")
            event.is_at_or_wake_command = False
            return

        if bool(getattr(event, "is_at_or_wake_command", False)):
            # 指令消息不参与连发合并，避免把历史消息拼进命令
            if text.startswith("/"):
                return
            merged = self._merge(group, cfg)
            if merged:
                self._apply_text(event, merged)
            return

        if bool(cfg.get("burst_enabled", True)):
            window_ms = int(cfg.get("burst_window_ms", 1500) or 0)
            if window_ms > 0:
                await asyncio.sleep(window_ms / 1000)
            if any(m["ts"] > now + 1e-6 for m in self._buffers.get(group, [])):
                logger.debug("[whale-behavior] 后面还有消息，交给它合并处理")
                event.is_at_or_wake_command = False
                return

        keywords = [k for k in (cfg.get("keywords") or []) if k]
        hit_keyword = any(k in text for k in keywords)
        reason = "keyword"
        if not hit_keyword:
            level = self._current_level(policy)
            if level <= 1:
                logger.debug("[whale-behavior] L1 极省：非 @/关键词 不主动接话")
                return
            tier = int(cfg.get("tier_slider", 60) or 0)
            tier = max(0, min(100, int(round(tier * self._tier_multiplier(level)))))
            if tier <= 0:
                return
            if tier < 100 and random.random() * 100 >= tier:
                logger.debug(f"[whale-behavior] 摇到不回复（tier={tier}）")
                return
            reason = "probability"

        cooldown = float(cfg.get("cooldown_sec", 30) or 0)
        if cooldown > 0 and time.time() - self._last_reply.get(group, 0.0) < cooldown:
            logger.debug(f"[whale-behavior] 冷却中，跳过（{group}）")
            self._buffers[group] = []
            return

        merged = self._merge(group, cfg) or text
        if bool(cfg.get("context_gate_enabled", False)):
            ok, _reason = await self._context_should_reply(event, group, merged)
            if not ok:
                event.is_at_or_wake_command = False
                self._buffers[group] = []
                return
        self._apply_text(event, merged)
        event.is_at_or_wake_command = True
        event.set_extra("whale_trigger", reason)
        logger.info(
            f"[whale-behavior] 触发插嘴（{'关键词' if hit_keyword else '概率'}）群={group} "
            f"合并={merged[:80]!r}"
        )

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def on_private_message(self, event: AstrMessageEvent):
        """私聊：白名单 + 与群聊相同的开关/连发合并/分句节奏。"""
        policy = self._policy()
        uid = str(event.get_sender_id())

        if bool(policy.get("whitelist_enabled")):
            allowed = {str(x) for x in (policy.get("allowed_private_users") or [])}
            if uid not in allowed:
                event.is_at_or_wake_command = False
                logger.info(f"[whale-behavior] 私聊 {uid} 不在白名单，拦截")
                return
        self._note_target_activity(f"private:{uid}")
        await self._collect_chat_images(event, f"private:{uid}")

        cfg = self._settings(uid)
        if not bool(cfg.get("enabled", True)):
            event.is_at_or_wake_command = False
            return

        text = (event.message_str or "").strip()
        self._ensure_proactive_task()
        self._record_history(f"private:{uid}", event.get_sender_name(), text)
        if text.startswith("/"):
            return

        now = time.time()
        self._buffers.setdefault(uid, []).append({"ts": now, "sender": uid, "name": event.get_sender_name(), "text": text})
        self._trim(uid, cfg)

        self._rel_bump(event)
        self._last_chat_ts = now
        gap = now - self._last_seen.get(uid, now)
        self._last_seen[uid] = now
        try:
            event.set_extra("whale_gap", gap)
            event.set_extra("whale_sleepy", self._is_sleeping(cfg))
        except Exception:
            pass

        # 私聊默认必回，所以走「已唤醒」分支：连发时等对方说完再合并成一条
        if bool(cfg.get("burst_enabled", True)):
            window_ms = int(cfg.get("burst_window_ms", 1500) or 0)
            if window_ms > 0:
                await asyncio.sleep(window_ms / 1000)
            if any(m["ts"] > now + 1e-6 for m in self._buffers.get(uid, [])):
                logger.debug("[whale-behavior] 私聊后面还有消息，交给它合并处理")
                event.is_at_or_wake_command = False
                return

        merged = self._merge(uid, cfg) or text
        self._apply_text(event, merged)

    @filter.on_llm_request()
    async def inject_level_note(self, event: AstrMessageEvent, req: ProviderRequest):
        """按当前峰谷等级给模型一条长度/语气约束。"""
        group = str(event.get_group_id() or event.get_sender_id())
        cfg = self._settings(group)
        if not bool(cfg.get("enabled", True)):
            return
        level = self._current_level(self._policy())
        note = LEVEL_PROMPTS.get(level)
        if not note:
            return
        current = req.system_prompt or ""
        extra = "\n".join(
            x for x in (self._state_note(cfg), self._rel_note(event), self._life_note()) if x
        )
        # 开关：动态状态/关系提示只在内容变化时注入，避免每轮重复占 token
        if bool(cfg.get("state_note_dedupe", True)):
            if extra and self._note_sig.get(group) == extra:
                extra = ""
            elif extra:
                self._note_sig[group] = extra
        req.system_prompt = "\n\n".join(x for x in (current, note, extra) if x)

    # ---------- 静默 + 分句 + 引用/@ + 戳一戳 ----------
    @filter.on_decorating_result()
    async def decorate(self, event: AstrMessageEvent):
        result = event.get_result()
        if result is None or not result.is_llm_result():
            return
        group = str(event.get_group_id() or event.get_sender_id())
        cfg = self._settings(group)

        text = (result.get_plain_text() or "").strip()
        silence_token = str(cfg.get("silence_token", "[SILENT]") or "").strip()
        if silence_token and silence_token in text:
            logger.info("[whale-behavior] 模型选择静默，丢弃本条")
            result.chain.clear()
            return
        if not text:
            result.chain.clear()
            return
        try:
            bkey = (
                f"group:{event.get_group_id()}"
                if event.get_group_id()
                else f"private:{event.get_sender_id()}"
            )
            self._record_bot_history(bkey, self._self_nickname or "小鲸鱼", text)
        except Exception:
            pass

        # 去 AI 味：清掉 markdown 痕迹（只在纯文本结果上做）
        if bool(cfg.get("sanitize", True)) and all(isinstance(c, Plain) for c in result.chain):
            cleaned = self._sanitize(text)
            if cleaned != text:
                result.chain = [Plain(cleaned)]
                text = cleaned

        try:
            event.set_extra("whale_final_text", text)
        except Exception:
            pass

        # 潜水概率：就算触发了，也有一定概率选择不说话
        skip_rate = int(cfg.get("skip_probability", 0) or 0)
        if skip_rate > 0 and random.random() * 100 < skip_rate:
            logger.info(f"[whale-behavior] 潜水概率命中（{skip_rate}%），本条不回")
            result.chain.clear()
            return

        await self._maybe_recall(event, cfg)
        await self._maybe_send_image(event, cfg)

        ack = self._late_ack(group, cfg, event)
        if ack:
            try:
                await asyncio.sleep(0.5)
                await event.send(event.plain_result(ack))
            except Exception:
                pass

        prefix = self._build_prefix(event, text, cfg)
        is_group = bool(event.get_group_id())

        if bool(cfg.get("poke_enabled", True)) and "[poke]" in text:
            text = text.replace("[poke]", "").strip()
            result.chain.clear()
            if text:
                await event.send(event.plain_result(text))
            await self._poke(event)
            return

        marker = str(cfg.get("split_marker", "||") or "||")
        max_segments = max(1, int(cfg.get("max_segments", 4) or 4))
        parts: list[str] = []
        if bool(cfg.get("split_enabled", True)):
            if marker and marker in text:
                parts = [p.strip() for p in text.split(marker) if p.strip()]
            elif bool(cfg.get("split_by_newline", False)):
                parts = [p.strip() for p in text.splitlines() if p.strip()]

        if len(parts) <= 1:
            delay_ms = int(cfg.get("first_delay_ms", 0) or 0)
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000)
            if prefix:
                result.chain = prefix + list(result.chain)
            self._last_reply[group] = time.time()
            await self._maybe_poke(event, cfg)
            return

        if len(parts) > max_segments:
            parts = parts[: max_segments - 1] + ["".join(parts[max_segments - 1 :])]

        self._last_reply[group] = time.time()
        delay_ms = int(cfg.get("segment_delay_ms", 900) or 0)
        first_delay_ms = int(cfg.get("first_delay_ms", 0) or 0)
        jitter_ms = int(cfg.get("jitter_ms", 0) or 0)
        logger.info(f"[whale-behavior] 分句发送 {len(parts)} 条：{parts}")
        result.chain.clear()
        for idx, part in enumerate(parts):
            wait = (first_delay_ms if idx == 0 else delay_ms) / 1000
            if jitter_ms > 0:
                wait = max(0.0, wait + random.uniform(-jitter_ms, jitter_ms) / 1000)
            if wait > 0:
                await asyncio.sleep(wait)
            chain = prefix if (idx == 0 and is_group) else []
            await event.send(MessageChain([*chain, Plain(part)]))
        await self._maybe_poke(event, cfg)

    @staticmethod
    def _sanitize(text: str) -> str:
        """清掉 markdown 痕迹和列表符号，降低 AI 味。"""
        s = text.replace("**", "").replace("__", "").replace("`", "")
        lines = []
        for line in s.splitlines():
            line = line.lstrip()
            if line.startswith("> "):
                line = line[2:]
            if line.startswith("- ") or line.startswith("* "):
                line = line[2:]
            lines.append(line)
        s = "\n".join(lines)
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s.strip()


    # ---------- 语境 / 情绪判断 ----------
    # ---------- 语境/情绪判断（含表情包选择，合并为一次调用） ----------
    def _sticker_candidates(self, text: str, limit: int = 18) -> list[dict]:
        path = (
            Path(__file__).resolve().parent.parent
            / "astrbot_plugin_sticker_pack"
            / "stickers"
            / "index.json"
        )
        try:
            data = json.loads(path.read_text("utf-8"))
        except Exception:
            return []
        words = set(re.findall(r"[\u4e00-\u9fff]{1,4}|[a-zA-Z]{2,}", (text or "").lower()))
        scored = []
        for entry in data:
            if not entry.get("id") or not entry.get("file"):
                continue
            hay = (
                str(entry.get("desc") or "")
                + " "
                + " ".join(str(t) for t in (entry.get("tags") or []))
            ).lower()
            score = sum(1 for w in words if w in hay)
            scored.append((score, random.random(), entry))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in scored[:limit]]

    async def _gate_llm(self, event: AstrMessageEvent, system_prompt: str, prompt: str, max_tokens: int) -> dict:
        try:
            provider_id = await self.context.get_current_chat_provider_id(
                umo=event.unified_msg_origin
            )
            resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                system_prompt=system_prompt,
                prompt=prompt,
                max_tokens=max_tokens,
            )
            text = (getattr(resp, "completion_text", "") or "").strip()
            m = re.search(r"\{.*\}", text, re.S)
            return json.loads(m.group(0)) if m else {}
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[whale-behavior] 语境判断子调用失败: {exc}")
            return {}

    async def _context_should_reply(self, event: AstrMessageEvent, group: str, merged: str) -> tuple[bool, str]:
        """两段式：先判断要不要接话/要不要表情（不注入候选），确认要表情后再单独选图。"""
        cfg = self._settings(group)
        max_recent = int(cfg.get("context_gate_max_recent", 8) or 8)
        hist = list(self._buffers.get(group, []))[-max_recent:]
        lines = []
        for item in hist:
            name = item.get("name") or item.get("sender") or "群友"
            text = str(item.get("text") or "").strip()
            if text:
                lines.append(f"{name}: {text}")
        transcript = "\n".join(lines) if lines else (merged or "")

        stage1_system = (
            "你是群聊气氛观察员。判断机器人现在插话是否合适，并判断此刻适不适合带一张表情包。"
            "考虑：话题是否严肃/悲伤/争吵/敏感；说话人的情绪；是否在跟别人对话；"
            "是否已经有人在回应；机器人活泼的语气此刻是否突兀。"
            '只输出 JSON，不要解释：{"reply": true 或 false, "want_sticker": true 或 false, '
            '"mood": "开心/平静/敷衍之一", "reason": "一句话原因"}'
        )
        stage1_prompt = (
            f"【最近的群聊】\n{transcript}\n\n"
            f"【现在这条消息】\n{merged}\n\n"
            "现在适合接话吗？适合带表情吗？"
        )
        data = await self._gate_llm(event, stage1_system, stage1_prompt, 140)
        if not data:
            return True, "gate-error"
        reply = bool(data.get("reply", True))
        want_sticker = bool(data.get("want_sticker", False))
        reason = str(data.get("reason") or "").strip()
        mood = str(data.get("mood") or "平静").strip()
        sid = None

        if reply and want_sticker:
            stickers = self._sticker_candidates(transcript + "\n" + merged)
            if stickers:
                sticker_lines = "\n".join(
                    f"- {e['id']}：{e.get('desc', '')[:40]}" for e in stickers
                )
                stage2_system = (
                    "你是表情包挑图助手。根据当前群聊气氛，从候选里选一张最贴切的表情包；"
                    "拿不准就 null。只输出 JSON，不要解释：{\"sticker\": \"候选id或null\"}"
                )
                stage2_prompt = (
                    f"【最近的群聊】\n{transcript}\n\n"
                    f"【现在这条消息】\n{merged}\n\n"
                    f"【候选表情】\n{sticker_lines}\n\n"
                    "选哪张？"
                )
                data2 = await self._gate_llm(event, stage2_system, stage2_prompt, 60)
                raw = data2.get("sticker")
                sid = str(raw).strip() if raw else None
                valid = {str(e["id"]) for e in stickers}
                if sid not in valid:
                    sid = None

        try:
            event.set_extra(
                "context_gate",
                {"ran": True, "reply": reply, "sticker_id": sid, "mood": mood, "reason": reason},
            )
        except Exception:
            pass
        if not reply:
            logger.info(f"[whale-behavior] 语境判断：不接话（{reason or '气氛不合适'}）")
        elif sid:
            logger.info(f"[whale-behavior] 语境判断：接话并发表情 {sid}（{reason}）")
        return reply, reason

    # ---------- 主动找人聊天 ----------
    @staticmethod
    def _hhmm_minutes(text: str) -> int | None:
        try:
            h, m = str(text).strip().split(":")
            return int(h) * 60 + int(m)
        except Exception:
            return None

    def _in_active_hours(self, ranges: str) -> bool:
        now = time.localtime()
        cur = now.tm_hour * 60 + now.tm_min
        for part in str(ranges or "").replace("，", ",").split(","):
            part = part.strip()
            if "-" not in part:
                continue
            a, b = part.split("-", 1)
            start, end = self._hhmm_minutes(a), self._hhmm_minutes(b)
            if start is None or end is None:
                continue
            if start <= end:
                if start <= cur < end:
                    return True
            else:
                if cur >= start or cur < end:
                    return True
        return False

    @staticmethod
    def _target_umo(target: str) -> str:
        target = str(target).strip()
        if target.startswith("private:"):
            return f"default:FriendMessage:{target.split(':', 1)[1]}"
        if target.startswith("group:"):
            return f"default:GroupMessage:{target.split(':', 1)[1]}"
        return f"default:FriendMessage:{target}"

    def _record_history(self, key: str, name: str, text: str) -> None:
        if not text:
            return
        bucket = self._history.setdefault(key, [])
        bucket.append({"ts": time.time(), "name": name, "text": text[:200]})
        del bucket[:-80]
        self._save_json(self.history_file, self._history)

    # ---------- 主动消息：状态 / 配置 / 命令 ----------
    def _proactive_state(self) -> dict:
        state = self._load_json(self.proactive_state_file, {})
        return state if isinstance(state, dict) else {}

    def _save_proactive_state(self, state: dict) -> None:
        self._save_json(self.proactive_state_file, state)

    def _note_target_activity(self, key: str) -> None:
        """用户发来消息：记录活跃时间并清空未回复计数。"""
        try:
            state = self._proactive_state()
            entry = state.setdefault("targets", {}).setdefault(key, {})
            entry["last_user_ts"] = time.time()
            entry["unanswered"] = 0
            self._save_proactive_state(state)
        except Exception:
            pass

    def _record_bot_history(self, key: str, name: str, text: str) -> None:
        if not text:
            return
        try:
            bucket = self._bot_history.setdefault(key, [])
            bucket.append({"ts": time.time(), "name": name, "text": text[:200]})
            del bucket[:-80]
            self._save_json(self.bot_history_file, self._bot_history)
        except Exception:
            pass

    def _proactive_overrides(self) -> dict:
        data = self._load_json(self.proactive_overrides_file, {}) or {}
        return data if isinstance(data, dict) else {}

    def _proactive_target_cfg(self, target: str) -> dict:
        cfg = self.config
        override = (self._proactive_overrides().get(target) or {})

        def pick(key, default):
            if key in override and override[key] not in (None, ""):
                return override[key]
            return cfg.get(key, default)

        is_group = str(target).startswith("group:")
        prompt_default = PROACTIVE_PROMPT_GROUP if is_group else PROACTIVE_PROMPT_PRIVATE
        return {
            "min_interval": float(pick("proactive_min_interval_min", 90) or 90) * 60,
            "max_interval": float(pick("proactive_max_interval_min", 240) or 240) * 60,
            "daily_limit": int(pick("proactive_daily_limit", 6) or 6),
            "silence_min": float(pick("proactive_silence_min", 25) or 25),
            "max_unanswered": int(pick("proactive_max_unanswered", 4) or 4),
            "prompt": str(override.get("prompt") or cfg.get("proactive_prompt_group" if is_group else "proactive_prompt_private") or prompt_default),
        }

    def _proactive_history_lines(self, target: str, limit: int = 14, include_bot: bool = True) -> list[str]:
        items = []
        for src in (self._history, self._bot_history if include_bot else {}):
            for it in (src.get(target) or []):
                text = str(it.get("text") or "").strip()
                if text:
                    items.append((float(it.get("ts") or 0), str(it.get("name") or "对方"), text))
        items.sort(key=lambda x: x[0])
        return [f"{name}: {text}" for _, name, text in items[-limit:]]

    def _next_proactive_at(self, entry: dict, tcfg: dict) -> float:
        last_sent = float(entry.get("last_sent") or 0)
        last_user = float(entry.get("last_user_ts") or 0)
        by_interval = last_sent + tcfg["min_interval"] if last_sent else 0
        by_silence = last_user + tcfg["silence_min"] * 60 if last_user else 0
        return max(by_interval, by_silence)

    def _split_proactive(self, text: str) -> list[str]:
        cfg = self.config
        if not bool(cfg.get("proactive_split_enabled", True)):
            return [text]
        parts = [x.strip() for x in re.split(r"(?<=[。！？!?…~\n])\s*", text) if x.strip()]
        max_parts = max(1, int(cfg.get("proactive_split_max", 3) or 3))
        if len(parts) > max_parts:
            head = parts[: max_parts - 1]
            tail = "".join(parts[max_parts - 1 :])
            parts = head + ([tail] if tail.strip() else [])
        return parts or [text]

    def _fill_proactive_prompt(self, template: str, history: str, unanswered: int, silence_min: int) -> str:
        now = time.localtime()
        text = template
        text = text.replace("{{current_time}}", time.strftime("%H:%M", now))
        text = text.replace("{{date}}", time.strftime("%Y-%m-%d", now))
        text = text.replace("{{unanswered_count}}", str(unanswered))
        text = text.replace("{{silence_minutes}}", str(int(silence_min)))
        text = text.replace("{{history}}", history)
        if "{{history}}" not in template:
            text = text + "\n\n【最近的聊天】\n" + history
        return text

    async def _send_proactive_to(self, target: str, force: bool = False) -> tuple[bool, str]:
        """给某个对象生成并发送一条主动消息；返回 (是否成功, 文本)。"""
        cfg = self.config
        state = self._proactive_state()
        entry = state.setdefault("targets", {}).setdefault(target, {})
        today = time.strftime("%Y-%m-%d")
        if entry.get("day") != today:
            entry["day"] = today
            entry["count"] = 0
        tcfg = self._proactive_target_cfg(target)
        if not force and int(entry.get("unanswered") or 0) >= tcfg["max_unanswered"]:
            return False, ""
        if not force and int(entry.get("count") or 0) >= tcfg["daily_limit"]:
            return False, ""
        history = self._proactive_history_lines(
            target, include_bot=bool(cfg.get("proactive_include_bot", True))
        )
        history_text = "\n".join(history) or "（还没有聊过天）"
        prompt = self._fill_proactive_prompt(
            tcfg["prompt"], history_text, int(entry.get("unanswered") or 0), int(tcfg["silence_min"])
        )
        try:
            umo = self._target_umo(target)
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)
            resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                system_prompt=PROACTIVE_SYSTEM_PROMPT,
                prompt=prompt,
                max_tokens=160,
            )
            text = (getattr(resp, "completion_text", "") or "").strip().strip('"“”')
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[whale-behavior] 主动消息生成失败: {exc}")
            return False, ""
        text = " ".join(x for x in text.split("\n") if x.strip()).strip()
        if not text or "[SILENT]" in text:
            return False, ""
        segments = self._split_proactive(text)
        umo = self._target_umo(target)
        split_min = float(cfg.get("proactive_split_min_sec", 1.5) or 1.5)
        split_max = float(cfg.get("proactive_split_max_sec", 3.5) or 3.5)
        if split_max < split_min:
            split_max = split_min
        sent = True
        for i, seg in enumerate(segments):
            try:
                ok = await self.context.send_message(umo, MessageChain().message(seg))
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[whale-behavior] 主动消息发送失败: {exc}")
                ok = False
            if not ok:
                sent = False
                break
            if i < len(segments) - 1:
                await asyncio.sleep(random.uniform(split_min, split_max))
        if not sent:
            return False, text
        self._record_bot_history(target, self._self_nickname or "小鲸鱼", text)
        entry["last_sent"] = time.time()
        entry["count"] = int(entry.get("count") or 0) + 1
        entry["unanswered"] = int(entry.get("unanswered") or 0) + 1
        entry["next_at"] = self._next_proactive_at(entry, tcfg)
        self._save_proactive_state(state)
        logger.info(
            f"[whale-behavior] 主动消息 -> {target}（第 {entry['count']} 条，未回复 {entry['unanswered']}）：{text[:50]}"
        )
        return True, text

    async def _process_proactive_commands(self) -> None:
        path = self.proactive_cmd_file
        if not path.exists():
            return
        try:
            cmd = json.loads(path.read_text("utf-8-sig"))
        except Exception:
            path.unlink(missing_ok=True)
            return
        path.unlink(missing_ok=True)
        action = str(cmd.get("action") or "")
        target = str(cmd.get("target") or "").strip()
        if not target:
            return
        state = self._proactive_state()
        entry = state.setdefault("targets", {}).setdefault(target, {})
        if action == "reset":
            state["targets"].pop(target, None)
            self._save_proactive_state(state)
            logger.info(f"[whale-behavior] 主动消息状态已重置：{target}")
        elif action == "pause":
            entry["paused"] = True
            self._save_proactive_state(state)
            logger.info(f"[whale-behavior] 已暂停主动消息：{target}")
        elif action == "resume":
            entry["paused"] = False
            self._save_proactive_state(state)
            logger.info(f"[whale-behavior] 已恢复主动消息：{target}")
        elif action == "send":
            await self._send_proactive_to(target, force=True)

    async def _proactive_tick(self) -> None:
        cfg = self.config
        await self._ensure_life_timeline()
        await self._daily_greetings()
        await self._maybe_update_signature()
        await self._qzone_post_tick()
        await self._weather_alert_tick()
        await self._process_proactive_commands()
        if not bool(cfg.get("proactive_enabled", False)):
            return
        targets = [str(t).strip() for t in (cfg.get("proactive_targets") or []) if str(t).strip()]
        if not targets:
            return
        if not self._in_active_hours(cfg.get("proactive_active_hours") or "09:00-23:30"):
            return
        if self._is_sleeping(cfg):
            return
        now = time.time()
        for target in targets:
            state = self._proactive_state()
            entry = state.setdefault("targets", {}).setdefault(target, {})
            tcfg = self._proactive_target_cfg(target)
            if entry.get("paused"):
                continue
            today = time.strftime("%Y-%m-%d")
            if entry.get("day") != today:
                entry["day"] = today
                entry["count"] = 0
            if not entry.get("last_user_ts"):
                # 首次见到该对象：从当前时间开始计算沉默，避免启动就发
                entry["last_user_ts"] = now
                self._save_proactive_state(state)
                continue
            if int(entry.get("count") or 0) >= tcfg["daily_limit"]:
                continue
            if int(entry.get("unanswered") or 0) >= tcfg["max_unanswered"]:
                continue
            last_user = float(entry.get("last_user_ts") or 0)
            if now - last_user < tcfg["silence_min"] * 60:
                continue
            last_sent = float(entry.get("last_sent") or 0)
            interval = random.uniform(tcfg["min_interval"], tcfg["max_interval"])
            if last_sent and now - last_sent < interval:
                continue
            await self._send_proactive_to(target)

    async def _proactive_loop(self) -> None:
        await asyncio.sleep(25)
        while True:
            try:
                await self._proactive_tick()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[whale-behavior] 主动聊天循环异常: {exc}")
            await asyncio.sleep(60)

    def _ensure_proactive_task(self) -> None:
        if self._proactive_task is not None and not self._proactive_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
            self._proactive_task = loop.create_task(self._proactive_loop())
            logger.info("[whale-behavior] 主动聊天循环已启动")
        except Exception:
            pass

    def _build_prefix(self, event: AstrMessageEvent, text: str, cfg: dict) -> list:
        if not event.get_group_id():
            return []
        prefix: list = []
        quote_rate = int(cfg.get("quote_rate", 15) or 0)
        at_rate = int(cfg.get("at_rate", 0) or 0)
        msg_id = getattr(event.message_obj, "message_id", None)
        if quote_rate > 0 and msg_id and random.random() * 100 < quote_rate:
            prefix.append(
                Reply(
                    id=str(msg_id),
                    sender_id=int(event.get_sender_id() or 0),
                    sender_nickname=event.get_sender_name(),
                    time=int(time.time()),
                    message_str=text[:60],
                )
            )
        if at_rate > 0 and random.random() * 100 < at_rate:
            prefix.append(At(qq=str(event.get_sender_id())))
        return prefix

    async def _poke(self, event: AstrMessageEvent) -> None:
        try:
            bot = getattr(event, "bot", None)
            if bot is None:
                logger.debug("[whale-behavior] 当前平台不支持戳一戳")
                return
            uid = int(event.get_sender_id() or 0)
            group = event.get_group_id()
            if group:
                await bot.call_action("send_poke", group_id=int(group), user_id=uid)
            else:
                await bot.call_action("send_poke", user_id=uid)
            logger.info(f"[whale-behavior] 戳了戳 {uid}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[whale-behavior] 戳一戳失败: {exc}")

    # ---------- 生命周期：AstrBot 启动/插件激活时自动拉起循环 ----------
    async def initialize(self) -> None:
        """插件被激活时启动主动聊天循环（不需要等第一条消息）。"""
        self._ensure_proactive_task()
        logger.info("[whale-behavior] 插件已激活，主动聊天循环就绪")

    async def terminate(self) -> None:
        """插件被禁用/重载时取消后台任务，避免重复循环。"""
        if self._proactive_task is not None and not self._proactive_task.done():
            self._proactive_task.cancel()
        self._proactive_task = None

    # ---------- 指令：/whale show|set|reset ----------
    @filter.command("whale")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def whale_cmd(self, event: AstrMessageEvent):
        """群级行为配置：/whale show | /whale set <key> <value> | /whale reset"""
        group = str(event.get_group_id() or "private")
        args = (event.message_str or "").split()
        sub = args[1].lower() if len(args) > 1 else "show"

        if sub == "set" and len(args) >= 4:
            key, value = args[2], " ".join(args[3:])
            if key not in INT_KEYS | BOOL_KEYS | LIST_KEYS | STR_KEYS:
                yield event.plain_result(f"不认识的配置项：{key}")
                return
            try:
                coerced = self._coerce(key, value)
            except ValueError:
                yield event.plain_result(f"值不合法：{value}")
                return
            self._overrides.setdefault(group, {})[key] = coerced
            self._save_overrides()
            yield event.plain_result(f"本群 {key} = {coerced}（已保存）")
            return

        if sub == "reset":
            self._overrides.pop(group, None)
            self._save_overrides()
            yield event.plain_result("本群覆盖已清除，回到全局配置")
            return

        cfg = self._settings(group)
        keys = [
            "tier_slider",
            "cooldown_sec",
            "burst_enabled",
            "burst_window_ms",
            "split_enabled",
            "quote_rate",
            "at_rate",
            "poke_enabled",
        ]
        body = "\n".join(f"- {k}: {cfg.get(k)}" for k in keys)
        over = "是" if group in self._overrides else "否"
        yield event.plain_result(f"群 {group} 生效配置（有覆盖：{over}）：\n{body}")
