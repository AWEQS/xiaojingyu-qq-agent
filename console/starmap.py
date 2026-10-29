"""记忆星图：事实 → 星座 → 篇章，带证据与审核。"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB_DIR = DATA / "plugin_data" / "memory_starmap"
DB_PATH = DB_DIR / "starmap.db"
DIARY_DB = DATA / "plugin_data" / "memory_diary" / "diary.db"
CORE_DIR = DATA / "plugins" / "astrbot_plugin_persona_pack" / "personas" / ".core"
CONFIG = DATA / "cmd_config.json"

CATEGORIES = {
    "人物": "#5ee0f0",
    "关系": "#ff8ec4",
    "事件": "#ffd982",
    "兴趣": "#a78bfa",
    "承诺": "#4ce0a3",
    "偏好": "#7dd3fc",
    "事实": "#cbd5e1",
}
DEFAULT_CAT = "事实"


def _conn():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), timeout=10)
    con.row_factory = sqlite3.Row
    return con


def ensure_db():
    con = _conn()
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS claims (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          subject TEXT NOT NULL,
          subject_kind TEXT DEFAULT '',
          predicate TEXT NOT NULL,
          object TEXT NOT NULL,
          object_kind TEXT DEFAULT '',
          category TEXT DEFAULT '事实',
          confidence REAL DEFAULT 0.6,
          quote TEXT DEFAULT '',
          date TEXT DEFAULT '',
          message_ids TEXT DEFAULT '',
          status TEXT DEFAULT 'pending',
          constellation_id INTEGER DEFAULT 0,
          episode_id INTEGER DEFAULT 0,
          created REAL,
          updated REAL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_claim_unique
          ON claims(subject, predicate, object);
        CREATE INDEX IF NOT EXISTS idx_claim_status ON claims(status);
        CREATE TABLE IF NOT EXISTS constellations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT UNIQUE,
          kind TEXT,
          color TEXT,
          description TEXT,
          created REAL
        );
        CREATE TABLE IF NOT EXISTS episodes (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT,
          summary TEXT,
          date TEXT,
          created REAL
        );
        CREATE TABLE IF NOT EXISTS extractions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          started REAL,
          finished REAL,
          messages INTEGER DEFAULT 0,
          added INTEGER DEFAULT 0,
          status TEXT,
          error TEXT
        );
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS sagas (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT,
          summary TEXT,
          start_date TEXT,
          end_date TEXT,
          created REAL,
          updated REAL
        );
        CREATE TABLE IF NOT EXISTS saga_episodes (
          saga_id INTEGER,
          episode_id INTEGER,
          UNIQUE(saga_id, episode_id)
        );
        CREATE TABLE IF NOT EXISTS aliases (
          alias TEXT PRIMARY KEY,
          canonical TEXT NOT NULL,
          created REAL
        );
        CREATE TABLE IF NOT EXISTS alias_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          alias TEXT,
          canonical TEXT,
          rows TEXT,
          changed INTEGER DEFAULT 0,
          created REAL,
          undone INTEGER DEFAULT 0
        );
        """
    )
    con.commit()
    con.close()


def _meta(con, key, default=""):
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def _set_meta(con, key, value):
    con.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def _clean_category(cat: str) -> str:
    cat = str(cat or "").strip()
    return cat if cat in CATEGORIES else DEFAULT_CAT


def _get_constellation(con, category: str) -> int:
    row = con.execute("SELECT id FROM constellations WHERE name=?", (category,)).fetchone()
    if row:
        return int(row["id"])
    cur = con.execute(
        "INSERT INTO constellations(name,kind,color,description,created) VALUES(?,?,?,?,?)",
        (category, category, CATEGORIES.get(category, "#cbd5e1"), f"{category}相关的事实与记忆", time.time()),
    )
    return int(cur.lastrowid)


def _get_episode(con, date_text: str) -> int:
    day = (date_text or datetime.now().strftime("%Y-%m-%d"))[:10]
    row = con.execute("SELECT id FROM episodes WHERE date=?", (day,)).fetchone()
    if row:
        return int(row["id"])
    cur = con.execute(
        "INSERT INTO episodes(title,summary,date,created) VALUES(?,?,?,?)",
        (f"{day} 的记忆", "", day, time.time()),
    )
    return int(cur.lastrowid)


def _insert_claim(con, c: dict, status: str = "pending") -> int | None:
    subject = str(c.get("subject") or "").strip()[:80]
    predicate = str(c.get("predicate") or "").strip()[:80]
    obj = str(c.get("object") or "").strip()[:200]
    if not subject or not predicate or not obj:
        return None
    category = _clean_category(c.get("category"))
    quote = str(c.get("quote") or "").strip()[:400]
    date_text = str(c.get("date") or datetime.now().strftime("%Y-%m-%d"))[:19]
    try:
        confidence = max(0.0, min(1.0, float(c.get("confidence") or 0.6)))
    except Exception:
        confidence = 0.6
    ids = c.get("message_ids") or []
    if not isinstance(ids, list):
        ids = []
    ids_text = ",".join(str(x) for x in ids[:20])
    exists = con.execute(
        "SELECT id FROM claims WHERE subject=? AND predicate=? AND object=?", (subject, predicate, obj)
    ).fetchone()
    if exists:
        return int(exists["id"])
    cur = con.execute(
        """INSERT INTO claims(subject,subject_kind,predicate,object,object_kind,category,confidence,quote,date,message_ids,status,created,updated)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            subject,
            str(c.get("subject_kind") or "")[:30],
            predicate,
            obj,
            str(c.get("object_kind") or "")[:30],
            category,
            confidence,
            quote,
            date_text,
            ids_text,
            status,
            time.time(),
            time.time(),
        ),
    )
    return int(cur.lastrowid)




def _auto_summary_enabled() -> bool:
    try:
        p = DATA / "console_features.json"
        if not p.exists():
            return True
        data = json.loads(p.read_text("utf-8-sig"))
        return bool(data.get("starmap_auto_summary", True))
    except Exception:
        return True




def sagas() -> dict:
    ensure_db()
    con = _conn()
    rows = []
    for r in con.execute("SELECT * FROM sagas ORDER BY id DESC"):
        item = dict(r)
        item["episode_ids"] = [
            int(x["episode_id"])
            for x in con.execute("SELECT episode_id FROM saga_episodes WHERE saga_id=? ORDER BY episode_id", (r["id"],))
        ]
        rows.append(item)
    con.close()
    return {"ok": True, "sagas": rows}


def generate_saga() -> dict:
    ensure_db()
    con = _conn()
    eps = [dict(r) for r in con.execute("SELECT * FROM episodes ORDER BY date ASC")]
    if not eps:
        con.close()
        return {"ok": False, "error": "还没有篇章，先生成一篇 Episode"}
    for e in eps:
        if not e.get("summary"):
            claims = [dict(x) for x in con.execute(
                "SELECT subject,predicate,object FROM claims WHERE episode_id=? AND status='approved' ORDER BY id",
                (e["id"],),
            )]
            e["summary"] = "；".join(f"{c['subject']}{c['predicate']}{c['object']}" for c in claims[:12]) or e.get("title", "")
    api_key, base, model = _provider()
    con.execute("DELETE FROM saga_episodes")
    con.execute("DELETE FROM sagas")
    groups = []
    current = []
    last_date = None
    for e in eps:
        d = str(e.get("date") or "")
        if current and last_date and d and (datetime.strptime(d[:10], "%Y-%m-%d") - datetime.strptime(last_date[:10], "%Y-%m-%d")).days > 14:
            groups.append(current)
            current = []
        current.append(e)
        if d:
            last_date = d
    if current:
        groups.append(current)
    created = 0
    for group in groups:
        text = "\n\n".join(
            f"【{e.get('date','')}】{e.get('title','')}\n{e.get('summary','')}" for e in group
        )[:6000]
        title = f"{group[0].get('date','')} - {group[-1].get('date','')}"
        summary = ""
        if api_key and len(group) >= 1:
            try:
                prompt = "把下面这些已确认的篇章整理成一条长期关系弧线。只使用给出的内容，不编造。输出 JSON：{\"title\":\"短标题\",\"summary\":\"4-6句叙事\"}\n\n" + text
                raw = _chat(api_key, base, model, "你负责把零散篇章整理成长期故事弧线，只基于给定内容。", prompt)
                data = _extract_json(raw)
                title = str(data.get("title") or title)[:80]
                summary = str(data.get("summary") or "")[:1200]
            except Exception:
                pass
        if not summary:
            summary = "；".join(str(e.get("summary") or e.get("title") or "") for e in group)[:1200]
        cur = con.execute(
            "INSERT INTO sagas(title,summary,start_date,end_date,created,updated) VALUES(?,?,?,?,?,?)",
            (title, summary, group[0].get("date", ""), group[-1].get("date", ""), time.time(), time.time()),
        )
        sid = int(cur.lastrowid)
        for e in group:
            con.execute("INSERT OR IGNORE INTO saga_episodes(saga_id,episode_id) VALUES(?,?)", (sid, int(e["id"])))
        created += 1
    con.commit()
    con.close()
    return {"ok": True, "sagas": created, **sagas()}

def episode_summary(ep_id: int) -> dict:
    ensure_db()
    con = _conn()
    ep = con.execute("SELECT * FROM episodes WHERE id=?", (ep_id,)).fetchone()
    if not ep:
        con.close()
        return {"ok": False, "error": "篇章不存在"}
    claims = [dict(r) for r in con.execute(
        "SELECT subject,predicate,object,quote,date FROM claims WHERE episode_id=? AND status='approved' ORDER BY id",
        (ep_id,),
    )]
    con.close()
    if not claims:
        return {"ok": False, "error": "篇章里还没有已确认的记忆"}
    api_key, base, model = _provider()
    if not api_key:
        return {"ok": False, "error": "没有可用模型 Key"}
    lines = []
    for c in claims[:40]:
        line = f"- {c['subject']} {c['predicate']} {c['object']}"
        if c.get("quote"):
            line += f"（原话：{c['quote'][:80]}）"
        lines.append(line)
    system = "你把已确认的记忆写成一段温柔的回忆片段。只使用给出的记忆，不要编造新事实；用中文，2-4 句，像在回想那天。不要列表、不要标题。"
    user = f"日期：{ep['date']}\n记忆：\n" + "\n".join(lines)
    try:
        summary = _chat(api_key, base, model, system, user).strip()[:800]
        con = _conn()
        con.execute("UPDATE episodes SET summary=? WHERE id=?", (summary, ep_id))
        con.commit()
        con.close()
        return {"ok": True, "id": ep_id, "summary": summary}
    except Exception as exc:
        return {"ok": False, "error": f"生成摘要失败: {exc}"}


def settings_info() -> dict:
    ensure_db()
    con = _conn()
    last = con.execute("SELECT finished,status,error FROM extractions ORDER BY id DESC LIMIT 1").fetchone()
    last_auto = _meta(con, "last_auto_ts", "")
    con.close()
    try:
        cfg = json.loads((DATA / "console_features.json").read_text("utf-8-sig"))
    except Exception:
        cfg = {}
    return {
        "ok": True,
        "auto": bool(cfg.get("starmap_auto", True)),
        "interval_min": int(cfg.get("starmap_interval_min", 30) or 30),
        "last_auto": last_auto,
        "last_extraction": dict(last) if last else None,
    }


def auto_extract(interval_min: int = 30) -> dict:
    ensure_db()
    con = _conn()
    last = float(_meta(con, "last_auto_ts", "0") or 0)
    con.close()
    if time.time() - last < max(5, int(interval_min)) * 60:
        return {"ok": True, "skipped": True}
    res = extract(60)
    con = _conn()
    _set_meta(con, "last_auto_ts", str(time.time()))
    con.commit()
    con.close()
    return res



def _resolve_alias(con, name: str) -> str:
    name = str(name or "").strip()
    for _ in range(6):
        row = con.execute("SELECT canonical FROM aliases WHERE alias=?", (name,)).fetchone()
        if not row:
            break
        name = str(row["canonical"])
    return name


def _dedupe_claim(con, keep_id: int) -> None:
    row = con.execute("SELECT * FROM claims WHERE id=?", (keep_id,)).fetchone()
    if not row:
        return
    others = con.execute(
        "SELECT * FROM claims WHERE subject=? AND predicate=? AND object=? AND id<>?",
        (row["subject"], row["predicate"], row["object"], keep_id),
    ).fetchall()
    for o in others:
        # 优先保留已审核的；否则保留置信度高的
        better = (o["status"] == "approved" and row["status"] != "approved") or (
            o["status"] == row["status"] and float(o["confidence"] or 0) > float(row["confidence"] or 0)
        )
        if better:
            con.execute("UPDATE claims SET status=?, confidence=?, quote=?, updated=? WHERE id=?",
                        (o["status"], o["confidence"], o["quote"] or row["quote"], time.time(), keep_id))
            row = con.execute("SELECT * FROM claims WHERE id=?", (keep_id,)).fetchone()
        con.execute("DELETE FROM claims WHERE id=?", (o["id"],))


def merge_alias(alias: str, canonical: str) -> dict:
    ensure_db()
    alias = str(alias or "").strip()
    canonical = str(canonical or "").strip()
    if not alias or not canonical:
        return {"ok": False, "error": "别名和正式名都不能为空"}
    con = _conn()
    canonical = _resolve_alias(con, canonical)
    if alias == canonical:
        con.close()
        return {"ok": False, "error": "别名和正式名相同"}
    rows = con.execute("SELECT * FROM claims WHERE subject=? OR object=?", (alias, alias)).fetchall()
    snapshot = {}
    changed = 0
    for r in rows:
        ns = canonical if r["subject"] == alias else r["subject"]
        no = canonical if r["object"] == alias else r["object"]
        dup = con.execute(
            "SELECT * FROM claims WHERE subject=? AND predicate=? AND object=? AND id<>?",
            (ns, r["predicate"], no, r["id"]),
        ).fetchone()
        if dup:
            snapshot.setdefault(int(dup["id"]), dict(dup))
            # 把别名记忆的引文并进保留项
            quote = str(dup["quote"] or "")
            extra = str(r["quote"] or "")
            if extra and extra not in quote:
                quote = (quote + " / " + extra).strip(" /")
            con.execute(
                "UPDATE claims SET quote=?, confidence=MAX(confidence,?), updated=? WHERE id=?",
                (quote[:800], float(r["confidence"] or 0), time.time(), dup["id"]),
            )
            con.execute("DELETE FROM claims WHERE id=?", (r["id"],))
        else:
            snapshot.setdefault(int(r["id"]), dict(r))
            con.execute("UPDATE claims SET subject=?, object=?, updated=? WHERE id=?", (ns, no, time.time(), r["id"]))
        changed += 1
    con.execute("UPDATE aliases SET canonical=? WHERE canonical=?", (canonical, alias))
    con.execute(
        "INSERT INTO aliases(alias,canonical,created) VALUES(?,?,?) ON CONFLICT(alias) DO UPDATE SET canonical=excluded.canonical",
        (alias, canonical, time.time()),
    )
    con.execute(
        "INSERT INTO alias_history(alias,canonical,rows,changed,created,undone) VALUES(?,?,?,?,?,0)",
        (alias, canonical, json.dumps(list(snapshot.values()), ensure_ascii=False), changed, time.time()),
    )
    hist_id = int(con.execute("SELECT last_insert_rowid()").fetchone()[0])
    con.commit()
    con.close()
    return {"ok": True, "alias": alias, "canonical": canonical, "changed": changed, "history_id": hist_id}


def alias_history(limit: int = 30) -> dict:
    ensure_db()
    con = _conn()
    rows = [dict(r) for r in con.execute("SELECT * FROM alias_history WHERE undone=0 ORDER BY id DESC LIMIT ?", (limit,))]
    con.close()
    for r in rows:
        r.pop("rows", None)
    return {"ok": True, "history": rows}


def undo_alias(history_id: int) -> dict:
    ensure_db()
    con = _conn()
    row = con.execute("SELECT * FROM alias_history WHERE id=?", (history_id,)).fetchone()
    if not row or row["undone"]:
        con.close()
        return {"ok": False, "error": "这条合并记录不存在或已撤销"}
    try:
        rows = json.loads(row["rows"] or "[]")
    except Exception:
        rows = []
    cols = [
        "id", "subject", "subject_kind", "predicate", "object", "object_kind",
        "category", "confidence", "quote", "date", "message_ids", "status",
        "constellation_id", "episode_id", "created", "updated",
    ]
    ids = [int(r["id"]) for r in rows if r.get("id") is not None]
    if ids:
        con.execute("DELETE FROM claims WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)
    for r in rows:
        vals = [r.get(c) for c in cols]
        con.execute(
            "INSERT OR REPLACE INTO claims(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols))),
            vals,
        )
    con.execute("DELETE FROM aliases WHERE alias=? AND canonical=?", (row["alias"], row["canonical"]))
    con.execute("UPDATE alias_history SET undone=1 WHERE id=?", (history_id,))
    con.commit()
    con.close()
    return {"ok": True, "id": history_id}


def entities(limit: int = 80) -> dict:
    ensure_db()
    con = _conn()
    rows = con.execute(
        "SELECT subject AS name, COUNT(*) AS n FROM claims WHERE status='approved' GROUP BY subject ORDER BY n DESC LIMIT ?",
        (limit,),
    ).fetchall()
    subjects = [dict(r) for r in rows]
    aliases = [dict(r) for r in con.execute("SELECT * FROM aliases ORDER BY created DESC LIMIT 200")]
    # 简单候选：大小写/空格差异，或一方包含另一方且长度差很小
    names = [s["name"] for s in subjects]
    suggestions = []
    seen = set()
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            na, nb = a.lower().strip(), b.lower().strip()
            if na == nb or (len(a) >= 2 and len(b) >= 2 and (a in b or b in a) and abs(len(a) - len(b)) <= 2):
                pair = tuple(sorted((a, b)))
                if pair in seen:
                    continue
                seen.add(pair)
                suggestions.append({"a": pair[0], "b": pair[1], "reason": "名称相近"})
    history = [
        dict(r)
        for r in con.execute(
            "SELECT id,alias,canonical,changed,created FROM alias_history WHERE undone=0 ORDER BY id DESC LIMIT 20"
        )
    ]
    con.close()
    return {"ok": True, "subjects": subjects, "aliases": aliases, "suggestions": suggestions[:20], "history": history}

def approve_claim(cid: int, auto_summary: bool = False) -> dict:
    ensure_db()
    con = _conn()
    row = con.execute("SELECT * FROM claims WHERE id=?", (cid,)).fetchone()
    if not row:
        con.close()
        return {"ok": False, "error": "这条记忆不存在"}
    cat = row["category"] if row["category"] in CATEGORIES else DEFAULT_CAT
    cid_const = _get_constellation(con, cat)
    ep_id = _get_episode(con, row["date"])
    con.execute(
        "UPDATE claims SET status='approved', constellation_id=?, episode_id=?, updated=? WHERE id=?",
        (cid_const, ep_id, time.time(), cid),
    )
    con.commit()
    con.close()
    try:
        if auto_summary and _auto_summary_enabled():
            episode_summary(int(ep_id))
    except Exception:
        pass
    return {"ok": True, "id": cid}




def unapprove_claim(cid: int) -> dict:
    ensure_db()
    con = _conn()
    row = con.execute("SELECT id FROM claims WHERE id=?", (cid,)).fetchone()
    if not row:
        con.close()
        return {"ok": False, "error": "这条记忆不存在"}
    con.execute(
        "UPDATE claims SET status='pending', constellation_id=0, episode_id=0, updated=? WHERE id=?",
        (time.time(), cid),
    )
    con.commit()
    con.close()
    return {"ok": True, "id": cid}
def reject_claim(cid: int) -> dict:
    ensure_db()
    con = _conn()
    con.execute("UPDATE claims SET status='rejected', updated=? WHERE id=?", (time.time(), cid))
    con.commit()
    con.close()
    return {"ok": True, "id": cid}


def pending_claims(limit: int = 50) -> dict:
    ensure_db()
    con = _conn()
    rows = con.execute(
        "SELECT * FROM claims WHERE status='pending' ORDER BY confidence DESC, id DESC LIMIT ?", (limit,)
    ).fetchall()
    con.close()
    return {"ok": True, "claims": [dict(r) for r in rows]}


def graph() -> dict:
    ensure_db()
    con = _conn()
    claims = [dict(r) for r in con.execute("SELECT * FROM claims WHERE status='approved' ORDER BY id DESC LIMIT 800")]
    pending = [dict(r) for r in con.execute("SELECT * FROM claims WHERE status='pending' ORDER BY id DESC LIMIT 50")]
    cons = [dict(r) for r in con.execute("SELECT * FROM constellations ORDER BY id")]
    episodes = [dict(r) for r in con.execute("SELECT * FROM episodes ORDER BY date DESC LIMIT 80")]
    meta = {r["key"]: r["value"] for r in con.execute("SELECT * FROM meta")}
    con.close()
    links = []
    by_key: dict[str, list[int]] = {}
    for c in claims:
        for key in (str(c["subject"]), str(c["object"])):
            if key and len(key) >= 2:
                by_key.setdefault(key, []).append(int(c["id"]))
    seen = set()
    for key, ids in by_key.items():
        if len(ids) < 2 or len(ids) > 8:
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                pair = tuple(sorted((ids[i], ids[j])))
                if pair in seen:
                    continue
                seen.add(pair)
                links.append({"source": pair[0], "target": pair[1], "reason": key})
    # 同星座内相邻记忆连线，让星座有形状
    by_const: dict[int, list[int]] = {}
    for c in claims:
        by_const.setdefault(int(c["constellation_id"] or 0), []).append(int(c["id"]))
    for ids in by_const.values():
        ids = sorted(ids)
        for i in range(len(ids) - 1):
            pair = tuple(sorted((ids[i], ids[i + 1])))
            if pair in seen:
                continue
            seen.add(pair)
            links.append({"source": pair[0], "target": pair[1], "reason": "星座"})
    episodes_out = []
    for ep in episodes:
        ids = [int(c["id"]) for c in claims if int(c["episode_id"] or 0) == int(ep["id"])]
        if ids:
            ep = dict(ep)
            ep["claim_ids"] = ids
            ep["title"] = ep.get("title") or f"{ep.get('date','')} 的记忆"
            episodes_out.append(ep)
    return {
        "ok": True,
        "constellations": cons,
        "claims": claims,
        "pending": pending,
        "links": links[:160],
        "episodes": episodes_out,
        "stats": {
            "approved": len(claims),
            "pending": len(pending),
            "constellations": len(cons),
            "episodes": len(episodes_out),
            "last_extract": meta.get("last_extract", ""),
        },
    }


def _provider() -> tuple[str, str, str]:
    try:
        cfg = json.loads(CONFIG.read_text("utf-8-sig"))
        sources = cfg.get("provider_sources") or []
        src = next((s for s in sources if s.get("enable")), None) or (sources[0] if sources else {})
        key = src.get("key") or []
        api_key = key[0] if isinstance(key, list) and key else (key if isinstance(key, str) else "")
        base = str(src.get("api_base") or "https://api.deepseek.com/v1").rstrip("/")
        providers = cfg.get("provider") or []
        model = next((p.get("model") for p in providers if p.get("enable")), "") or "deepseek-chat"
        return api_key, base, model
    except Exception:
        return "", "https://api.deepseek.com/v1", "deepseek-chat"


EXTRACT_SYSTEM = """你是记忆星图的抽取器。只从对话里抽取可以长期复用的原子事实，不要写总结、不要编造。
输出严格 JSON：{"claims":[{"subject":"主体","subject_kind":"人物/地点/事件/兴趣/承诺/关系/其他","predicate":"关系或动作","object":"客体/内容","object_kind":"同上","category":"人物/关系/事件/兴趣/承诺/偏好/事实","confidence":0.8,"quote":"原文里的一句证据","message_ids":[1,2],"date":"YYYY-MM-DD"}]}
规则：
- 每条 claim 必须能回到原文 quote；quote 必须是消息里的原话片段。
- 主体通常是用户或群友的名字/昵称；也可以是小鲸鱼自己。
- 只抽取稳定信息：身份、关系、偏好、承诺、重要事件、地点、兴趣；不抽天气、一次性寒暄、闲聊语气。
- 不要抽系统功能、模块、API、接口、配置、代码、开发任务、测试请求；这些不是人的长期记忆。
- 疑问句、请求句、临时需求不要直接当事实，除非明确表达了长期偏好或承诺。
- 同一件事只抽一条；合并同一主体同一谓词。
- 没有值得记的就返回 {"claims":[]}。"""


def _extract_json(text: str) -> dict:
    text = str(text or "").strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


def _chat(api_key: str, base: str, model: str, system: str, user: str) -> str:
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.1,
        "max_tokens": 2000,
    }
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + api_key)
    req.add_header("User-Agent", "Mozilla/5.0")
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    return str(data["choices"][0]["message"]["content"] or "")


def _valid_claim(c: dict) -> bool:
    text = f"{c.get('subject','')} {c.get('predicate','')} {c.get('object','')} {c.get('quote','')}"
    bad = ("模块", "功能", "API", "接口", "token", "插件", "配置", "设置", "代码", "开发任务", "测试请求")
    if any(x in text for x in bad):
        return False
    if str(c.get("predicate") or "") in ("想让", "要求", "希望", "需要"):
        return False
    quote = str(c.get("quote") or "")
    if any(q in quote for q in ("能不能", "可以吗", "怎么", "为什么", "是不是")):
        return False
    return True


def extract(limit: int = 60) -> dict:
    ensure_db()
    api_key, base, model = _provider()
    if not api_key:
        return {"ok": False, "error": "没有找到可用模型 API Key"}
    cur = _conn()
    last_id = int(_meta(cur, "last_msg_id", "0") or 0)
    msgs = []
    if DIARY_DB.exists():
        try:
            dcon = sqlite3.connect(str(DIARY_DB), timeout=10)
            dcon.row_factory = sqlite3.Row
            rows = dcon.execute(
                "SELECT id, ts, name, sender, text FROM raw_messages WHERE id>? ORDER BY id ASC LIMIT ?",
                (last_id, limit),
            ).fetchall()
            dcon.close()
            msgs = [dict(r) for r in rows]
        except Exception as exc:
            cur.close()
            return {"ok": False, "error": f"读取日记库失败: {exc}"}
    if not msgs:
        cur.close()
        return {"ok": True, "added": 0, "messages": 0, "message": "没有新消息"}
    lines = []
    for m in msgs:
        ts = datetime.fromtimestamp(float(m.get("ts") or 0)).strftime("%Y-%m-%d %H:%M")
        name = m.get("name") or m.get("sender") or "某人"
        lines.append(f"[id={m['id']} {ts}] {name}: {str(m.get('text') or '')[:300]}")
    prompt = "已有哪些事实（避免重复）：\n" + "\n".join(
        f"- {r['subject']} {r['predicate']} {r['object']}" for r in cur.execute("SELECT subject,predicate,object FROM claims ORDER BY id DESC LIMIT 80")
    )[:3000]
    prompt += "\n\n新对话：\n" + "\n".join(lines)
    try:
        text = _chat(api_key, base, model, EXTRACT_SYSTEM, prompt)
        data = _extract_json(text)
        claims = data.get("claims") or []
        added = 0
        for c in claims:
            if not isinstance(c, dict):
                continue
            if float(c.get("confidence") or 0) < 0.45:
                continue
            if not _valid_claim(c):
                continue
            if _insert_claim(cur, c, "pending"):
                added += 1
        max_id = max(int(m["id"]) for m in msgs)
        _set_meta(cur, "last_msg_id", max_id)
        _set_meta(cur, "last_extract", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        cur.execute(
            "INSERT INTO extractions(started,finished,messages,added,status,error) VALUES(?,?,?,?,?,?)",
            (time.time(), time.time(), len(msgs), added, "ok", ""),
        )
        cur.commit()
        cur.close()
        return {"ok": True, "added": added, "messages": len(msgs), "model": model}
    except Exception as exc:
        try:
            cur.execute(
                "INSERT INTO extractions(started,finished,messages,added,status,error) VALUES(?,?,?,?,?,?)",
                (time.time(), time.time(), len(msgs), 0, "error", str(exc)[:300]),
            )
            cur.commit()
        except Exception:
            pass
        cur.close()
        return {"ok": False, "error": f"抽取失败: {exc}"}


def seed_core() -> dict:
    ensure_db()
    files = sorted(CORE_DIR.glob("*.md")) if CORE_DIR.exists() else []
    if not files:
        return {"ok": False, "error": "还没有核心设定，先去人设页写一份"}
    text = files[0].read_text("utf-8", errors="replace")
    con = _conn()
    added = 0
    section = "核心设定"
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if not line.startswith("- "):
            continue
        value = line[2:].strip()
        if len(value) < 2:
            continue
        cat_map = {
            "核心身份": "人物",
            "外形": "人物",
            "关系": "关系",
            "说话": "事实",
            "性格": "事实",
            "不像程序": "事实",
            "底线": "承诺",
        }
        claim = {
            "subject": "小鲸鱼",
            "subject_kind": "人物",
            "predicate": section,
            "object": value[:180],
            "object_kind": "事实",
            "category": cat_map.get(section, "事实"),
            "confidence": 1.0,
            "quote": value,
            "date": datetime.now().strftime("%Y-%m-%d"),
        }
        cid = _insert_claim(con, claim, "pending")
        con.commit()
        if cid:
            approve_claim(cid)
            added += 1
    con.close()
    return {"ok": True, "added": added}
