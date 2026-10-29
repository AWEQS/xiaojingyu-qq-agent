r"""小鲸鱼控制台后端：纯标准库，零第三方依赖。

启动：<项目根>\tools\astrbot\Scripts\python.exe <项目根>\console\server.py
（项目根 = 本文件上一级；可用环境变量 ASTRBOT_ROOT 覆盖）
UI：http://127.0.0.1:8787
"""

from __future__ import annotations

import base64
import io
import json
import sqlite3
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlparse

import features as ops
import starmap as sm

ROOT = Path(os.environ.get('ASTRBOT_ROOT', '').strip()).resolve() if os.environ.get('ASTRBOT_ROOT', '').strip() else Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG_DIR = DATA / "config"
PLUGIN_DIR = DATA / "plugins"
PERSONA_DIR = PLUGIN_DIR / "astrbot_plugin_persona_pack" / "personas"
PERSONA_CORE_DIR = PERSONA_DIR / ".core"
PERSONA_CORE_HISTORY = PERSONA_CORE_DIR / ".history"
PERSONA_CORE_PENDING = PERSONA_CORE_DIR / ".pending"
MEMORY_DIR = PLUGIN_DIR / "astrbot_plugin_member_memory" / "memory"
STICKER_DIR = PLUGIN_DIR / "astrbot_plugin_sticker_pack" / "stickers"
NAPCAT_DIR = ROOT / "napcat"
SCRIPTS = ROOT / "scripts"
WEB_DIR = ROOT / "console" / "web"
PYTHON = ROOT / "tools" / "astrbot" / "Scripts" / "python.exe"
PORT = 8787
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW：避免 pythonw 下子进程弹窗
HEALTH_FILE = DATA / "console" / "health.json"   # 由 scripts/watchdog.ps1 写入


def api_health():
    """守护进程写入的健康快照；超过 3 分钟未更新即视为守护未运行。"""
    if not HEALTH_FILE.exists():
        return {"ok": False, "watchdog": False, "verdict": "unknown",
                "reason": "watchdog_not_running", "components": []}
    try:
        snap = json.loads(HEALTH_FILE.read_text("utf-8-sig"))
    except Exception as exc:
        return {"ok": False, "watchdog": False, "verdict": "unknown",
                "reason": f"parse_error: {exc}", "components": []}
    age = time.time() - float(snap.get("ts") or 0)
    snap["age_sec"] = round(age, 1)
    snap["watchdog"] = age < 180
    snap["ok"] = snap.get("verdict") == "ok" and snap["watchdog"]
    return snap


def _qq_logged_in() -> bool:
    """NapCat 本地 HTTP 是否报告已登录。"""
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:6198/get_login_info",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8", "ignore"))
        return bool(data.get("retcode") == 0 and data.get("data"))
    except Exception:
        return False


def api_ready() -> dict:
    """首次运行自检：现场探测（不依赖守护），供概览页引导卡使用。"""
    issues = []

    def add(key: str, title: str, hint: str, tab: str = "") -> None:
        issues.append({"key": key, "title": title, "hint": hint, "tab": tab})

    cfg = read_json(DATA / "cmd_config.json", {}) or {}
    if not (cfg.get("provider") or []):
        add("provider", "还没配置模型", "管理端 → 模型管理，填入 DeepSeek API Key", "links")

    napcat_ok = NAPCAT_DIR.exists() and (
        (NAPCAT_DIR / "napcat.mjs").exists() or any(NAPCAT_DIR.glob("NapCat*"))
    )
    if not napcat_ok:
        add("napcat", "NapCat 协议端未安装", r"运行 scripts\install-napcat.ps1（约 1.5 GB）")
    else:
        cfgdir = NAPCAT_DIR / "config"
        if not (cfgdir.exists() and any(cfgdir.glob("onebot11_*.json"))):
            add("onebot", "OneBot 连接还没配置", r"QQ 登录后运行 scripts\post-login-setup.ps1", "links")
        if not _qq_logged_in():
            add("qq", "QQ 未登录", "在管理端扫码登录机器人 QQ", "links")

    snap = read_json(HEALTH_FILE, {}) or {}
    if time.time() - float(snap.get("ts") or 0) > 180:
        add("watchdog", "守护进程没在运行", "双击「守护服务.bat」，或托盘右键 → 启动守护")

    if not (DATA / "data_v4.db").exists():
        add("chat", "还没有任何对话", "让群里 @ 她一次，或用私聊发条消息试试")

    return {"ready": not issues, "issues": issues, "checked_at": datetime.now().strftime("%H:%M:%S")}


# ---------------------------------------------------------------- helpers
def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text("utf-8-sig"))
    except Exception:
        return default


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8-sig")


def port_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def established_to(port: int) -> int:
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=6,
            creationflags=NO_WINDOW,
        ).stdout
        count = 0
        for line in out.splitlines():
            if f":{port}" in line and "ESTABLISHED" in line.upper():
                count += 1
        return count
    except Exception:
        return 0


def tail(path: Path, lines: int = 120) -> list[str]:
    if not path.exists():
        return []
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            block = min(size, 200_000)
            fh.seek(size - block)
            raw = fh.read().decode("utf-8", "replace")
    except Exception:
        return []
    result = raw.splitlines()[-lines:]
    return [strip_ansi(x) for x in result]


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text).replace("\r", "")


def newest_napcat_log() -> Path | None:
    logs = sorted(NAPCAT_DIR.glob("napcat-live*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def napcat_info() -> dict:
    info = {"uin": "", "group": "", "webui_token": "", "webui_url": ""}
    for f in NAPCAT_DIR.glob("config/onebot11_*.json"):
        m = re.match(r"onebot11_(\d+)\.json$", f.name)
        if m:
            info["uin"] = m.group(1)
            break
    webui = read_json(NAPCAT_DIR / "config" / "webui.json", {}) or {}
    info["webui_token"] = webui.get("token", "")
    if info["webui_token"]:
        info["webui_url"] = f"http://127.0.0.1:6099/webui?token={info['webui_token']}"
    log = newest_napcat_log()
    if log:
        try:
            text = log.read_text("utf-8", "replace")
            groups = re.findall(r"群聊 \[([^\](]+)\((\d+)\)\]", text)
            if groups:
                name, gid = groups[-1]
                info["group"] = f"{name}({gid})"
        except Exception:
            pass
    if not info["group"]:
        names = _group_names()
        if names:
            gid, name = list(names.items())[-1]
            info["group"] = f"{name}({gid})"
    return info


def _model_version_of(model: str) -> str:
    return MODEL_VERSION_MAP.get(str(model or "").strip(), "")


def model_info() -> dict:
    cfg = read_json(DATA / "cmd_config.json", {}) or {}
    runner = (cfg.get("agent_runner") or {}).get("config", {})
    pid = (runner.get("model") or {}).get("provider_id", "")
    providers = cfg.get("provider", []) or []
    sources = {s.get("id"): s for s in (cfg.get("provider_sources") or [])}
    out = {"provider_id": pid, "model": "", "api_base": "", "key_masked": ""}
    for p in providers:
        if p.get("id") == pid:
            out["model"] = p.get("model", "")
            src = sources.get(p.get("provider_source_id"), {})
            out["api_base"] = src.get("api_base", "")
            keys = src.get("key") or []
            if keys:
                k = str(keys[0])
                out["key_masked"] = (k[:6] + "..." + k[-4:]) if len(k) > 12 else "***"
            break
    out["version"] = _model_version_of(out["model"])
    return out


def plugin_versions() -> list[dict]:
    out = []
    for d in sorted(PLUGIN_DIR.glob("astrbot_plugin_*")):
        meta = d / "metadata.yaml"
        ver = ""
        if meta.exists():
            for line in meta.read_text("utf-8", "replace").splitlines():
                if line.startswith("version:"):
                    ver = line.split(":", 1)[1].strip()
                    break
        out.append({"dir": d.name, "version": ver})
    return out


def run_script(name: str) -> dict:
    script = SCRIPTS / name
    if not script.exists():
        return {"ok": False, "error": f"缺少脚本 {name}"}
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        cwd=str(SCRIPTS),
        creationflags=NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"ok": True, "script": name}


# ---------------------------------------------------------------- API
LIFE_FILE = PLUGIN_DIR / "astrbot_plugin_whale_behavior" / "life_timeline.json"


def _hhmm_to_min(text: str) -> int | None:
    try:
        h, m = str(text).strip().split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def life_info() -> dict:
    data = read_json(LIFE_FILE, {}) or {}
    items = data.get("items") or []
    today = datetime.now().strftime("%Y-%m-%d")
    if str(data.get("date") or "") != today:
        return {"date": data.get("date") or "", "activity": "", "next": "", "items": items, "stale": True}
    now_min = datetime.now().hour * 60 + datetime.now().minute
    activity, nxt = "", ""
    for i, it in enumerate(items):
        start = _hhmm_to_min(it.get("start", ""))
        end = _hhmm_to_min(it.get("end", ""))
        if start is None or end is None:
            continue
        if start <= now_min < end:
            activity = f"{it.get('start', '')}-{it.get('end', '')} {it.get('activity', '')}"
            if i + 1 < len(items):
                nxt = f"{items[i + 1].get('start', '')} {items[i + 1].get('activity', '')}"
            break
    return {"date": data.get("date") or "", "activity": activity, "next": nxt, "items": items, "stale": False}


def api_status() -> dict:
    astrbot_up = port_listening(6185) and port_listening(6199)
    napcat_up = port_listening(6099)
    connected = established_to(6199)
    stats = {}
    # 简单读一下今日消息量（NapCat 日志里 接收/发送 行数）
    log = newest_napcat_log()
    if log:
        try:
            text = log.read_text("utf-8", "replace")
            stats["received"] = len(re.findall(r"接收 <-", text))
            stats["sent"] = len(re.findall(r"发送 ->", text))
        except Exception:
            pass
    return {
        "astrbot": {"up": astrbot_up, "webui": "http://127.0.0.1:6185"},
        "napcat": {"up": napcat_up, **napcat_info(), "latency_ms": _napcat_latency()},
        "connection": connected,
        "runtime": {
            "uptime_sec": _napcat_uptime_seconds(),
            "last_active_ts": _last_active_ts(),
            "policy": _policy_summary(),
            "memory_sleep": _memory_sleep_status(),
        },
        "life": life_info(),
        "model": model_info(),
        "plugins": plugin_versions(),
        "stats": stats,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _persona_pack_active() -> str:
    cfg = read_json(DATA / "config" / "astrbot_plugin_persona_pack_config.json", {}) or {}
    return str(cfg.get("default_persona") or "")



PERSONA_STATE_FILE = DATA / "plugins" / "astrbot_plugin_persona_pack" / "state.json"


def _persona_set_active(name: str) -> None:
    """同时更新 persona-pack 的 state.json 与插件配置，确保立即生效。"""
    state = read_json(PERSONA_STATE_FILE, {}) or {}
    if not isinstance(state, dict):
        state = {}
    state.setdefault("bindings", {})
    state["default"] = name
    PERSONA_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PERSONA_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")

    cfg_path = DATA / "config" / "astrbot_plugin_persona_pack_config.json"
    cfg = read_json(cfg_path, {}) or {}
    cfg["default_persona"] = name
    try:
        api_plugin_config_save("persona_pack", cfg)
    except Exception:
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")



def api_persona_rename(old: str, new: str) -> dict:
    pat = r"[\w\-\u4e00-\u9fff]+"
    old = str(old or "").strip()
    new = str(new or "").strip()
    if not re.fullmatch(pat, old) or not re.fullmatch(pat, new):
        return {"ok": False, "error": "人设名只能包含中文、字母、数字、下划线和短横线"}
    if old == new:
        return {"ok": True, "new": new, "unchanged": True}
    old_path = PERSONA_DIR / f"{old}.md"
    new_path = PERSONA_DIR / f"{new}.md"
    if not old_path.exists() or old_path.name.startswith("_"):
        return {"ok": False, "error": "原人设不存在"}
    if new_path.exists():
        return {"ok": False, "error": "目标人设名已存在"}
    try:
        old_path.rename(new_path)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"重命名失败: {exc}"}

    # 核心设定、AI 提议、核心快照
    try:
        core_old = PERSONA_CORE_DIR / f"{old}.md"
        core_new = PERSONA_CORE_DIR / f"{new}.md"
        if core_old.exists() and not core_new.exists():
            core_old.rename(core_new)
        pending_old = PERSONA_CORE_PENDING / f"{old}.json"
        pending_new = PERSONA_CORE_PENDING / f"{new}.json"
        if pending_old.exists() and not pending_new.exists():
            pending_old.rename(pending_new)
        for f in PERSONA_CORE_HISTORY.glob(f"{old}__*.md"):
            target = PERSONA_CORE_HISTORY / f.name.replace(f"{old}__", f"{new}__", 1)
            if not target.exists():
                f.rename(target)
        for f in PERSONA_DIR.joinpath(".history").glob(f"{old}__*.md"):
            target = f.parent / f.name.replace(f"{old}__", f"{new}__", 1)
            if not target.exists():
                f.rename(target)
    except Exception:
        pass

    # 状态与绑定
    state = read_json(PERSONA_STATE_FILE, {}) or {}
    if not isinstance(state, dict):
        state = {}
    state.setdefault("bindings", {})
    if str(state.get("default") or "") == old:
        state["default"] = new
    state["bindings"] = {k: (new if v == old else v) for k, v in state["bindings"].items()}
    PERSONA_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")
    try:
        cfg = read_json(DATA / "config" / "astrbot_plugin_persona_pack_config.json", {}) or {}
        if str(cfg.get("default_persona") or "") == old:
            cfg["default_persona"] = new
            api_plugin_config_save("persona_pack", cfg)
    except Exception:
        pass
    return {"ok": True, "old": old, "new": new, "active": str(state.get("default") or "")}


def api_persona_activate(name: str) -> dict:
    if not re.fullmatch(r"[\w\-\u4e00-\u9fff]+", name or ""):
        return {"ok": False, "error": "非法人设名"}
    path = PERSONA_DIR / f"{name}.md"
    if not path.exists() or path.name.startswith("_"):
        return {"ok": False, "error": "人设不存在"}
    try:
        _persona_set_active(name)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"切换失败: {exc}"}
    return {"ok": True, "active": name}


def api_personas() -> list[dict]:
    out = []
    active = _persona_pack_active()
    if PERSONA_DIR.exists():
        for f in sorted(PERSONA_DIR.glob("*.md")):
            if f.name.startswith("_"):
                continue
            out.append(
                {
                    "name": f.stem,
                    "size": f.stat().st_size,
                    "mtime": datetime.fromtimestamp(f.stat().st_mtime).strftime("%m-%d %H:%M"),
                    "active": f.stem == active,
                }
            )
    return out


def _core_path(name: str):
    return PERSONA_CORE_DIR / f"{name}.md"


def _read_core(name: str) -> str:
    path = _core_path(name)
    if not path.exists():
        return ""
    try:
        return path.read_text("utf-8").strip()
    except Exception:
        return ""


def _write_core(name: str, content: str) -> None:
    PERSONA_CORE_DIR.mkdir(parents=True, exist_ok=True)
    content = str(content or "").strip()
    _core_path(name).write_text(content + ("\n" if content else ""), "utf-8")


def _snapshot_core(name: str) -> None:
    path = _core_path(name)
    if not path.exists():
        return
    old = path.read_text("utf-8").strip()
    if not old:
        return
    PERSONA_CORE_HISTORY.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (PERSONA_CORE_HISTORY / f"{name}__{stamp}.md").write_text(old + "\n", "utf-8")
    files = sorted(PERSONA_CORE_HISTORY.glob(f"{name}__*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    for old_file in files[60:]:
        try:
            old_file.unlink()
        except Exception:
            pass


def _core_history(name: str) -> list[dict]:
    if not PERSONA_CORE_HISTORY.exists():
        return []
    out = []
    for f in sorted(PERSONA_CORE_HISTORY.glob(f"{name}__*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            text = f.read_text("utf-8").strip()
        except Exception:
            continue
        out.append(
            {
                "file": f.name,
                "time": datetime.fromtimestamp(f.stat().st_mtime).strftime("%m-%d %H:%M:%S"),
                "chars": len(text),
                "preview": text[:80].replace("\n", " "),
            }
        )
    return out


def _pending_path(name: str):
    return PERSONA_CORE_PENDING / f"{name}.json"


def _read_pending(name: str) -> list[dict]:
    path = _pending_path(name)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text("utf-8-sig"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_pending(name: str, items: list[dict]) -> None:
    PERSONA_CORE_PENDING.mkdir(parents=True, exist_ok=True)
    _pending_path(name).write_text(json.dumps(items, ensure_ascii=False, indent=2), "utf-8")


def api_persona(name: str) -> dict:
    if not re.fullmatch(r"[\w\-\u4e00-\u9fff]+", name):
        return {"ok": False, "error": "非法人设名"}
    path = PERSONA_DIR / f"{name}.md"
    if not path.exists():
        return {"ok": False, "error": "不存在"}
    core = _read_core(name)
    return {"ok": True, "name": name, "content": path.read_text("utf-8"), "core": core, "core_chars": len(core)}


def api_persona_core_info(name: str) -> dict:
    if not re.fullmatch(r"[\w\-\u4e00-\u9fff]+", name or ""):
        return {"ok": False, "error": "非法人设名"}
    if not (PERSONA_DIR / f"{name}.md").exists():
        return {"ok": False, "error": "人设不存在"}
    return {
        "ok": True,
        "name": name,
        "core": _read_core(name),
        "pending": _read_pending(name),
        "history": _core_history(name),
    }


def api_persona_core_save(name: str, content: str) -> dict:
    if not re.fullmatch(r"[\w\-\u4e00-\u9fff]+", name or ""):
        return {"ok": False, "error": "非法人设名"}
    if not (PERSONA_DIR / f"{name}.md").exists():
        return {"ok": False, "error": "人设不存在"}
    content = str(content or "").strip()
    if len(content) > 4000:
        return {"ok": False, "error": "核心设定建议不超过 4000 字"}
    if content != _read_core(name):
        _snapshot_core(name)
        _write_core(name, content)
    return {"ok": True, "name": name, "chars": len(content)}


def api_persona_core_approve(name: str, pid: str) -> dict:
    items = _read_pending(name)
    target = next((x for x in items if str(x.get("id")) == str(pid)), None)
    if not target:
        return {"ok": False, "error": "提议不存在或已被处理"}
    suggestion = str(target.get("suggestion") or "").strip()
    if not suggestion:
        return {"ok": False, "error": "提议内容为空"}
    current = _read_core(name)
    new_core = (current + "\n\n" + suggestion).strip() if current else suggestion
    if len(new_core) > 4000:
        return {"ok": False, "error": "合并后超过 4000 字，请手动整理"}
    _snapshot_core(name)
    _write_core(name, new_core)
    _write_pending(name, [x for x in items if str(x.get("id")) != str(pid)])
    return {"ok": True, "core": new_core, "pending": _read_pending(name)}


def api_persona_core_reject(name: str, pid: str) -> dict:
    items = _read_pending(name)
    left = [x for x in items if str(x.get("id")) != str(pid)]
    _write_pending(name, left)
    return {"ok": True, "pending": left}


def api_persona_core_rollback(name: str, filename: str) -> dict:
    filename = str(filename or "").strip()
    if "/" in filename or "\\" in filename or ".." in filename:
        return {"ok": False, "error": "非法快照"}
    path = PERSONA_CORE_HISTORY / filename
    if not path.exists() or not path.name.startswith(f"{name}__"):
        return {"ok": False, "error": "快照不存在"}
    content = path.read_text("utf-8").strip()
    _snapshot_core(name)
    _write_core(name, content)
    return {"ok": True, "core": content, "history": _core_history(name)}


def api_persona_save(name: str, content: str) -> dict:
    if not re.fullmatch(r"[\w\-\u4e00-\u9fff]+", name):
        return {"ok": False, "error": "非法人设名"}
    path = PERSONA_DIR / f"{name}.md"
    hist = PERSONA_DIR / ".history"
    hist.mkdir(exist_ok=True)
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy(path, hist / f"{name}__console-{stamp}.md")
    path.write_text(content, "utf-8")
    return {"ok": True, "name": name, "saved_at": datetime.now().strftime("%H:%M:%S")}


def api_persona_delete(name: str) -> dict:
    if not re.fullmatch(r"[\w\-\u4e00-\u9fff]+", name or ""):
        return {"ok": False, "error": "非法人设名"}
    path = PERSONA_DIR / f"{name}.md"
    if not path.exists() or path.name.startswith("_"):
        return {"ok": False, "error": "人设不存在"}
    names = [f.stem for f in sorted(PERSONA_DIR.glob("*.md")) if not f.name.startswith("_")]
    if len(names) <= 1:
        return {"ok": False, "error": "至少保留一个人设"}
    active = _persona_pack_active()
    new_active = ""
    if active == name:
        candidates = [x for x in names if x != name]
        if not candidates:
            return {"ok": False, "error": "没有可切换的其他人设"}
        new_active = candidates[0]
        _persona_set_active(new_active)
    path.unlink()
    try:
        (PERSONA_CORE_DIR / f"{name}.md").unlink(missing_ok=True)
        (PERSONA_CORE_PENDING / f"{name}.json").unlink(missing_ok=True)
        for _p in PERSONA_CORE_HISTORY.glob(f"{name}__*.md"):
            _p.unlink(missing_ok=True)
    except Exception:
        pass
    return {"ok": True, "deleted": name, "new_active": new_active, "remaining": len(names) - 1}


def behavior_path() -> Path:
    return CONFIG_DIR / "astrbot_plugin_whale_behavior_config.json"


def api_behavior() -> dict:
    return read_json(behavior_path(), {}) or {}


def api_behavior_save(patch: dict) -> dict:
    cfg = read_json(behavior_path(), {}) or {}
    cfg.update(patch or {})
    write_json(behavior_path(), cfg)
    return {"ok": True, "need_restart": True, "config": cfg}


def api_stickers() -> list[dict]:
    index = read_json(STICKER_DIR / "index.json", []) or []
    out = []
    for item in index:
        f = STICKER_DIR / str(item.get("file", ""))
        out.append(
            {
                "id": item.get("id", ""),
                "file": item.get("file", ""),
                "desc": item.get("desc", ""),
                "tags": item.get("tags", []),
                "exists": f.exists(),
            }
        )
    return out


def _memory_file(group: str):
    return MEMORY_DIR / f"{group}.json"


def api_memory() -> list[dict]:
    """返回有内容的群档案；空壳群文件顺手清理掉。"""
    out = []
    if not MEMORY_DIR.exists():
        return out
    for f in sorted(MEMORY_DIR.glob("*.json")):
        data = read_json(f, {}) or {}
        members = data.get("members") or {}
        notes = data.get("group_notes") or []
        if not members and not notes:
            try:
                f.unlink()
            except Exception:
                pass
            continue
        names = _group_names()
        out.append(
            {
                "group": data.get("group", f.stem),
                "group_name": names.get(data.get("group", f.stem), ""),
                "members": [
                    {
                        "uid": uid,
                        "name": member.get("name", "") or f"群友{uid[-4:]}",
                        "notes": [n.get("text", "") for n in (member.get("notes") or [])],
                    }
                    for uid, member in members.items()
                ],
                "group_notes": [
                    n.get("text", "") if isinstance(n, dict) else str(n) for n in notes
                ],
            }
        )
    return out


def api_memory_clear(group: str, uid: str) -> dict:
    if not re.fullmatch(r"\d{5,20}", group or ""):
        return {"ok": False, "error": "非法群号"}
    path = _memory_file(group)
    if not path.exists():
        return {"ok": False, "error": "群档案不存在"}
    data = read_json(path, {}) or {}
    members = data.get("members") or {}
    members.pop(str(uid), None)
    data["members"] = members
    if not members and not (data.get("group_notes") or []):
        path.unlink(missing_ok=True)
        return {"ok": True, "group_removed": True}
    write_json(path, data)
    return {"ok": True, "group_removed": False}


def api_memory_clear_group(group: str) -> dict:
    if not re.fullmatch(r"\d{5,20}", group or ""):
        return {"ok": False, "error": "非法群号"}
    path = _memory_file(group)
    if path.exists():
        path.unlink()
    return {"ok": True}


def api_logs(target: str, lines: int) -> list[str]:
    if target == "napcat":
        log = newest_napcat_log()
        return tail(log, lines) if log else []
    return tail(ROOT / "run-stdout.log", lines)


def api_service(action: str, target: str) -> dict:
    mapping = {
        ("astrbot", "start"): "start-all.ps1",
        ("astrbot", "stop"): "stop-all.ps1",
        ("astrbot", "restart"): "restart-astrbot.ps1",
        ("napcat", "start"): "start-napcat.ps1",
        ("napcat", "stop"): "stop-napcat.ps1",
        ("napcat", "restart"): "restart-napcat.ps1",
        ("all", "start"): "start-qq-agent.ps1",
        ("all", "stop"): "stop-qq-agent.ps1",
    }
    script = mapping.get((target, action))
    if not script:
        return {"ok": False, "error": f"不支持 {target}/{action}"}
    return run_script(script)



# ---------------------------------------------------------------- 表情包管理
ALLOWED_IMG = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
STICKER_TRASH = STICKER_DIR / ".trash"


def _sticker_index() -> list:
    return read_json(STICKER_DIR / "index.json", []) or []


def _save_sticker_index(items: list) -> None:
    # 注意：插件按 utf-8（无 BOM）读取，不能用 write_json 的 utf-8-sig
    (STICKER_DIR / "index.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=2), "utf-8"
    )


def api_sticker_add(payload: dict) -> dict:
    name = str(payload.get("filename") or "sticker.png")
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_IMG:
        return {"ok": False, "error": f"不支持的图片格式 {ext}"}
    raw = str(payload.get("data") or "")
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    try:
        blob = base64.b64decode(raw, validate=True)
    except Exception:
        return {"ok": False, "error": "图片数据解码失败"}
    if len(blob) > 8 * 1024 * 1024:
        return {"ok": False, "error": "图片超过 8MB"}
    orig_size = len(blob)
    compress = bool(payload.get("compress", _settings().get("autoCompress", True)))
    if compress:
        blob, ext = _compress_image(blob, ext)
    sid = re.sub(r"[^\w\-]", "_", str(payload.get("id") or "")).strip("_")
    if not sid:
        sid = "custom_%d" % int(time.time() * 1000)
    items = _sticker_index()
    existing = {x.get("id") for x in items}
    base_sid = sid
    n = 2
    while sid in existing:
        sid = f"{base_sid}_{n}"
        n += 1
    filename = f"{sid}{ext}"
    (STICKER_DIR / filename).write_bytes(blob)
    items.append(
        {
            "id": sid,
            "file": filename,
            "desc": str(payload.get("desc") or "").strip(),
            "tags": [str(t).strip() for t in (payload.get("tags") or []) if str(t).strip()],
        }
    )
    _save_sticker_index(items)
    return {
        "ok": True,
        "id": sid,
        "file": filename,
        "orig_size": orig_size,
        "size": len(blob),
        "compressed": len(blob) < orig_size,
    }


def api_sticker_delete(sid: str) -> dict:
    items = _sticker_index()
    removed = None
    keep = []
    for it in items:
        if it.get("id") == sid:
            removed = it
        else:
            keep.append(it)
    if removed is None:
        return {"ok": False, "error": "表情不存在"}
    fname = str(removed.get("file") or "")
    if fname:
        src = STICKER_DIR / fname
        if src.exists():
            STICKER_TRASH.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(STICKER_TRASH / src.name))
    _save_sticker_index(keep)
    return {"ok": True, "moved_to_trash": fname}


def api_sticker_update(payload: dict) -> dict:
    sid = str(payload.get("id") or "")
    items = _sticker_index()
    found = False
    for it in items:
        if it.get("id") == sid:
            if "desc" in payload:
                it["desc"] = str(payload.get("desc") or "").strip()
            if "tags" in payload:
                it["tags"] = [str(t).strip() for t in (payload.get("tags") or []) if str(t).strip()]
            found = True
            break
    if not found:
        return {"ok": False, "error": "表情不存在"}
    _save_sticker_index(items)
    return {"ok": True}





# ---------------------------------------------------------------- 群名
GROUP_NAME_CACHE = DATA / "console" / "group_names.json"
GROUP_RE = re.compile(r"群聊 \[([^\]\(]+)\((\d{5,20})\)\]")
_GROUP_SCAN_AT = 0.0


def _group_names() -> dict:
    """从 NapCat 日志里收集群号 -> 群名，缓存到 data/console/group_names.json。"""
    global _GROUP_SCAN_AT
    cache = read_json(GROUP_NAME_CACHE, {}) or {}
    now = time.time()
    if cache and now - _GROUP_SCAN_AT < 60:
        return cache
    _GROUP_SCAN_AT = now
    before = dict(cache)
    logs = sorted(NAPCAT_DIR.glob("napcat-live*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    for log in logs[:20]:
        try:
            with log.open("rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - 2_000_000))
                text = fh.read().decode("utf-8", "replace")
            for name, gid in GROUP_RE.findall(text):
                name = name.strip()
                if name and gid:
                    cache[gid] = name
        except Exception:
            continue
    if cache != before:
        try:
            GROUP_NAME_CACHE.parent.mkdir(parents=True, exist_ok=True)
            GROUP_NAME_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), "utf-8")
        except Exception:
            pass
    return cache




# ---------------------------------------------------------------- 模型管理
def _models_config():
    return read_json(DATA / "cmd_config.json", {}) or {}


def _mask_key(key) -> str:
    text = str(key or "")
    if len(text) > 12:
        return text[:6] + "..." + text[-4:]
    return "***" if text else ""


MODEL_VERSION_MAP = {
    "deepseek-flash": "DeepSeek-V4.1-Flash-1017",
    "deepseek-chat": "DeepSeek-V4.1-Flash-1017（deepseek-chat 别名）",
    "deepseek-reasoner": "DeepSeek-V4.1-Reasoner（legacy）",
    "deepseek-v4-pro": "DeepSeek-V4-Pro-0813",
}


def _model_version(model: str) -> str:
    return MODEL_VERSION_MAP.get(str(model or "").strip(), "")


def api_models() -> dict:
    cfg = _models_config()
    runner = (cfg.get("agent_runner") or {}).get("config", {})
    current = (runner.get("model") or {}).get("provider_id", "")
    sources = {s.get("id"): s for s in (cfg.get("provider_sources") or [])}
    items = []
    for p in cfg.get("provider") or []:
        src = sources.get(p.get("provider_source_id"), {})
        keys = src.get("key") or []
        items.append(
            {
                "id": p.get("id"),
                "model": p.get("model", ""),
                "api_base": src.get("api_base", ""),
                "key_masked": _mask_key(keys[0] if keys else ""),
                "version": _model_version(p.get("model", "")),
                "current": p.get("id") == current,
            }
        )
    return {"ok": True, "providers": items, "current": current}


def _restart_astrbot_async() -> None:
    try:
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPTS / "restart-astrbot.ps1"),
            ],
            cwd=str(SCRIPTS),
            creationflags=NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def api_models_switch(provider_id: str) -> dict:
    cfg = _models_config()
    ids = {p.get("id") for p in (cfg.get("provider") or [])}
    if provider_id not in ids:
        return {"ok": False, "error": "没有这个模型"}
    cfg.setdefault("agent_runner", {}).setdefault("config", {}).setdefault("model", {})[
        "provider_id"
    ] = provider_id
    cfg.setdefault("provider_settings", {})["default_provider_id"] = provider_id
    write_json(DATA / "cmd_config.json", cfg)
    _restart_astrbot_async()
    return {"ok": True, "provider_id": provider_id, "need_restart": True}


def api_models_delete(provider_id: str) -> dict:
    cfg = _models_config()
    providers = cfg.get("provider") or []
    sources = cfg.get("provider_sources") or []
    target = next((p for p in providers if p.get("id") == provider_id), None)
    if not target:
        return {"ok": False, "error": "没有这个模型"}
    runner = (cfg.get("agent_runner") or {}).get("config", {})
    current = (runner.get("model") or {}).get("provider_id", "")
    if provider_id == current:
        return {"ok": False, "error": "不能删除正在使用的模型，先切换到别的模型"}
    if len(providers) <= 1:
        return {"ok": False, "error": "至少保留一个模型"}
    providers.remove(target)
    src_id = target.get("provider_source_id")
    if src_id and not any(p.get("provider_source_id") == src_id for p in providers):
        sources[:] = [x for x in sources if x.get("id") != src_id]
    write_json(DATA / "cmd_config.json", cfg)
    _restart_astrbot_async()
    return {"ok": True, "provider_id": provider_id, "need_restart": True}


def api_models_add(payload: dict) -> dict:
    pid = str(payload.get("id") or "").strip()
    model = str(payload.get("model") or "").strip()
    base = str(payload.get("api_base") or "").strip()
    key = str(payload.get("api_key") or "").strip()
    if not pid or not model or not base:
        return {"ok": False, "error": "id / model / api_base 都要填"}
    cfg = _models_config()
    providers = cfg.setdefault("provider", [])
    sources = cfg.setdefault("provider_sources", [])
    if any(p.get("id") == pid for p in providers):
        return {"ok": False, "error": "这个 id 已存在"}
    source_id = f"{pid}_source"
    sources.append(
        {
            "id": source_id,
            "provider": "openai",
            "type": "openai_chat_completion",
            "provider_type": "chat_completion",
            "enable": True,
            "key": [key],
            "api_base": base.rstrip("/"),
            "timeout": 120,
            "proxy": "",
            "custom_headers": {},
        }
    )
    providers.append(
        {
            "id": pid,
            "provider_source_id": source_id,
            "model": model,
            "modalities": [],
            "custom_extra_body": {},
            "enable": True,
        }
    )
    write_json(DATA / "cmd_config.json", cfg)
    _restart_astrbot_async()
    return {"ok": True, "provider_id": pid, "need_restart": True}











# ---------------------------------------------------------------- Breeze TTS
BREEZE_PLUGIN = "astrbot_plugin_breeze_tts"
BREEZE_CACHE = DATA / "plugin_data" / "breeze_tts" / "cache"


def _breeze_cfg() -> dict:
    try:
        return (api_plugin_config(BREEZE_PLUGIN).get("config") or {})
    except Exception:
        return {}


def _breeze_api(path: str, method: str = "GET", payload=None, timeout: float = 60):
    cfg = _breeze_cfg()
    key = str(cfg.get("api_key") or "").strip()
    if not key:
        raise RuntimeError("还没有配置 Breeze API Key")
    base = str(cfg.get("base_url") or "https://api.breeze.blue").rstrip("/")
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(base + path, data=body, method=method)
    req.add_header("xi-api-key", key)
    req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _breeze_voices_raw() -> list[dict]:
    raw = _breeze_api("/v1/voices?language_code=zh&page_size=50", timeout=40)
    data = json.loads(raw.decode("utf-8", "replace"))
    items = data.get("voices") if isinstance(data, dict) else data
    if not isinstance(items, list):
        items = []
    out = []
    for v in items:
        if not isinstance(v, dict):
            continue
        vid = str(v.get("voice_id") or v.get("id") or "").strip()
        if not vid:
            continue
        out.append(
            {
                "id": vid,
                "name": str(v.get("name") or vid),
                "category": str(v.get("category") or ""),
                "description": str(v.get("description") or ""),
                "language": str(v.get("language") or v.get("language_code") or ""),
                "preview_url": str(v.get("preview_url") or ""),
            }
        )
    return out


def api_breeze_voices() -> dict:
    try:
        voices = _breeze_voices_raw()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "voices": [], "active": ""}
    cfg = _breeze_cfg()
    return {"ok": True, "voices": voices, "active": str(cfg.get("voice_id") or "")}


def api_breeze_clone(payload: dict) -> dict:
    import base64
    import subprocess as _sp
    import uuid

    name = str(payload.get("name") or "").strip()
    audio_b64 = str(payload.get("audio") or "")
    if not name:
        return {"ok": False, "error": "先给音色起个名字"}
    if not audio_b64:
        return {"ok": False, "error": "没有收到音频"}
    try:
        raw = base64.b64decode(audio_b64)
    except Exception:
        return {"ok": False, "error": "音频解析失败"}
    if len(raw) < 2000:
        return {"ok": False, "error": "音频太短，至少 3 秒"}
    if len(raw) > 20 * 1024 * 1024:
        return {"ok": False, "error": "音频太大（上限 20MB）"}
    BREEZE_CACHE.mkdir(parents=True, exist_ok=True)
    src = BREEZE_CACHE / f"upload_{int(time.time())}.bin"
    src.write_bytes(raw)
    wav = src.with_suffix(".wav")
    ffmpeg = ROOT / "bin" / "ffmpeg.exe"
    try:
        _sp.run(
            [str(ffmpeg), "-y", "-i", str(src), "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)],
            capture_output=True, timeout=120, creationflags=NO_WINDOW,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"音频转换失败: {exc}"}
    if not wav.exists() or wav.stat().st_size < 2000:
        return {"ok": False, "error": "音频转换失败，换 wav/mp3 再试"}
    try:
        boundary = "----BreezeBoundary" + uuid.uuid4().hex
        parts = []

        def field(k, v):
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8"))

        field("name", name)
        field("description", "QQ bot voice clone")
        field("reference_language_code", "zh")
        parts.append(
            (
                f"--{boundary}\r\n"
                f"Content-Disposition: form-data; name=\"files\"; filename=\"ref.wav\"\r\n"
                "Content-Type: audio/wav\r\n\r\n"
            ).encode("utf-8")
        )
        parts.append(wav.read_bytes())
        parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(parts)
        cfg = _breeze_cfg()
        key = str(cfg.get("api_key") or "").strip()
        if not key:
            return {"ok": False, "error": "还没有配置 Breeze API Key"}
        base = str(cfg.get("base_url") or "https://api.breeze.blue").rstrip("/")
        req = urllib.request.Request(base + "/v1/voice-previews/clone", data=body, method="POST")
        req.add_header("xi-api-key", key)
        req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        req.add_header("Accept", "application/json")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        with urllib.request.urlopen(req, timeout=180) as resp:
            preview = json.loads(resp.read().decode("utf-8", "replace"))
        gvid = str(preview.get("generated_voice_id") or preview.get("generatedVoiceId") or "").strip()
        if not gvid:
            return {"ok": False, "error": f"克隆失败: {str(preview)[:200]}"}
        saved = _breeze_api(
            f"/v1/voice-previews/{gvid}/save",
            "POST",
            {"voice_name": name, "language_code": "zh"},
            timeout=120,
        )
        sdata = json.loads(saved.decode("utf-8", "replace"))
        vid = str(
            sdata.get("voice_id")
            or (sdata.get("voice") or {}).get("voice_id")
            or sdata.get("id")
            or ""
        ).strip()
        if not vid:
            return {"ok": False, "error": f"保存音色失败: {str(sdata)[:200]}"}
        cfg2 = _breeze_cfg()
        cfg2["voice_id"] = vid
        api_plugin_config_save(BREEZE_PLUGIN, cfg2)
        try:
            src.unlink(missing_ok=True)
            wav.unlink(missing_ok=True)
        except Exception:
            pass
        return {"ok": True, "id": vid, "name": name}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"调用 Breeze 失败: {exc}"}


def api_breeze_switch(voice_id: str) -> dict:
    voice_id = str(voice_id or "").strip()
    if not voice_id:
        return {"ok": False, "error": "缺少音色"}
    try:
        cfg = _breeze_cfg()
        cfg["voice_id"] = voice_id
        api_plugin_config_save(BREEZE_PLUGIN, cfg)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"保存失败: {exc}"}
    return {"ok": True, "active": voice_id}


def api_breeze_delete(voice_id: str) -> dict:
    voice_id = str(voice_id or "").strip()
    if not voice_id:
        return {"ok": False, "error": "缺少音色"}
    try:
        _breeze_api(f"/v1/voices/{voice_id}", "DELETE", timeout=40)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"删除失败: {exc}"}
    try:
        cfg = _breeze_cfg()
        if str(cfg.get("voice_id") or "") == voice_id:
            cfg["voice_id"] = ""
            api_plugin_config_save(BREEZE_PLUGIN, cfg)
    except Exception:
        pass
    return {"ok": True}


def api_breeze_preview(voice_id: str, text: str):
    voice_id = str(voice_id or "").strip()
    text = str(text or "你好呀，我是小鲸鱼，今天过得怎么样？").strip()[:200]
    if not voice_id:
        return None
    cfg = _breeze_cfg()
    payload = {
        "text": text,
        "model_id": str(cfg.get("model_id") or "breeze-tts-2"),
        "instructions": str(cfg.get("instructions") or ""),
        "voice_settings": {"guidance_scale": float(cfg.get("guidance_scale", 4.0) or 4.0)},
    }
    key = str(cfg.get("api_key") or "").strip()
    if not key:
        return None
    base = str(cfg.get("base_url") or "https://api.breeze.blue").rstrip("/")
    req = urllib.request.Request(
        base + f"/v1/text-to-speech/{voice_id}?output_format=wav_24000",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    req.add_header("xi-api-key", key)
    req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    req.add_header("Accept", "audio/wav")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


# ---------------------------------------------------------------- 聊天日记
DIARY_DB = DATA / "plugin_data" / "memory_diary" / "diary.db"


def _diary_scope_label(umo: str) -> str:
    text = str(umo or "")
    if ":GroupMessage:" in text:
        return "群 " + text.split(":", 2)[-1]
    if ":FriendMessage:" in text:
        return "私聊 " + text.split(":", 2)[-1]
    return text[:40]


def api_diary_list(limit: int = 40) -> dict:
    if not DIARY_DB.exists():
        return {"ok": True, "items": []}
    items = []
    try:
        con = sqlite3.connect(str(DIARY_DB))
        rows = con.execute(
            "SELECT date, umo, page, created_at, msg_count FROM diary ORDER BY date DESC, created_at DESC LIMIT ?",
            (max(1, min(200, int(limit))),),
        ).fetchall()
        con.close()
        for date, umo, page, created_at, msg_count in rows:
            items.append(
                {
                    "date": str(date),
                    "scope": _diary_scope_label(str(umo)),
                    "umo": str(umo),
                    "page": str(page or ""),
                    "msg_count": int(msg_count or 0),
                    "created_at": float(created_at or 0),
                }
            )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"读取日记失败: {exc}", "items": []}
    return {"ok": True, "items": items}


# ---------------------------------------------------------------- 主动消息面板
WHALE_PLUGIN_DIR = PLUGIN_DIR / "astrbot_plugin_whale_behavior"
WHALE_CFG_FILE = DATA / "config" / "astrbot_plugin_whale_behavior_config.json"
WHALE_STATE_FILE = WHALE_PLUGIN_DIR / "proactive_state.json"
WHALE_CMD_FILE = WHALE_PLUGIN_DIR / "proactive_cmd.json"
WHALE_OVERRIDE_FILE = WHALE_PLUGIN_DIR / "proactive_overrides.json"


def api_proactive_status() -> dict:
    cfg = read_json(WHALE_CFG_FILE, {}) or {}
    state = read_json(WHALE_STATE_FILE, {}) or {}
    targets = [str(t).strip() for t in (cfg.get("proactive_targets") or []) if str(t).strip()]
    overrides = read_json(WHALE_OVERRIDE_FILE, {}) or {}
    now = time.time()
    rows = []
    for target in targets:
        ov = overrides.get(target) or {}

        def pick(key, default):
            if key in ov and ov[key] not in (None, ""):
                return ov[key]
            return cfg.get(key, default)

        is_group = target.startswith("group:")
        min_i = float(pick("proactive_min_interval_min", 90) or 90) * 60
        max_i = float(pick("proactive_max_interval_min", 240) or 240) * 60
        daily = int(pick("proactive_daily_limit", 6) or 6)
        silence = float(pick("proactive_silence_min", 25) or 25) * 60
        max_un = int(pick("proactive_max_unanswered", 4) or 4)
        entry = (state.get("targets") or {}).get(target) or {}
        last_sent = float(entry.get("last_sent") or 0)
        last_user = float(entry.get("last_user_ts") or 0)
        count = int(entry.get("count") or 0)
        unanswered = int(entry.get("unanswered") or 0)
        paused = bool(entry.get("paused"))
        by_interval = last_sent + min_i if last_sent else 0
        by_silence = last_user + silence if last_user else 0
        next_at = max(by_interval, by_silence) if last_user or last_sent else 0
        status = "ready"
        if paused:
            status = "paused"
        elif count >= daily:
            status = "limit"
        elif unanswered >= max_un:
            status = "silence"
        elif next_at and now < next_at:
            status = "waiting"
        rows.append(
            {
                "target": target,
                "is_group": is_group,
                "paused": paused,
                "count": count,
                "daily_limit": daily,
                "unanswered": unanswered,
                "max_unanswered": max_un,
                "silence_min": int(silence / 60),
                "min_interval_min": int(min_i / 60),
                "max_interval_min": int(max_i / 60),
                "last_sent": last_sent,
                "last_user_ts": last_user,
                "next_at": next_at,
                "status": status,
                "has_override": bool(ov),
            }
        )
    return {"ok": True, "targets": rows, "enabled": bool(cfg.get("proactive_enabled")), "now": now}


def api_proactive_action(action: str, target: str) -> dict:
    action = str(action or "").strip()
    target = str(target or "").strip()
    if action not in ("send", "reset", "pause", "resume"):
        return {"ok": False, "error": "未知操作"}
    if not target:
        return {"ok": False, "error": "缺少对象"}
    write_json(WHALE_CMD_FILE, {"action": action, "target": target, "ts": time.time()})
    return {"ok": True, "action": action, "target": target}


def api_proactive_override(payload: dict) -> dict:
    target = str(payload.get("target") or "").strip()
    if not target:
        return {"ok": False, "error": "缺少对象"}
    overrides = read_json(WHALE_OVERRIDE_FILE, {}) or {}
    if payload.get("clear"):
        overrides.pop(target, None)
    else:
        item = dict(overrides.get(target) or {})
        for key in (
            "proactive_min_interval_min",
            "proactive_max_interval_min",
            "proactive_daily_limit",
            "proactive_silence_min",
            "proactive_max_unanswered",
        ):
            if key in payload and str(payload[key]).strip() != "":
                try:
                    item[key] = int(float(payload[key]))
                except Exception:
                    pass
        prompt = payload.get("prompt")
        if prompt is not None:
            text = str(prompt).strip()
            if text:
                item["prompt"] = text
            else:
                item.pop("prompt", None)
        overrides[target] = item
    write_json(WHALE_OVERRIDE_FILE, overrides)
    return {"ok": True}


# ---------------------------------------------------------------- 插件市场
_MARKET_CACHE = {"at": 0.0, "items": [], "meta": {}}


def _plugin_installed_versions() -> dict:
    out = {}
    for d in PLUGIN_DIR.glob("astrbot_plugin_*"):
        meta = d / "metadata.yaml"
        ver = ""
        if meta.exists():
            try:
                for line in meta.read_text("utf-8").splitlines():
                    if line.strip().startswith("version:"):
                        ver = line.split(":", 1)[1].strip()
                        break
            except Exception:
                pass
        out[d.name] = ver
    return out


def api_market_list(force: bool = False) -> dict:
    now = time.time()
    if not force and _MARKET_CACHE["items"] and now - _MARKET_CACHE["at"] < 600:
        return {"ok": True, "items": _MARKET_CACHE["items"], "meta": _MARKET_CACHE["meta"], "cached": True}
    try:
        raw = _astrbot_api("/api/v1/plugins/market" + ("?force_refresh=true" if force else ""), timeout=60)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"读取插件市场失败: {exc}"}
    data = raw if isinstance(raw, dict) else {}
    meta = data.get("$meta") or {}
    installed = _plugin_installed_versions()
    items = []
    for key, item in data.items():
        if str(key).startswith("$") or not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        author = str(item.get("author") or "").strip()
        mid = str(item.get("market_plugin_id") or key or "").strip()
        if not mid:
            continue
        items.append(
            {
                "id": mid,
                "name": name,
                "display_name": str(item.get("display_name") or name or mid),
                "author": author,
                "version": str(item.get("version") or ""),
                "desc": str(item.get("desc") or item.get("short_desc") or ""),
                "repo": str(item.get("repo") or ""),
                "logo": str(item.get("logo") or ""),
                "category": str(item.get("category") or "其他"),
                "stars": int(item.get("stars") or 0),
                "downloads": int(item.get("download_count") or 0),
                "updated_at": str(item.get("updated_at") or ""),
                "astrbot_version": str(item.get("astrbot_version") or ""),
                "support_platforms": item.get("support_platforms") or [],
                "download_url": str(item.get("download_url") or ""),
                "installed": name in installed,
                "installed_version": installed.get(name, ""),
                "local_modified": _is_local_modified(name),
                "modify_note": _local_modify_note(name),
            }
        )
    items.sort(key=lambda x: (x["downloads"], x["stars"]), reverse=True)
    _MARKET_CACHE.update({"at": now, "items": items, "meta": meta})
    return {"ok": True, "items": items, "meta": meta, "cached": False}


def api_market_update(plugin_id: str) -> dict:
    plugin_id = str(plugin_id or "").strip()
    item = next((x for x in _MARKET_CACHE["items"] if x["id"] == plugin_id), None)
    if item is None:
        got = api_market_list(force=True)
        if not got.get("ok"):
            return got
        item = next((x for x in _MARKET_CACHE["items"] if x["id"] == plugin_id), None)
    if item is None:
        return {"ok": False, "error": "市场里找不到这个插件"}
    try:
        res = _astrbot_api(
            "/api/v1/plugins/update",
            "POST",
            {"plugin_ids": [item.get("name") or ""], "proxy": None, "ignore_version_check": False},
            timeout=180,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"更新请求失败: {exc}"}
    return {"ok": True, "result": res if isinstance(res, dict) else str(res), "plugin": item}


def api_market_install(plugin_id: str) -> dict:
    plugin_id = str(plugin_id or "").strip()
    if not plugin_id:
        return {"ok": False, "error": "缺少插件 id"}
    item = next((x for x in _MARKET_CACHE["items"] if x["id"] == plugin_id), None)
    if item is None:
        got = api_market_list(force=True)
        if not got.get("ok"):
            return got
        item = next((x for x in _MARKET_CACHE["items"] if x["id"] == plugin_id), None)
    if item is None:
        return {"ok": False, "error": "市场里找不到这个插件"}
    payload = {
        "url": item.get("repo") or "",
        "download_url": item.get("download_url") or "",
        "market_plugin_id": item["id"],
        "install_method": "market",
        "registry_url": None,
        "ignore_version_check": False,
    }
    try:
        res = _astrbot_api("/api/v1/plugins/install/url", "POST", payload, timeout=180)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"安装请求失败: {exc}"}
    return {"ok": True, "result": res if isinstance(res, dict) else str(res), "plugin": item}


# ---------------------------------------------------------------- 对话记录
TURNS_FILE = DATA / "plugin_data" / "usage_tracker" / "turns.jsonl"


def _read_turns() -> list[dict]:
    out = []
    if not TURNS_FILE.exists():
        return out
    try:
        with TURNS_FILE.open("r", encoding="utf-8") as fh:
            for idx, line in enumerate(fh):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                rec["idx"] = idx
                out.append(rec)
    except Exception:
        pass
    return out


def api_turns_list(limit: int = 40) -> dict:
    rows = _read_turns()
    recent = rows[-max(1, min(200, int(limit))):]
    items = []
    for r in reversed(recent):
        usage = r.get("usage") or {}
        tokens = int(usage.get("miss", 0)) + int(usage.get("cached", 0)) + int(usage.get("out", 0))
        items.append(
            {
                "idx": r.get("idx"),
                "ts": r.get("ts"),
                "model": r.get("model"),
                "tokens": tokens,
                "cached": int(usage.get("cached", 0)),
                "prompt_preview": (r.get("prompt") or "").strip()[:60],
                "reply_preview": (r.get("reply") or "").strip()[:60],
            }
        )
    return {"ok": True, "items": items, "total": len(rows)}


def api_turns_detail(idx: int) -> dict:
    rows = _read_turns()
    for r in rows:
        if r.get("idx") == idx:
            usage = r.get("usage") or {}
            miss = int(usage.get("miss", 0))
            cached = int(usage.get("cached", 0))
            out = int(usage.get("out", 0))
            input_total = miss + cached
            rec = dict(r)
            rec["usage"] = {
                "miss": miss,
                "cached": cached,
                "out": out,
                "total": miss + cached + out,
                "hit_rate": round(cached / input_total * 100, 1) if input_total else 0.0,
            }
            rec["cost_usd"] = round(
                _row_cost_usd(str(r.get("model") or ""), miss, cached, out, float(r.get("ts") or 0)),
                6,
            )
            rec["cost_cny"] = round(rec["cost_usd"] * USD_CNY, 4)
            return {"ok": True, "turn": rec}
    return {"ok": False, "error": "找不到这条记录"}


# ---------------------------------------------------------------- Token 用量统计
USAGE_FILE = DATA / "plugin_data" / "usage_tracker" / "usage.jsonl"
USD_CNY = 7.1
# 单位：美元 / 1M tokens；(谷时, 峰时)
MODEL_PRICES = {
    "flash": {"hit": (0.003, 0.006), "miss": (0.15, 0.3), "out": (0.6, 1.2)},
    "pro": {"hit": (0.022, 0.044), "miss": (0.66, 1.32), "out": (1.98, 3.96)},
}


def _is_peak(ts: float) -> bool:
    """北京时间周一~周五 09-12、14-18 为高峰。"""
    import datetime as _dt

    local = _dt.datetime.fromtimestamp(ts, _dt.timezone(_dt.timedelta(hours=8)))
    if local.weekday() >= 5:
        return False
    return (9 <= local.hour < 12) or (14 <= local.hour < 18)


def _model_family(model: str) -> str:
    return "pro" if "pro" in str(model or "").lower() else "flash"


def _row_cost_usd(model: str, miss: int, cached: int, out: int, ts: float) -> float:
    p = MODEL_PRICES[_model_family(model)]
    idx = 1 if _is_peak(ts) else 0
    return (
        miss / 1_000_000 * p["miss"][idx]
        + cached / 1_000_000 * p["hit"][idx]
        + out / 1_000_000 * p["out"][idx]
    )


def _local_day(ts: float) -> str:
    import datetime as _dt

    return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _load_usage_rows() -> list[dict]:
    rows = []
    if USAGE_FILE.exists():
        try:
            with USAGE_FILE.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        continue
        except Exception:
            pass
    return rows


def _load_legacy_rows(before_ts: float | None) -> list[dict]:
    """AstrBot 自带的 provider_stats（只含主对话），作为历史数据补齐。"""
    import datetime as _dt
    import sqlite3

    out = []
    db = DATA / "data_v4.db"
    if not db.exists():
        return out
    try:
        con = sqlite3.connect(str(db))
        for created, model, miss, cached, out_tok in con.execute(
            "select created_at, provider_model, token_input_other, token_input_cached, token_output from provider_stats"
        ):
            try:
                ts = _dt.datetime.fromisoformat(str(created)).timestamp()
            except Exception:
                continue
            if before_ts is not None and ts >= before_ts:
                continue
            out.append(
                {
                    "ts": ts,
                    "model": str(model or "deepseek-chat"),
                    "in_miss": int(miss or 0),
                    "in_cached": int(cached or 0),
                    "out": int(out_tok or 0),
                    "umo": "",
                }
            )
        con.close()
    except Exception:
        pass
    return out


def api_usage_stats(days: int = 30) -> dict:
    days = max(1, min(180, int(days or 30)))
    rows = _load_usage_rows()
    first_ts = min((float(r.get("ts", 0) or 0) for r in rows), default=None)
    rows += _load_legacy_rows(first_ts)
    buckets: dict[str, dict] = {}
    models: dict[str, dict] = {}
    for r in rows:
        try:
            ts = float(r.get("ts", 0) or 0)
            miss = int(r.get("in_miss", 0) or 0)
            cached = int(r.get("in_cached", 0) or 0)
            out = int(r.get("out", 0) or 0)
            model = str(r.get("model") or "unknown")
        except Exception:
            continue
        if ts <= 0:
            continue
        day = _local_day(ts)
        cost = _row_cost_usd(model, miss, cached, out, ts)
        b = buckets.setdefault(
            day, {"date": day, "miss": 0, "cached": 0, "out": 0, "cost_usd": 0.0}
        )
        b["miss"] += miss
        b["cached"] += cached
        b["out"] += out
        b["cost_usd"] += cost
        m = models.setdefault(
            model, {"model": model, "miss": 0, "cached": 0, "out": 0, "cost_usd": 0.0}
        )
        m["miss"] += miss
        m["cached"] += cached
        m["out"] += out
        m["cost_usd"] += cost

    day_list = sorted(buckets.values(), key=lambda x: x["date"])[-days:]
    for b in day_list:
        b["cost_usd_raw"] = b["cost_usd"]
        b["cost_cny"] = round(b["cost_usd"] * USD_CNY, 4)
        b["cost_usd"] = round(b["cost_usd"], 4)
        b["tokens"] = b["miss"] + b["cached"] + b["out"]
        total_in = b["miss"] + b["cached"]
        b["hit_rate"] = round(b["cached"] / total_in * 100, 1) if total_in else 0.0

    def window(n: int) -> dict:
        if n:
            import datetime as _dt2

            cutoff = _dt2.date.today() - _dt2.timedelta(days=n - 1)
            sub = [x for x in day_list if _dt2.date.fromisoformat(x["date"]) >= cutoff]
        else:
            sub = day_list
        miss = sum(x["miss"] for x in sub)
        cached = sum(x["cached"] for x in sub)
        out = sum(x["out"] for x in sub)
        cost_usd = sum(x.get("cost_usd_raw", x["cost_usd"]) for x in sub)
        total_in = miss + cached
        return {
            "tokens": miss + cached + out,
            "input": total_in,
            "cached": cached,
            "output": out,
            "cost_usd": round(cost_usd, 6),
            "cost_cny": round(cost_usd * USD_CNY, 4),
            "hit_rate": round(cached / total_in * 100, 1) if total_in else 0.0,
        }

    model_list = []
    for m in models.values():
        total_in = m["miss"] + m["cached"]
        model_list.append(
            {
                "model": m["model"],
                "tokens": m["miss"] + m["cached"] + m["out"],
                "cached": m["cached"],
                "output": m["out"],
                "cost_usd": round(m["cost_usd"], 4),
                "cost_cny": round(m["cost_usd"] * USD_CNY, 2),
                "hit_rate": round(m["cached"] / total_in * 100, 1) if total_in else 0.0,
            }
        )
    model_list.sort(key=lambda x: -x["tokens"])
    return {
        "ok": True,
        "days": day_list,
        "model_list": model_list,
        "today": window(1),
        "week": window(7),
        "month": window(30),
        "all": window(0),
        "usd_cny": USD_CNY,
        "tracked_rows": len(rows),
        "note": "价格按 DeepSeek 官方 flash/pro 峰谷价估算（$/1M tokens），汇率 7.1；历史数据来自 AstrBot provider_stats，新数据来自 usage_tracker。",
    }


# ---------------------------------------------------------------- QQ空间
QZONE_STATE = DATA / "plugin_data" / "astrbot_plugin_qzone_ultra" / "state.json"
QZONE_DAEMON = "http://127.0.0.1:18999"


def _qzone_secret() -> str:
    st = read_json(QZONE_STATE, {}) or {}
    return str(((st.get("runtime") or {}).get("secret")) or "")


def _qzone_api(path: str, method: str = "GET", payload=None):
    secret = _qzone_secret()
    if not secret:
        raise RuntimeError("QQ空间 daemon 尚未启动或无 secret")
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(QZONE_DAEMON + path, data=body, method=method)
    req.add_header("X-Qzone-Secret", secret)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if isinstance(data, dict) and data.get("ok") is False:
        raise RuntimeError(str(data.get("error") or "daemon 返回错误"))
    return data.get("data") if isinstance(data, dict) else data


def api_qzone_status() -> dict:
    try:
        return {"ok": True, "status": _qzone_api("/status")}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def api_qzone_feeds(limit: int = 5) -> dict:
    try:
        return {"ok": True, "feeds": _qzone_api(f"/feeds?limit={max(1, min(20, int(limit)))}")}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}



# ---------------------------------------------------------------- 二维码刷新
def api_qr_refresh() -> dict:
    """QQ 未登录时重启 NapCat 以重新生成二维码。"""
    try:
        conns = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "(Get-NetTCPConnection -State Established -RemotePort 6199 -ErrorAction SilentlyContinue | Measure-Object).Count"],
            capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW,
        )
        if (conns.stdout or "").strip() not in ("", "0"):
            return {"ok": False, "error": "QQ 已登录，不需要刷新二维码"}
    except Exception:
        pass
    qr = NAPCAT_DIR / "cache" / "qrcode.png"
    old = qr.stat().st_mtime if qr.exists() else 0
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(SCRIPTS / "stop-napcat.ps1")],
            capture_output=True, timeout=60, creationflags=NO_WINDOW,
        )
        time.sleep(2)
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(SCRIPTS / "start-napcat.ps1")],
            cwd=str(SCRIPTS), creationflags=NO_WINDOW,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"重启 NapCat 失败: {exc}"}
    deadline = time.time() + 40
    while time.time() < deadline:
        time.sleep(1)
        if qr.exists() and qr.stat().st_mtime > old:
            return {"ok": True, "qr_time": int(qr.stat().st_mtime)}
    if qr.exists():
        return {"ok": True, "qr_time": int(qr.stat().st_mtime), "note": "二维码文件未更新，请打开 NapCat 管理端查看"}
    return {"ok": False, "error": "等待新二维码超时，请打开 NapCat 管理端（6099）登录"}


# ---------------------------------------------------------------- 记忆整理状态
ANGEL_MEMORY_DIR = DATA / "plugin_data" / "astrbot_plugin_angel_memory" / "memory_center"


def _memory_sleep_status() -> dict:
    """返回上次睡眠整理时间；没有记录时返回 None。"""
    center = ANGEL_MEMORY_DIR
    ts = None
    state = read_json(center / "maintenance_state.json", {}) or {}
    try:
        raw = state.get("cleanup_last_sleep_at") or 0
        if float(raw) > 0:
            ts = float(raw)
    except Exception:
        ts = None
    if ts is None:
        backups = sorted((center / "backups").glob("memory_backup_*.json"))
        if backups:
            ts = backups[-1].stat().st_mtime
    if ts is None:
        return {
            "last_ts": None,
            "hours_ago": None,
            "overdue": False,
            "scheduled_hour": 22,
        }
    hours = max(0.0, (time.time() - ts) / 3600.0)
    return {
        "last_ts": int(ts),
        "hours_ago": round(hours, 1),
        "overdue": hours >= 48,
        "scheduled_hour": 22,
    }


# ---------------------------------------------------------------- 运行状态
_RUNTIME_CACHE = {"ts": 0.0, "uptime_sec": None}


def _napcat_latency() -> int | None:
    """调一次 NapCat HTTP 接口，返回往返毫秒。"""
    try:
        t0 = time.perf_counter()
        req = urllib.request.Request(
            "http://127.0.0.1:6198/get_status", data=b"{}", method="POST"
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=3) as resp:
            resp.read()
        return int((time.perf_counter() - t0) * 1000)
    except Exception:
        return None


def _napcat_uptime_seconds() -> int | None:
    """QQ 进程已运行时长（缓存 60 秒）。"""
    now = time.time()
    if now - _RUNTIME_CACHE["ts"] < 60:
        return _RUNTIME_CACHE["uptime_sec"]
    value = None
    try:
        import psutil

        for proc in psutil.process_iter(["name", "exe", "create_time"]):
            try:
                exe = (proc.info.get("exe") or "").lower()
                name = (proc.info.get("name") or "").lower()
                if name == "qq.exe" and "qq-9.9.33" in exe:
                    value = int(now - float(proc.info.get("create_time") or now))
                    break
            except Exception:
                continue
    except Exception:
        value = None
    _RUNTIME_CACHE["ts"] = now
    _RUNTIME_CACHE["uptime_sec"] = value
    return value


def _last_active_ts() -> int | None:
    log = newest_napcat_log()
    if not log:
        return None
    try:
        with log.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 200_000))
            text = fh.read().decode("utf-8", "replace")
    except Exception:
        return None
    year = datetime.now().year
    found = re.findall(r"(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})[^\n]*(?:接收 <-|发送 ->)", text)
    if not found:
        return None
    mo, day, hh, mm, ss = found[-1]
    try:
        return int(datetime(year, int(mo), int(day), int(hh), int(mm), int(ss)).timestamp())
    except Exception:
        return None


def _policy_summary() -> dict:
    policy = _read_policy()
    enabled = bool(policy.get("peak_valley_enabled", True))
    in_peak = _policy_in_peak(policy) if enabled else False
    try:
        if enabled:
            level = int(policy.get("peak_level" if in_peak else "offpeak_level"))
        else:
            level = int(policy.get("fixed_level", 3))
    except Exception:
        level = 3
    return {
        "whitelist": bool(policy.get("whitelist_enabled")),
        "peak_valley_enabled": enabled,
        "in_peak": in_peak,
        "level": max(1, min(4, level)),
    }


# ---------------------------------------------------------------- 设置
SETTINGS_FILE = ROOT / "desktop" / "settings.json"
SETTINGS_DEFAULT = {"closeAction": "quit", "autoStart": False, "autoCompress": True}


def _autostart_lnk() -> Path:
    """Startup 目录里的小鲸鱼快捷方式（开机自启的真实开关）。"""
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "小鲸鱼.lnk"


def _settings() -> dict:
    data = SETTINGS_DEFAULT.copy()
    data.update(read_json(SETTINGS_FILE, {}) or {})
    # 以磁盘上的快捷方式为准：配置写成 true 但快捷方式被删掉了，UI 不该继续显示"已开启"
    data["autoStart"] = _autostart_lnk().exists()
    return data


def _save_settings(patch: dict) -> dict:
    data = _settings()
    for k in SETTINGS_DEFAULT:
        if k in patch:
            data[k] = patch[k]
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), "utf-8"
    )
    return data


def _set_autostart(enabled: bool) -> dict:
    """执行 set-autostart.ps1，并按磁盘结果校验是否真的生效。"""
    script = SCRIPTS / "set-autostart.ps1"
    if not script.exists():
        return {"ok": False, "error": "缺少 set-autostart.ps1"}
    try:
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Enable",
                "1" if enabled else "0",
            ],
            capture_output=True,
            creationflags=NO_WINDOW,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "执行 set-autostart.ps1 超时"}
    actual = _autostart_lnk().exists()
    if actual != bool(enabled):
        detail = (proc.stderr or proc.stdout or b"").decode("utf-8", "ignore").strip()[:300]
        return {
            "ok": False,
            "enabled": actual,
            "error": f"快捷方式未按预期{'创建' if enabled else '删除'}" + (f"：{detail}" if detail else ""),
        }
    return {"ok": True, "enabled": actual}


# ---------------------------------------------------------------- 图片压缩
def _compress_image(blob: bytes, ext: str) -> tuple[bytes, str]:
    """超过 200KB 或边长 512 的图压缩；动图跳过。返回 (数据, 扩展名)。"""
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(blob))
        if getattr(im, "is_animated", False):
            return blob, ext
        w, h = im.size
        if max(w, h) <= 512 and len(blob) <= 200 * 1024:
            return blob, ext
        ratio = min(1.0, 512.0 / max(w, h))
        if ratio < 1:
            im = im.resize((max(1, int(w * ratio)), max(1, int(h * ratio))), Image.LANCZOS)
        has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
        buf = io.BytesIO()
        if has_alpha:
            im.convert("RGBA").save(buf, "PNG", optimize=True)
            newext = ".png"
        else:
            im.convert("RGB").save(buf, "JPEG", quality=85, optimize=True)
            newext = ".jpg"
        out = buf.getvalue()
        if len(out) < len(blob):
            return out, newext
        return blob, ext
    except Exception:
        return blob, ext



# ---------------------------------------------------------------- 批量 AI 打标
STICKER_BATCH = {
    "running": False,
    "total": 0,
    "done": 0,
    "ok": 0,
    "fail": 0,
    "current": "",
    "started": 0,
    "finished": 0,
}


def _batch_worker(ids: list[str]) -> None:
    import threading as _threading

    def run():
        import time as _time

        STICKER_BATCH.update(
            running=True, total=len(ids), done=0, ok=0, fail=0, current="", started=int(_time.time()), finished=0
        )
        for sid in ids:
            STICKER_BATCH["current"] = sid
            try:
                r = api_sticker_auto_tag({"id": sid})
                if r.get("ok"):
                    api_sticker_update({"id": sid, "desc": r.get("desc") or "", "tags": r.get("tags") or []})
                    STICKER_BATCH["ok"] += 1
                else:
                    STICKER_BATCH["fail"] += 1
            except Exception:
                STICKER_BATCH["fail"] += 1
            STICKER_BATCH["done"] += 1
        STICKER_BATCH["running"] = False
        STICKER_BATCH["current"] = ""
        STICKER_BATCH["finished"] = int(_time.time())

    _threading.Thread(target=run, daemon=True, name="sticker-batch-tagger").start()


def api_sticker_batch_start(payload: dict) -> dict:
    if STICKER_BATCH.get("running"):
        return {"ok": False, "error": "已有批量打标任务在跑"}
    ids = [str(x) for x in (payload.get("ids") or []) if str(x).strip()]
    items = _sticker_index()
    if ids:
        targets = [x for x in items if x.get("id") in ids]
    else:
        targets = [
            x
            for x in items
            if not re.search(r"[\u4e00-\u9fff]", (x.get("desc") or ""))
        ]
    if not targets:
        return {"ok": False, "error": "没有需要打标的表情（描述已含中文）"}
    _batch_worker([x["id"] for x in targets])
    return {"ok": True, "total": len(targets)}


# ---------------------------------------------------------------- AI 打标
VISION_PROMPT = (
    "你是表情包标注助手。用中文描述这张表情包：先一句话说明画面内容，"
    "再说明适合在什么语境下发（不超过 50 字）。然后给 3-6 个短标签。"
    '只输出 JSON，不要解释：{"desc":"...","tags":["...","..."]}'
)


def _model_credentials():
    cfg = read_json(DATA / "cmd_config.json", {}) or {}
    runner = (cfg.get("agent_runner") or {}).get("config", {})
    pid = (runner.get("model") or {}).get("provider_id", "")
    providers = {p.get("id"): p for p in (cfg.get("provider") or [])}
    sources = {x.get("id"): x for x in (cfg.get("provider_sources") or [])}
    prov = providers.get(pid) or {}
    src = sources.get(prov.get("provider_source_id"), {})
    base = src.get("api_base") or "https://api.deepseek.com/v1"
    keys = src.get("key") or []
    key = keys[0] if keys else ""
    model = prov.get("model") or "deepseek-chat"
    return base.rstrip("/"), key, model


def _vision_tag(image_bytes: bytes, mime: str) -> dict:
    base, key, model = _model_credentials()
    if not key:
        return {"ok": False, "error": "没找到模型 Key"}
    import base64 as _b64

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:%s;base64,%s" % (mime, _b64.b64encode(image_bytes).decode())},
                    },
                ],
            }
        ],
        "max_tokens": 300,
        "stream": False,
    }
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        text = body["choices"][0]["message"]["content"]
    except Exception as exc:
        return {"ok": False, "error": "识别失败: %s" % exc}
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"ok": False, "error": "模型返回格式异常", "raw": text[:200]}
    try:
        data = json.loads(m.group(0))
    except Exception:
        return {"ok": False, "error": "模型返回 JSON 解析失败", "raw": text[:200]}
    desc = str(data.get("desc") or "").strip()
    tags = [str(t).strip() for t in (data.get("tags") or []) if str(t).strip()][:8]
    return {"ok": True, "desc": desc, "tags": tags}


MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}


def api_sticker_auto_tag(payload: dict) -> dict:
    sid = str(payload.get("id") or "")
    if sid:
        items = _sticker_index()
        entry = next((x for x in items if x.get("id") == sid), None)
        if not entry:
            return {"ok": False, "error": "表情不存在"}
        path = STICKER_DIR / str(entry.get("file") or "")
        if not path.exists():
            return {"ok": False, "error": "图片文件不存在"}
        return _vision_tag(path.read_bytes(), MIME.get(path.suffix.lower(), "image/png"))
    raw = str(payload.get("data") or "")
    if raw.startswith("data:"):
        head, _, raw = raw.partition(",")
        mime = "image/png"
        if head.startswith("data:") and ";" in head:
            mime = head[5:].split(";")[0]
    else:
        mime = MIME.get(Path(str(payload.get("filename") or "")).suffix.lower(), "image/png")
    try:
        blob = base64.b64decode(raw, validate=True)
    except Exception:
        return {"ok": False, "error": "图片数据解码失败"}
    return _vision_tag(blob, mime)



# ---------------------------------------------------------------- AstrBot 插件管理
ASTRBOT_BASE = "http://127.0.0.1:6185"
_AB_TOKEN = {"token": "", "exp": 0.0}

# 自研插件 -> 控制台里的高级面板
PLUGIN_ADVANCED_TAB = {
    "persona_pack": "persona",
    "whale_behavior": "behavior",
    "sticker_pack": "stickers",
    "member_memory": "memory",
}

# 已知功能重叠目录：仅当对方插件【已安装】时才作为冲突提示，否则只在详情里作为「同类方案」参考
LOCAL_MODIFIED_PLUGINS = {
    "astrbot_plugin_angel_memory": "睡眠整理时间已改为 22:00（原版 04:00）",
    "astrbot_plugin_sticker_pack": "已自定义表情接口/字段（旧版 0.2.0）",
    "astrbot_plugin_qzone_ultra": "自动评论已改为随机挑选（本地补丁）",
}

def _is_local_modified(name: str) -> bool:
    name = str(name or "").strip()
    if name in LOCAL_MODIFIED_PLUGINS:
        return True
    if not name.startswith("astrbot_plugin_"):
        return f"astrbot_plugin_{name}" in LOCAL_MODIFIED_PLUGINS
    return False


def _local_modify_note(name: str) -> str:
    name = str(name or "").strip()
    if name in LOCAL_MODIFIED_PLUGINS:
        return LOCAL_MODIFIED_PLUGINS[name]
    if not name.startswith("astrbot_plugin_"):
        return LOCAL_MODIFIED_PLUGINS.get(f"astrbot_plugin_{name}", "")
    return ""


PLUGIN_CONFLICT_CATALOG = {
    "whale_behavior": [
        {"plugin": "proactive_chat", "reason": "两者都会主动发言，同时开容易刷屏"},
        {"plugin": "private_companion", "reason": "拟人状态/主动消息与插嘴概率可能叠加"},
    ],
    "member_memory": [
        {"plugin": "mnemosyne", "reason": "两套长期记忆同时注入会重复占用上下文"},
        {"plugin": "angel_memory", "reason": "同上，建议只留一套记忆方案"},
    ],
    "sticker_pack": [
        {"plugin": "meme_manager", "reason": "两个表情系统可能争抢表情发送逻辑"},
    ],
}


def _astrbot_token(force: bool = False) -> str:
    import jwt as _jwt

    now = time.time()
    if not force and _AB_TOKEN["token"] and _AB_TOKEN["exp"] > now + 60:
        return _AB_TOKEN["token"]
    cfg = read_json(DATA / "cmd_config.json", {}) or {}
    dash = cfg.get("dashboard") or {}
    secret = dash.get("jwt_secret") or ""
    if not secret:
        raise RuntimeError("AstrBot 未配置 dashboard.jwt_secret")
    import datetime as _dtm

    token = _jwt.encode(
        {
            "username": dash.get("username", "astrbot"),
            "exp": _dtm.datetime.now(_dtm.timezone.utc) + _dtm.timedelta(hours=2),
        },
        secret,
        algorithm="HS256",
    )
    _AB_TOKEN["token"] = token
    _AB_TOKEN["exp"] = now + 2 * 3600
    return token


def _astrbot_api(path: str, method: str = "GET", payload=None, timeout: float = 25):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in range(2):
        req = urllib.request.Request(ASTRBOT_BASE + path, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer " + _astrbot_token(force=attempt > 0))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and attempt == 0:
                continue
            raise RuntimeError(f"AstrBot API HTTP {exc.code}: {exc.read()[:200]!r}")
    if isinstance(data, dict) and data.get("status") == "error":
        raise RuntimeError(str(data.get("message") or "AstrBot API 返回错误"))
    return data.get("data") if isinstance(data, dict) else data


def api_version() -> dict:
    """返回前端静态资源构建号（mtime 最大值），用于检测界面是否需要刷新。"""
    files = {}
    build = 0
    try:
        for p in WEB_DIR.glob("*"):
            if p.is_file():
                stamp = int(p.stat().st_mtime * 1000)
                files[p.name] = stamp
                build = max(build, stamp)
    except Exception:
        pass
    return {"ok": True, "build": build, "files": files}


def api_plugins_list() -> dict:
    plugins = _astrbot_api("/api/v1/plugins") or []
    installed = {p.get("name") for p in plugins}
    display = {p.get("name"): (p.get("display_name") or p.get("name")) for p in plugins}
    out = []
    for p in plugins:
        name = p.get("name") or ""
        conflicts = []
        related = []
        for item in PLUGIN_CONFLICT_CATALOG.get(name, []):
            other = item.get("plugin")
            if other in installed:
                conflicts.append(
                    {
                        "plugin": other,
                        "display_name": display.get(other, other),
                        "reason": item.get("reason", ""),
                        "other_active": bool(
                            next((x.get("activated") for x in plugins if x.get("name") == other), False)
                        ),
                    }
                )
            else:
                related.append({"plugin": other, "reason": item.get("reason", "")})
        out.append(
            {
                "name": name,
                "display_name": p.get("display_name") or name,
                "author": p.get("author") or "",
                "desc": p.get("desc") or "",
                "version": p.get("version") or "",
                "activated": bool(p.get("activated")),
                "reserved": bool(p.get("reserved")),
                "repo": p.get("repo") or "",
                "advanced_tab": PLUGIN_ADVANCED_TAB.get(name),
                "conflicts": conflicts,
                "related": related,
                "has_pages": bool(p.get("pages")),
                "local_modified": _is_local_modified(name),
                "modify_note": _local_modify_note(name),
            }
        )
    return {"ok": True, "plugins": out}


def api_plugin_toggle(plugin_id: str, enabled: bool) -> dict:
    _astrbot_api(
        "/api/v1/plugins/enabled",
        "PATCH",
        {"plugin_id": plugin_id, "enabled": bool(enabled)},
    )
    return {"ok": True, "plugin_id": plugin_id, "enabled": bool(enabled)}


def api_plugin_config(plugin_id: str) -> dict:
    data = _astrbot_api(f"/api/v1/plugins/config?plugin_id={urllib.parse.quote(plugin_id)}") or {}
    return {
        "ok": True,
        "plugin_id": plugin_id,
        "metadata": data.get("metadata") or {},
        "config": data.get("config") or {},
        "i18n": data.get("i18n") or {},
        "log_level": data.get("log_level"),
    }


def api_plugin_config_save(plugin_id: str, config: dict) -> dict:
    _astrbot_api(
        "/api/v1/plugins/config",
        "PUT",
        {"plugin_id": plugin_id, "config": config},
    )
    reload_ok = True
    try:
        _astrbot_api("/api/v1/plugins/reload", "POST", {"plugin_id": plugin_id})
    except Exception:
        reload_ok = False
    return {"ok": True, "plugin_id": plugin_id, "reloaded": reload_ok}


def api_plugin_reload(plugin_id: str) -> dict:
    _astrbot_api("/api/v1/plugins/reload", "POST", {"plugin_id": plugin_id})
    return {"ok": True, "plugin_id": plugin_id}



# ---------------------------------------------------------------- 插件卸载
RESERVED_PLUGINS = {"astrbot", "builtin_commands"}


def api_plugin_uninstall(plugin_id: str, delete_config: bool = False, delete_data: bool = False) -> dict:
    if not plugin_id:
        return {"ok": False, "error": "缺少插件名"}
    if plugin_id in RESERVED_PLUGINS:
        return {"ok": False, "error": "内置插件不能卸载"}
    plugins = _astrbot_api("/api/v1/plugins") or []
    found = None
    for p in plugins:
        if p.get("name") == plugin_id:
            found = p
            break
    if not found:
        return {"ok": False, "error": "插件不存在或已卸载"}
    if found.get("reserved"):
        return {"ok": False, "error": "内置插件不能卸载"}
    _astrbot_api(
        "/api/v1/plugins/by-id?plugin_id=" + urllib.parse.quote(plugin_id),
        "DELETE",
        {"delete_config": bool(delete_config), "delete_data": bool(delete_data)},
    )
    return {"ok": True, "plugin_id": plugin_id}




# ---------------------------------------------------------------- 白名单候选
CANDIDATE_GROUP_RE = re.compile(r"群聊 \[([^\]\(]+)\((\d{5,20})\)\]")
CANDIDATE_SENDER_RE = re.compile(r"群聊 \[[^\]]*\] \[([^\]\(]+)\((\d{5,20})\)\]")
CANDIDATE_PRIVATE_RE = re.compile(r"私聊 \((\d{5,20})\)")
CANDIDATE_LOG_RE = re.compile(r"\] ([^\s/]{1,32})/(\d{5,20}):")


ONEBOT_HTTP = "http://127.0.0.1:6198"


def _onebot_api(action: str):
    """调用 NapCat 的 OneBot HTTP 接口（本地 6198），失败返回 None。"""
    for method in ("POST", "GET"):
        try:
            body = b"{}" if method == "POST" else None
            req = urllib.request.Request(ONEBOT_HTTP + "/" + action, data=body, method=method)
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, dict) and data.get("status") in ("ok", "async") and "data" in data:
                return data.get("data")
            return None
        except Exception:
            continue
    return None


def _qq_lists() -> dict | None:
    """QQ 真实群列表 + 好友列表；未登录/接口不可用时返回 None。"""
    groups_raw = _onebot_api("get_group_list")
    friends_raw = _onebot_api("get_friend_list")
    if groups_raw is None and friends_raw is None:
        return None
    self_id = ""
    try:
        for f in (NAPCAT_DIR / "config").glob("onebot11_*.json"):
            m = re.match(r"onebot11_(\d{5,20})$", f.stem)
            if m:
                self_id = m.group(1)
                break
    except Exception:
        pass
    groups = []
    for g in groups_raw or []:
        gid = str(g.get("group_id") or g.get("group_id_str") or "")
        name = str(g.get("group_name") or "").strip()
        if gid:
            groups.append({"id": gid, "name": name})
    people = []
    for f in friends_raw or []:
        uid = str(f.get("user_id") or f.get("user_id_str") or "")
        name = str(f.get("remark") or f.get("nickname") or "").strip()
        if uid and uid != self_id:
            people.append({"id": uid, "name": name})
    return {"groups": groups, "people": people}


def _scan_candidates() -> dict:
    qq = _qq_lists()
    if qq is not None:
        return {
            "ok": True,
            "source": "qq",
            "groups": qq["groups"],
            "people": qq["people"],
            "private_ids": qq["people"],
        }

    groups: dict[str, str] = {}
    people: dict[str, str] = {}

    # 1) 群名缓存
    groups.update(_group_names() or {})

    # 2) NapCat 日志：群名 + 群友昵称 + 私聊 QQ
    private_ids: set[str] = set()
    logs = sorted(NAPCAT_DIR.glob("napcat-live*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    for log in logs[:20]:
        try:
            with log.open("rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - 1_500_000))
                text = fh.read().decode("utf-8", "replace")
        except Exception:
            continue
        for name, gid in CANDIDATE_GROUP_RE.findall(text):
            if name.strip():
                groups[str(gid)] = name.strip()
        for name, uid in CANDIDATE_SENDER_RE.findall(text):
            if name.strip():
                people[str(uid)] = name.strip()
        for uid in CANDIDATE_PRIVATE_RE.findall(text):
            private_ids.add(str(uid))

    # 3) AstrBot 运行日志：昵称/QQ
    try:
        text = (ROOT / "run-stdout.log").read_text("utf-8", "replace")
        for name, uid in CANDIDATE_LOG_RE.findall(text[-3_000_000:]):
            name = name.strip()
            if name and name not in {"Prepare", "to", "send"}:
                people.setdefault(str(uid), name)
    except Exception:
        pass

    # 4) 记忆档案
    if MEMORY_DIR.exists():
        for f in MEMORY_DIR.glob("*.json"):
            data = read_json(f, {}) or {}
            gid = str(data.get("group") or f.stem)
            for uid, member in (data.get("members") or {}).items():
                name = str(member.get("name") or "").strip()
                if name:
                    people.setdefault(str(uid), name)

    return {
        "ok": True,
        "source": "logs",
        "groups": [{"id": gid, "name": name} for gid, name in groups.items()],
        "people": [{"id": uid, "name": name} for uid, name in people.items()],
        "private_ids": [{"id": uid, "name": people.get(uid, "")} for uid in sorted(private_ids)],
    }


# ---------------------------------------------------------------- 响应策略
POLICY_FILE = PLUGIN_DIR / "astrbot_plugin_whale_behavior" / "policy.json"
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
LEVEL_INFO = [
    {"level": 1, "name": "极省 L1", "desc": "只接受 @ 和关键词触发，绝不主动接话；回复限 15 字内。适合 token 最贵的高峰时段。"},
    {"level": 2, "name": "省流 L2", "desc": "主动插嘴概率减半，回复限 30 字内、最多两条短句。适合高峰时段。"},
    {"level": 3, "name": "标准 L3", "desc": "按行为插件配置的正常档位走，不做额外限制。"},
    {"level": 4, "name": "活跃 L4", "desc": "插嘴概率 ×1.3（上限 100），允许自然多说一两句。适合低谷时段。"},
]


def _read_policy() -> dict:
    data = dict(POLICY_DEFAULT)
    data.update(read_json(POLICY_FILE, {}) or {})
    return data


def _policy_in_peak(policy: dict) -> bool:
    def minutes(text):
        try:
            h, m = str(text).strip().split(":")
            h, m = int(h), int(m)
        except Exception:
            return None
        if not (0 <= h <= 24 and 0 <= m < 60):
            return None
        return h * 60 + m

    now = datetime.now()
    # 官方规则：周末全天为空闲时段
    if bool(policy.get("peak_weekdays_only", True)) and now.weekday() >= 5:
        return False
    cur = now.hour * 60 + now.minute
    for rng in policy.get("peak_ranges") or []:
        parts = str(rng).split("-")
        if len(parts) != 2:
            continue
        start, end = minutes(parts[0]), minutes(parts[1])
        if start is None or end is None:
            continue
        if end == 24 * 60:
            if cur >= start:
                return True
        elif start <= end:
            if start <= cur < end:
                return True
        else:
            if cur >= start or cur < end:
                return True
    return False


def api_policy() -> dict:
    policy = _read_policy()
    names = _group_names()
    groups = [
        {"id": str(gid), "name": names.get(str(gid), "")}
        for gid in (policy.get("allowed_groups") or [])
    ]
    pv_enabled = bool(policy.get("peak_valley_enabled", True))
    in_peak = _policy_in_peak(policy) if pv_enabled else False
    if pv_enabled:
        level = policy.get("peak_level") if in_peak else policy.get("offpeak_level")
    else:
        level = policy.get("fixed_level", 3)
    try:
        level = max(1, min(4, int(level)))
    except Exception:
        level = 3
    now = datetime.now().strftime("%H:%M")
    return {
        "ok": True,
        "policy": policy,
        "groups": groups,
        "levels": LEVEL_INFO,
        "status": {
            "in_peak": in_peak,
            "level": level,
            "now": now,
            "peak_valley_enabled": pv_enabled,
        },
    }


def api_policy_save(payload: dict) -> dict:
    data = dict(POLICY_DEFAULT)
    data.update(_read_policy())
    if "whitelist_enabled" in payload:
        data["whitelist_enabled"] = bool(payload["whitelist_enabled"])
    if "allowed_groups" in payload:
        data["allowed_groups"] = [str(x).strip() for x in (payload["allowed_groups"] or []) if str(x).strip()]
    if "allowed_private_users" in payload:
        data["allowed_private_users"] = [
            str(x).strip() for x in (payload["allowed_private_users"] or []) if str(x).strip()
        ]
    if "peak_ranges" in payload:
        ranges = []
        for item in payload["peak_ranges"] or []:
            text = str(item).strip()
            if text and text.count("-") == 1:
                ranges.append(text)
        data["peak_ranges"] = ranges
    if "peak_weekdays_only" in payload:
        data["peak_weekdays_only"] = bool(payload["peak_weekdays_only"])
    if "peak_valley_enabled" in payload:
        data["peak_valley_enabled"] = bool(payload["peak_valley_enabled"])
    for key in ("peak_level", "offpeak_level", "fixed_level"):
        if key in payload:
            try:
                data[key] = max(1, min(4, int(payload[key])))
            except Exception:
                pass
    POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
    POLICY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    return {"ok": True, "policy": data}




# ---------------------------------------------------------------- 聊天记忆（AstrBot 会话）
def _ab_conv_url(cid: str, uid: str, tail: str = "") -> str:
    from urllib.parse import quote

    return f"/api/v1/conversations/{quote(str(cid), safe='')}{tail}?user_id={quote(str(uid), safe='')}"


def api_chat_memory_list() -> dict:
    try:
        data = _astrbot_api("/api/v1/conversations?page=1&page_size=100&include_history=false")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"读取会话失败: {exc}"}
    return {"ok": True, **(data or {})}


def api_chat_memory_detail(payload: dict) -> dict:
    uid = str(payload.get("user_id") or "")
    cid = str(payload.get("cid") or "")
    if not uid or not cid:
        return {"ok": False, "error": "缺少 user_id 或 cid"}
    try:
        data = _astrbot_api(_ab_conv_url(cid, uid))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"读取会话详情失败: {exc}"}
    return {"ok": True, **(data or {})}


def api_chat_memory_save(payload: dict) -> dict:
    uid = str(payload.get("user_id") or "")
    cid = str(payload.get("cid") or "")
    history = payload.get("history")
    if not uid or not cid or not isinstance(history, list):
        return {"ok": False, "error": "参数不完整"}
    try:
        _astrbot_api(_ab_conv_url(cid, uid, "/messages"), method="PUT", payload={"messages": history})
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"保存失败: {exc}"}
    return {"ok": True}


def api_chat_memory_delete(payload: dict) -> dict:
    uid = str(payload.get("user_id") or "")
    cid = str(payload.get("cid") or "")
    if not uid or not cid:
        return {"ok": False, "error": "缺少 user_id 或 cid"}
    try:
        _astrbot_api(_ab_conv_url(cid, uid), method="DELETE")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"删除失败: {exc}"}
    return {"ok": True}


def _proactive_history_file():
    return PLUGIN_DIR / "astrbot_plugin_whale_behavior" / "chat_history.json"


def api_memory_extra() -> dict:
    hist = read_json(_proactive_history_file(), {}) or {}
    proactive = {
        str(k): len(v or []) for k, v in hist.items() if isinstance(v, list)
    }
    member_dir = PLUGIN_DIR / "astrbot_plugin_member_memory" / "members"
    member_groups = 0
    member_count = 0
    if member_dir.exists():
        for g in member_dir.iterdir():
            if g.is_dir():
                member_groups += 1
                member_count += len(list(g.glob("*.json")))
    return {
        "ok": True,
        "proactive": proactive,
        "member_groups": member_groups,
        "member_count": member_count,
    }


def api_memory_proactive_clear(payload: dict) -> dict:
    target = str(payload.get("target") or "").strip()
    path = _proactive_history_file()
    hist = read_json(path, {}) or {}
    if target:
        hist.pop(target, None)
    else:
        hist = {}
    write_json(path, hist)
    return {"ok": True}


# ---------------------------------------------------------------- 主动聊天测试
PROACTIVE_HISTORY = PLUGIN_DIR / "astrbot_plugin_whale_behavior" / "chat_history.json"


def _onebot_send(target: str, text: str) -> bool:
    target = str(target or "").strip()
    if ":" in target:
        kind, ident = target.split(":", 1)
    else:
        kind, ident = "private", target
    try:
        if kind == "group":
            req = urllib.request.Request(
                ONEBOT_HTTP + "/send_group_msg",
                data=json.dumps({"group_id": int(ident), "message": text}).encode("utf-8"),
                method="POST",
            )
        else:
            req = urllib.request.Request(
                ONEBOT_HTTP + "/send_private_msg",
                data=json.dumps({"user_id": int(ident), "message": text}).encode("utf-8"),
                method="POST",
            )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("status") in ("ok", "async") or bool(data.get("retcode") == 0)
    except Exception as exc:  # noqa: BLE001
        return False


def api_proactive_test(payload: dict) -> dict:
    target = str(payload.get("target") or "").strip()
    if not target:
        return {"ok": False, "error": "没有配置主动聊天对象"}
    cfg = read_json(CONFIG_DIR / "astrbot_plugin_whale_behavior_config.json", {}) or {}
    mode = str(payload.get("mode") or cfg.get("proactive_topic_mode") or "mix")
    if mode == "mix":
        mode = "history" if __import__("random").random() < 0.5 else "share"
    history = read_json(PROACTIVE_HISTORY, {}) or {}
    bucket = history.get(target) or []
    recent = bucket[-12:]
    lines = "\n".join(f"{h.get('name') or '对方'}: {h.get('text')}" for h in recent) or "（没有历史记录）"
    instruction = (
        "基于下面聊天记录涉及的领域/话题，分享一个相关的小知识、见闻、推荐或看法，像你突然想起什么来主动找人聊。不要重复原话。"
        if mode == "share"
        else "根据下面最近的聊天，自然地开启一个新话题或接着刚才的话题聊一句，像主动找人搭话。"
    )
    system_prompt = (
        "你是小鲸鱼，一个活泼、有点话痨的群友/朋友。现在你主动找人聊天。"
        "只输出一条要发的话，口语化、自然，不超过 40 字，不要解释、不要加引号。"
    )
    prompt = f"【最近的聊天】\n{lines}\n\n{instruction}"
    base, key, model = _model_credentials()
    if not key:
        return {"ok": False, "error": "没有配置模型 Key"}
    try:
        req = urllib.request.Request(
            base + "/chat/completions",
            data=json.dumps(
                {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 120,
                }
            ).encode("utf-8"),
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer " + key)
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        text = (body["choices"][0]["message"]["content"] or "").strip().strip('"')
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"生成失败: {exc}"}
    if not text:
        return {"ok": False, "error": "生成的文本为空"}
    ok = _onebot_send(target, text)
    return {"ok": ok, "target": target, "text": text, "mode": mode}


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    # ---------- response helpers
    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code=200):
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _bytes(self, data: bytes, ctype: str):
        self._send(200, data, ctype)

    def _file(self, path: Path):
        if not path.exists() or not path.is_file():
            self._json({"ok": False, "error": "not found"}, 404)
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }.get(path.suffix.lower(), "application/octet-stream")
        self._send(200, path.read_bytes(), ctype)

    # ---------- routing
    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        qs = parse_qs(url.query)
        try:
            if path in ("/", "/index.html"):
                return self._file(WEB_DIR / "index.html")
            if path in ("/favicon.ico", "/logo.png"):
                return self._file(WEB_DIR / path.lstrip("/"))
            if path == "/style.css":
                return self._file(WEB_DIR / "style.css")
            if path == "/app.js":
                return self._file(WEB_DIR / "app.js")
            if path in ("/ops.js", "/ops.css", "/guide.js", "/starmap.js", "/starmap.css"):
                return self._file(WEB_DIR / path.lstrip("/"))
            if path == "/api/status":
                return self._json(api_status())
            if path == "/api/health":
                return self._json(api_health())
            if path == "/api/ready":
                return self._json(api_ready())
            if path == "/api/personas":
                return self._json(api_personas())
            if path == "/api/persona/core":
                return self._json(api_persona_core_info(str(qs.get("name", [""])[0])))
            if path == "/api/persona":
                return self._json(api_persona(qs.get("name", [""])[0]))
            if path == "/api/behavior":
                return self._json(api_behavior())
            if path == "/api/stickers/auto-tag-batch/status":
                return self._json({"ok": True, **STICKER_BATCH})
            if path == "/api/stickers":
                return self._json(api_stickers())
            if path == "/api/sticker-image":
                name = qs.get("file", [""])[0]
                if "/" in name or "\\" in name or ".." in name:
                    return self._json({"ok": False, "error": "bad file"}, 400)
                return self._file(STICKER_DIR / name)
            if path == "/api/qr/refresh":
                return self._json(api_qr_refresh())
            if path == "/api/qzone/status":
                return self._json(api_qzone_status())
            if path == "/api/qzone/feeds":
                return self._json(api_qzone_feeds(int(qs.get("limit", ["5"])[0])))
            if path == "/api/breeze/voices":
                return self._json(api_breeze_voices())
            if path == "/api/breeze/preview":
                vid = qs.get("voice_id", [""])[0]
                text = qs.get("text", [""])[0]
                try:
                    data = api_breeze_preview(vid, text)
                except Exception as exc:
                    return self._json({"ok": False, "error": str(exc)}, 500)
                if not data:
                    return self._json({"ok": False, "error": "无法生成试听"}, 400)
                return self._bytes(data, "audio/wav")
            if path == "/api/starmap/alias/history":
                return self._json(sm.alias_history())
            if path == "/api/starmap/sagas":
                return self._json(sm.sagas())
            if path == "/api/starmap/entities":
                return self._json(sm.entities())
            if path == "/api/starmap/settings":
                return self._json(sm.settings_info())
            if path == "/api/starmap/graph":
                return self._json(sm.graph())
            if path == "/api/starmap/pending":
                return self._json(sm.pending_claims(int(qs.get("limit", ["50"])[0])))
            if path == "/api/ops/today":
                return self._json(ops.today_info())
            if path == "/api/ops/memory":
                return self._json(ops.memory_info())
            if path == "/api/ops/health":
                return self._json(ops.health_info())
            if path == "/api/ops/backups":
                return self._json(ops.list_backups())
            if path == "/api/ops/budget":
                return self._json(ops.budget_info())
            if path == "/api/ops/taste":
                return self._json(ops.taste_info(int(qs.get("limit", ["20"])[0])))
            if path == "/api/ops/settings":
                return self._json({"ok": True, **ops.settings()})
            if path == "/api/diary":
                return self._json(api_diary_list(int(qs.get("limit", ["40"])[0])))
            if path == "/api/proactive/status":
                return self._json(api_proactive_status())
            if path == "/api/proactive/action":
                return self._json(
                    api_proactive_action(str(body.get("action", "")), str(body.get("target", "")))
                )
            if path == "/api/proactive/override":
                return self._json(api_proactive_override(body))
            if path == "/api/market":
                return self._json(api_market_list(bool(qs.get("force", ["0"])[0] in ("1", "true"))))
            if path == "/api/turns/detail":
                return self._json(api_turns_detail(int(qs.get("idx", ["0"])[0])))
            if path == "/api/life":
                return self._json({"ok": True, **life_info()})
            if path == "/api/turns":
                return self._json(api_turns_list(int(qs.get("limit", ["40"])[0])))
            if path == "/api/usage":
                return self._json(api_usage_stats(int(qs.get("days", ["30"])[0])))
            if path == "/api/memory/chat":
                return self._json(api_chat_memory_list())
            if path == "/api/memory/chat/detail":
                return self._json(api_chat_memory_detail(body))
            if path == "/api/memory/chat/save":
                return self._json(api_chat_memory_save(body))
            if path == "/api/memory/chat/delete":
                return self._json(api_chat_memory_delete(body))
            if path == "/api/memory/extra":
                return self._json(api_memory_extra())
            if path == "/api/memory/proactive/clear":
                return self._json(api_memory_proactive_clear(body))
            if path == "/api/memory":
                return self._json(api_memory())
            if path == "/api/logs":
                target = qs.get("target", ["astrbot"])[0]
                lines = int(qs.get("lines", ["120"])[0])
                return self._json({"lines": api_logs(target, lines)})
            if path == "/api/qr":
                return self._file(NAPCAT_DIR / "cache" / "qrcode.png")
            if path == "/api/version":
                return self._json(api_version())
            if path == "/api/plugins":
                return self._json(api_plugins_list())
            if path == "/api/plugins/config":
                return self._json(api_plugin_config(qs.get("plugin_id", [""])[0]))
            if path == "/api/policy/candidates":
                return self._json(_scan_candidates())
            if path == "/api/models":
                return self._json(api_models())
            if path == "/api/policy":
                return self._json(api_policy())
            if path == "/api/settings":
                return self._json(_settings())
            if path == "/api/model":
                return self._json(model_info())
            self._json({"ok": False, "error": "not found"}, 404)
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001
            self._json({"ok": False, "error": str(exc)}, 500)

    def do_POST(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            body = {}
        try:
            path = url.path
            if path == "/api/persona/core/approve":
                return self._json(api_persona_core_approve(str(body.get("name", "")), str(body.get("id", ""))))
            if path == "/api/persona/core/reject":
                return self._json(api_persona_core_reject(str(body.get("name", "")), str(body.get("id", ""))))
            if path == "/api/persona/core/rollback":
                return self._json(api_persona_core_rollback(str(body.get("name", "")), str(body.get("file", ""))))
            if path == "/api/persona/core/save":
                return self._json(api_persona_core_save(str(body.get("name", "")), str(body.get("content", ""))))
            if path == "/api/starmap/saga/generate":
                return self._json(sm.generate_saga())
            if path == "/api/starmap/alias/undo":
                return self._json(sm.undo_alias(int(body.get("id") or 0)))
            if path == "/api/starmap/alias/merge":
                return self._json(sm.merge_alias(str(body.get("alias", "")), str(body.get("canonical", ""))))
            if path == "/api/starmap/settings":
                return self._json({"ok": True, **ops.save_settings(body)})
            if path == "/api/starmap/episode/summary":
                return self._json(sm.episode_summary(int(body.get("id") or 0)))
            if path == "/api/starmap/extract":
                return self._json(sm.extract(int(body.get("limit", 60))))
            if path == "/api/starmap/seed":
                return self._json(sm.seed_core())
            if path == "/api/starmap/unapprove":
                return self._json(sm.unapprove_claim(int(body.get("id") or 0)))
            if path == "/api/starmap/decision":
                cid = int(body.get("id") or 0)
                if body.get("approve"):
                    return self._json(sm.approve_claim(cid, bool(body.get("auto_summary", False))))
                return self._json(sm.reject_claim(cid))
            if path == "/api/ops/backup":
                return self._json(ops.create_backup(str(body.get("label", "manual"))))
            if path == "/api/ops/restore":
                return self._json(ops.restore_backup(str(body.get("name", "")), body.get("modules")))
            if path == "/api/ops/budget/save":
                budget = body.get("budget") if isinstance(body.get("budget"), dict) else body
                ops.save_settings({"budget": budget})
                return self._json(ops.budget_info())
            if path == "/api/ops/settings/save":
                return self._json({"ok": True, **ops.save_settings(body)})
            if path == "/api/ops/onboarding/complete":
                return self._json({"ok": True, **ops.save_settings({"onboarding_done": True, "guide_version": 2})})
            if path == "/api/ops/logs/rotate":
                return self._json(ops.rotate_logs())
            if path == "/api/persona/rename":
                return self._json(api_persona_rename(str(body.get("old", "")), str(body.get("new", ""))))
            if path == "/api/persona/activate":
                return self._json(api_persona_activate(str(body.get("name", ""))))
            if path == "/api/persona/delete":
                return self._json(api_persona_delete(str(body.get("name", ""))))
            if path == "/api/breeze/clone":
                return self._json(api_breeze_clone(body))
            if path == "/api/breeze/switch":
                return self._json(api_breeze_switch(str(body.get("voice_id", ""))))
            if path == "/api/breeze/delete":
                return self._json(api_breeze_delete(str(body.get("voice_id", ""))))
            if path == "/api/persona/save":
                return self._json(api_persona_save(body.get("name", ""), body.get("content", "")))
            if path == "/api/behavior/save":
                return self._json(api_behavior_save(body))
            if path == "/api/stickers/auto-tag-batch/start":
                return self._json(api_sticker_batch_start(body))
            if path == "/api/stickers/auto-tag-batch/status":
                return self._json({"ok": True, **STICKER_BATCH})
            if path == "/api/sticker/auto-tag":
                return self._json(api_sticker_auto_tag(body))
            if path == "/api/plugins/toggle":
                return self._json(
                    api_plugin_toggle(str(body.get("plugin_id", "")), bool(body.get("enabled")))
                )
            if path == "/api/plugins/config/save":
                return self._json(
                    api_plugin_config_save(str(body.get("plugin_id", "")), body.get("config") or {})
                )
            if path == "/api/plugins/uninstall":
                return self._json(
                    api_plugin_uninstall(
                        str(body.get("plugin_id", "")),
                        bool(body.get("delete_config")),
                        bool(body.get("delete_data")),
                    )
                )
            if path == "/api/plugins/reload":
                return self._json(api_plugin_reload(str(body.get("plugin_id", ""))))
            if path == "/api/models/delete":
                return self._json(api_models_delete(str(body.get("provider_id", ""))))
            if path == "/api/models/switch":
                return self._json(api_models_switch(str(body.get("provider_id", ""))))
            if path == "/api/models/add":
                return self._json(api_models_add(body))
            if path == "/api/proactive/test":
                return self._json(api_proactive_test(body))
            if path == "/api/policy/save":
                return self._json(api_policy_save(body))
            if path == "/api/settings/save":
                patch = {k: body[k] for k in ("closeAction", "autoStart", "autoCompress") if k in body}
                if "autoStart" in patch:
                    res = _set_autostart(bool(patch["autoStart"]))
                    if not res.get("ok"):
                        # 没真正生效就不要写入配置，否则下次打开 UI 会撒谎
                        return self._json({"ok": False, "error": res.get("error", "开机自启设置失败")}, 500)
                return self._json(_save_settings(patch))
            if path == "/api/sticker/add":
                return self._json(api_sticker_add(body))
            if path == "/api/sticker/delete":
                return self._json(api_sticker_delete(str(body.get("id", ""))))
            if path == "/api/sticker/update":
                return self._json(api_sticker_update(body))
            if path == "/api/memory/clear-group":
                return self._json(api_memory_clear_group(str(body.get("group", ""))))
            if path == "/api/market/update":
                return self._json(api_market_update(str(body.get("id", ""))))
            if path == "/api/proactive/action":
                return self._json(
                    api_proactive_action(str(body.get("action", "")), str(body.get("target", "")))
                )
            if path == "/api/proactive/override":
                return self._json(api_proactive_override(body))
            if path == "/api/market/install":
                return self._json(api_market_install(str(body.get("id", ""))))
            if path == "/api/qr/refresh":
                return self._json(api_qr_refresh())
            if path == "/api/memory/chat":
                return self._json(api_chat_memory_list())
            if path == "/api/memory/chat/detail":
                return self._json(api_chat_memory_detail(body))
            if path == "/api/memory/chat/save":
                return self._json(api_chat_memory_save(body))
            if path == "/api/memory/chat/delete":
                return self._json(api_chat_memory_delete(body))
            if path == "/api/memory/proactive/clear":
                return self._json(api_memory_proactive_clear(body))
            if path == "/api/memory/clear":
                return self._json(api_memory_clear(str(body.get("group", "")), str(body.get("uid", ""))))
            if path == "/api/service":
                return self._json(api_service(body.get("action", ""), body.get("target", "astrbot")))
            self._json({"ok": False, "error": "not found"}, 404)
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001
            self._json({"ok": False, "error": str(exc)}, 500)


def _starmap_auto_loop() -> None:
    while True:
        try:
            st = ops.settings()
            if st.get("starmap_auto", True):
                sm.auto_extract(int(st.get("starmap_interval_min", 30) or 30))
            if st.get("backup_auto", True):
                last = max((f.stat().st_mtime for f in ops.BACKUP_DIR.glob("backup-*.zip")), default=0)
                if time.time() - last > 24 * 3600:
                    ops.create_backup("auto")
        except Exception:
            pass
        time.sleep(60)


def main() -> None:
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _group_names()  # 预热群名缓存
    except Exception:
        pass
    try:
        ops.rotate_logs()
        st = ops.settings()
        last = max((f.stat().st_mtime for f in ops.BACKUP_DIR.glob("backup-*.zip")), default=0)
        if st.get("backup_auto", True) and time.time() - last > 24 * 3600:
            ops.create_backup("auto")
    except Exception:
        pass
    threading.Thread(target=_starmap_auto_loop, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"小鲸鱼控制台: http://127.0.0.1:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
