"""运营台后端：今日状态、健康自检、备份/恢复、预算、AI 味复盘、隐私与引导。"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG_DIR = DATA / "config"
PLUGIN_DATA = DATA / "plugin_data"
PERSONAS = DATA / "plugins" / "astrbot_plugin_persona_pack" / "personas"
CORE_DIR = PERSONAS / ".core"
WHALE_DIR = DATA / "plugins" / "astrbot_plugin_whale_behavior"
USAGE = PLUGIN_DATA / "usage_tracker" / "usage.jsonl"
TURNS = PLUGIN_DATA / "usage_tracker" / "turns.jsonl"
DIARY_DB = PLUGIN_DATA / "memory_diary" / "diary.db"
FEATURES_FILE = DATA / "console_features.json"
BACKUP_DIR = DATA / "backups"

DEFAULTS = {
    "onboarding_done": False,
    "guide_version": 1,
    "starmap_auto": True,
    "starmap_interval_min": 30,
    "privacy_mask": False,
    "backup_auto": True,
    "budget": {
        "daily_tokens": 200000,
        "daily_voice_chars": 5000,
        "alert_ratio": 0.8,
    },
}


def _read(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text("utf-8-sig"))
    except Exception:
        return default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def settings() -> dict:
    raw = _read(FEATURES_FILE, {}) or {}
    out = json.loads(json.dumps(DEFAULTS))
    out.update({k: raw[k] for k in raw if k in out})
    budget = out.get("budget") or {}
    for k, v in DEFAULTS["budget"].items():
        budget.setdefault(k, v)
    out["budget"] = budget
    return out


def save_settings(patch: dict) -> dict:
    cur = settings()
    for k in ("onboarding_done", "privacy_mask", "backup_auto"):
        if k in patch:
            cur[k] = bool(patch[k])
    if "starmap_auto" in patch:
        cur["starmap_auto"] = bool(patch["starmap_auto"])
    if "starmap_interval_min" in patch:
        try:
            cur["starmap_interval_min"] = max(5, int(patch["starmap_interval_min"]))
        except Exception:
            pass
    if "guide_version" in patch:
        try:
            cur["guide_version"] = int(patch["guide_version"])
        except Exception:
            pass
    if isinstance(patch.get("budget"), dict):
        for k in ("daily_tokens", "daily_voice_chars", "alert_ratio"):
            if k in patch["budget"]:
                try:
                    cur["budget"][k] = max(0, float(patch["budget"][k]))
                except Exception:
                    pass
    _write(FEATURES_FILE, cur)
    return cur


def _port(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.35):
            return True
    except Exception:
        return False


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    except Exception:
        pass
    return total


def _tail_lines(path: Path, n: int = 300) -> list[str]:
    if not path.exists():
        return []
    try:
        lines = path.read_text("utf-8", errors="replace").splitlines()
        return lines[-n:]
    except Exception:
        return []


def today_info() -> dict:
    now = datetime.now()
    st = settings()
    timeline = _read(WHALE_DIR / "life_timeline.json", {}) or {}
    daily = _read(WHALE_DIR / "daily_state.json", {}) or {}
    items = timeline.get("items") or []
    current = ""
    for it in items:
        start = str(it.get("start") or "")
        end = str(it.get("end") or "")
        if start <= now.strftime("%H:%M") <= end:
            current = str(it.get("activity") or "")
            break
    if not current and items:
        current = str(items[-1].get("activity") or "")

    diary = ""
    if DIARY_DB.exists():
        try:
            con = sqlite3.connect(str(DIARY_DB))
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT date, page FROM diary ORDER BY date DESC LIMIT 1").fetchone()
            con.close()
            if row:
                diary = f"{row['date']}  {str(row['page'])[:200]}"
        except Exception:
            pass

    core_mtime = ""
    core_chars = 0
    for f in CORE_DIR.glob("*.md") if CORE_DIR.exists() else []:
        if not f.name.startswith("."):
            core_chars += len(f.read_text("utf-8", errors="replace"))
            core_mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%m-%d %H:%M")
    pending = 0
    pdir = CORE_DIR / ".pending"
    if pdir.exists():
        for f in pdir.glob("*.json"):
            try:
                pending += len(json.loads(f.read_text("utf-8-sig")))
            except Exception:
                pass

    return {
        "ok": True,
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "mood": str(daily.get("mood") or "未知"),
        "energy": daily.get("energy"),
        "hint": str(daily.get("hint") or ""),
        "current": current,
        "diary": diary,
        "core_chars": core_chars,
        "core_updated": core_mtime,
        "core_pending": pending,
        "privacy_mask": st.get("privacy_mask", False),
    }




def memory_info() -> dict:
    layers = []
    try:
        con = sqlite3.connect(str(DIARY_DB))
        raw = con.execute("SELECT COUNT(*) FROM raw_messages").fetchone()[0]
        days = con.execute("SELECT COUNT(*) FROM diary").fetchone()[0]
        last = con.execute("SELECT date FROM diary ORDER BY date DESC LIMIT 1").fetchone()
        con.close()
        layers.append({"name": "原始消息", "count": raw, "desc": "日记插件的全量聊天流水"})
        layers.append({"name": "每日日记", "count": days, "desc": f"最近 {last[0] if last else '—'}"})
    except Exception:
        layers.append({"name": "日记库", "count": 0, "desc": "尚未生成"})

    core_chars = 0
    core_files = 0
    if CORE_DIR.exists():
        for f in CORE_DIR.glob("*.md"):
            if not f.name.startswith("."):
                core_files += 1
                core_chars += len(f.read_text("utf-8", errors="replace"))
    pending = 0
    pdir = CORE_DIR / ".pending"
    if pdir.exists():
        for f in pdir.glob("*.json"):
            try:
                pending += len(json.loads(f.read_text("utf-8-sig")))
            except Exception:
                pass
    layers.append({"name": "核心设定", "count": core_chars, "desc": f"{core_files} 份 · {pending} 条提议待确认"})

    angel_size = 0
    angel_db = PLUGIN_DATA / "astrbot_plugin_angel_memory" / "memory_center" / "index" / "simple_memory.db"
    if angel_db.exists():
        angel_size = angel_db.stat().st_size
    layers.append({"name": "Angel 记忆", "count": 0, "desc": f"库 {angel_size/1024:.0f} KB · 当前未启用抽取"})
    return {
        "ok": True,
        "layers": layers,
        "diary_days": layers[1]["count"] if len(layers) > 1 else 0,
        "core_chars": core_chars,
        "pending": pending,
    }



def _config_issues() -> list[str]:
    issues = []
    for d in (DATA / "plugins").glob("*"):
        schema_path = d / "_conf_schema.json"
        if not schema_path.exists():
            continue
        try:
            schema = json.loads(schema_path.read_text("utf-8-sig"))
        except Exception:
            continue
        if not isinstance(schema, dict):
            continue
        candidates = [
            CONFIG_DIR / f"{d.name}_config.json",
            CONFIG_DIR / f"{d.name.replace('astrbot_plugin_', '')}_config.json",
        ]
        cfg = None
        for c in candidates:
            if c.exists():
                cfg = _read(c, {}) or {}
                break
        if cfg is None:
            continue
        missing = [k for k in schema if k not in cfg]
        if missing:
            issues.append(f"{d.name}: 缺 {', '.join(missing[:3])}")
    return issues

def health_info() -> dict:
    checks = []

    def add(name, ok, detail, hint=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "hint": hint})

    add("AstrBot", _port(6185), "6185 " + ("监听中" if _port(6185) else "未监听"), "运行 scripts/start-qq-agent.ps1")
    napcat_http = _port(6198)
    napcat_ws = _port(6199)
    add("NapCat", napcat_http or napcat_ws, f"6198 {'✓' if napcat_http else '✗'} / 6199 {'✓' if napcat_ws else '✗'}", "检查 NapCat 登录")
    add("控制台", _port(8787), "8787 " + ("正常" if _port(8787) else "异常"))
    add("QQ空间服务", _port(18999), "18999 " + ("正常" if _port(18999) else "未启动"), "运行 Qzone daemon")

    breeze = _read(CONFIG_DIR / "astrbot_plugin_breeze_tts_config.json", {}) or {}
    add("Breeze 语音", bool(breeze.get("api_key")), "API Key " + ("已配置" if breeze.get("api_key") else "未配置"), "在聊天设置里填写 Breeze API Key")

    plugin_dirs = [d for d in (DATA / "plugins").glob("*") if d.is_dir() and (d / "metadata.yaml").exists()]
    add("插件目录", len(plugin_dirs) > 0, f"{len(plugin_dirs)} 个插件")

    log = _tail_lines(ROOT / "run-stdout.log", 400)
    errors = [x for x in log if "ERROR" in x or "Traceback" in x]
    add("启动日志", len(errors) == 0, f"最近 400 行 {len(errors)} 条错误", "打开日志页查看")

    try:
        free_gb = shutil.disk_usage(str(ROOT)).free / 1024**3
        add("磁盘", free_gb > 5, f"剩余 {free_gb:.1f} GB", "清理旧备份或日志")
    except Exception:
        free_gb = 0

    db_size = (DATA / "data_v4.db").stat().st_size if (DATA / "data_v4.db").exists() else 0
    add("数据库", db_size > 0, f"AstrBot DB {db_size/1024/1024:.1f} MB")
    add("日记库", DIARY_DB.exists(), f"diary.db {DIARY_DB.stat().st_size/1024:.0f} KB" if DIARY_DB.exists() else "不存在")
    issues = _config_issues()
    add("插件配置", len(issues) == 0, f"{len(issues)} 个插件配置缺字段", "；".join(issues[:2]) if issues else "")

    ok_count = sum(1 for c in checks if c["ok"])
    return {"ok": True, "checks": checks, "summary": f"{ok_count}/{len(checks)} 项正常", "all_ok": ok_count == len(checks)}


def budget_info() -> dict:
    st = settings()
    day = date.today().isoformat()
    in_tok = out_tok = 0
    calls = 0
    if USAGE.exists():
        for line in _tail_lines(USAGE, 5000):
            try:
                d = json.loads(line)
                ts = datetime.fromtimestamp(float(d.get("ts") or 0)).date().isoformat()
                if ts != day:
                    continue
                calls += 1
                in_tok += int(d.get("in_miss") or 0) + int(d.get("in_cached") or 0)
                out_tok += int(d.get("out") or 0)
            except Exception:
                pass
    total_tok = in_tok + out_tok
    cost = in_tok / 1_000_000 * 2 + out_tok / 1_000_000 * 8
    b = st["budget"]
    limit = float(b.get("daily_tokens") or 0)
    ratio = (total_tok / limit) if limit else 0
    voice_used = 0
    vlog = PLUGIN_DATA / "breeze_tts" / "voice_usage.jsonl"
    if vlog.exists():
        for line in _tail_lines(vlog, 3000):
            try:
                d = json.loads(line)
                if datetime.fromtimestamp(float(d.get("ts") or 0)).date().isoformat() == day:
                    voice_used += int(d.get("chars") or 0)
            except Exception:
                pass
    voice_limit = float(b.get("daily_voice_chars") or 0)
    return {
        "ok": True,
        "date": day,
        "calls": calls,
        "tokens": {"total": total_tok, "in": in_tok, "out": out_tok},
        "cost_cny": round(cost, 3),
        "budget": b,
        "token_ratio": round(ratio, 4),
        "voice_used": voice_used,
        "voice_ratio": round(voice_used / voice_limit, 4) if voice_limit else 0,
        "alert": ratio >= float(b.get("alert_ratio") or 0.8) or (voice_limit and voice_used / voice_limit >= float(b.get("alert_ratio") or 0.8)),
    }


TASTE_MARKERS = [
    "作为 AI", "作为AI", "首先", "其次", "综上", "总之", "希望对你", "建议你",
    "当然可以", "没问题", "理解你的感受", "我理解", "总的来说", "需要注意的是",
    "以下是", "总结", "如果你愿意", "我可以帮你", "请问你", "根据我的训练",
]


def taste_info(limit: int = 20) -> dict:
    rows = []
    total = 0
    flagged = []
    for line in _tail_lines(TURNS, 400):
        try:
            d = json.loads(line)
        except Exception:
            continue
        sp = str(d.get("system_prompt") or "")
        if "只输出 JSON" in sp or "日记" in sp or "日程设计师" in sp or "核心设定" in sp:
            continue
        reply = str(d.get("reply") or "").strip()
        if not reply or len(reply) < 8:
            continue
        total += 1
        hits = [m for m in TASTE_MARKERS if m in reply]
        if hits or len(reply) > 180:
            flagged.append(
                {
                    "ts": datetime.fromtimestamp(float(d.get("ts") or 0)).strftime("%m-%d %H:%M"),
                    "reply": reply[:220],
                    "hits": hits[:4] or (["过长"] if len(reply) > 180 else []),
                }
            )
    flagged = list(reversed(flagged))[:limit]
    return {"ok": True, "total": total, "flagged": flagged, "ratio": round(len(flagged) / total, 3) if total else 0}


MODULES = {
    "personas": ("personas", PERSONAS),
    "config": ("config", CONFIG_DIR),
    "plugin_data": ("plugin_data", PLUGIN_DATA),
    "database": ("database", DATA / "data_v4.db"),
    "whale_state": ("whale_state", WHALE_DIR),
}


def _zip_add(zf: zipfile.ZipFile, arc: str, src: Path) -> int:
    if not src.exists():
        return 0
    if src.is_file():
        zf.write(src, arc)
        return src.stat().st_size
    n = 0
    for f in src.rglob("*"):
        if not f.is_file() or ".git" in f.parts:
            continue
        if "fastembed_cache" in f.parts or "__pycache__" in f.parts:
            continue
        zf.write(f, str(Path(arc) / f.relative_to(src)))
        n += f.stat().st_size
    return n


def create_backup(label: str = "") -> dict:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = "".join(ch for ch in (label or "manual") if ch.isalnum() or ch in "-_")[:20] or "manual"
    name = f"backup-{stamp}-{safe}.zip"
    path = BACKUP_DIR / name
    size = 0
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for mod, (arc, src) in MODULES.items():
            if mod == "database":
                if src.exists():
                    zf.write(src, "database/data_v4.db")
                    size += src.stat().st_size
                continue
            if mod == "whale_state":
                for f in src.glob("*.json"):
                    zf.write(f, "whale_state/" + f.name)
                    size += f.stat().st_size
                continue
            size += _zip_add(zf, arc, src)
        zf.writestr(
            "manifest.json",
            json.dumps(
                {"created_at": datetime.now().isoformat(timespec="seconds"), "modules": list(MODULES), "size_hint": size},
                ensure_ascii=False,
                indent=2,
            ),
        )
    _prune_backups()
    return {"ok": True, "name": name, "size": path.stat().st_size, "path": str(path)}


def _prune_backups(keep: int = 7) -> None:
    files = sorted(BACKUP_DIR.glob("backup-*.zip"), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files[keep:]:
        try:
            f.unlink()
        except Exception:
            pass


def list_backups() -> dict:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for f in sorted(BACKUP_DIR.glob("backup-*.zip"), key=lambda x: x.stat().st_mtime, reverse=True):
        out.append(
            {
                "name": f.name,
                "size_mb": round(f.stat().st_size / 1024 / 1024, 2),
                "time": datetime.fromtimestamp(f.stat().st_mtime).strftime("%m-%d %H:%M:%S"),
            }
        )
    return {"ok": True, "backups": out}


def restore_backup(name: str, modules: list[str] | None = None) -> dict:
    if "/" in name or "\\" in name or ".." in name:
        return {"ok": False, "error": "非法备份名"}
    path = BACKUP_DIR / name
    if not path.exists():
        return {"ok": False, "error": "备份不存在"}
    chosen = [m for m in (modules or list(MODULES)) if m in MODULES]
    if not chosen:
        return {"ok": False, "error": "没有选择模块"}
    has_data = PERSONAS.exists() and any(f.suffix == ".md" for f in PERSONAS.iterdir())
    if has_data:
        create_backup("pre-restore")
    restored = []
    skipped = []
    staging = DATA / ".restore_staging"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(path) as zf:
            zf.extractall(staging)
        for mod in chosen:
            if mod == "database":
                src = staging / "database" / "data_v4.db"
                dst = DATA / "data_v4.db"
                try:
                    shutil.copy2(src, dst)
                    restored.append("database")
                except Exception as exc:
                    skipped.append(f"database: {exc}")
                continue
            if mod == "whale_state":
                src_dir = staging / "whale_state"
                if src_dir.exists():
                    for f in src_dir.glob("*.json"):
                        try:
                            shutil.copy2(f, WHALE_DIR / f.name)
                            restored.append(f"whale_state/{f.name}")
                        except Exception as exc:
                            skipped.append(f"{f.name}: {exc}")
                continue
            arc, dst = MODULES[mod]
            src = staging / arc
            if not src.exists():
                skipped.append(mod)
                continue
            if dst.exists():
                if dst.is_dir():
                    shutil.rmtree(dst, ignore_errors=True)
                else:
                    dst.unlink(missing_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            restored.append(mod)
    except Exception as exc:
        return {"ok": False, "error": f"恢复失败: {exc}", "restored": restored, "skipped": skipped}
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {"ok": True, "restored": restored, "skipped": skipped, "restart_tip": "恢复数据库后建议重启 AstrBot 与控制台"}


def rotate_logs() -> dict:
    result = []
    for name in ("run-stdout.log", "run-stderr.log", "console.log", "shell.log"):
        p = ROOT / name
        if not p.exists() or p.stat().st_size < 5 * 1024 * 1024:
            continue
        try:
            target = p.with_name(p.name + "." + datetime.now().strftime("%Y%m%d"))
            if not target.exists():
                p.rename(target)
                result.append(name)
        except Exception:
            pass
    return {"ok": True, "rotated": result}
