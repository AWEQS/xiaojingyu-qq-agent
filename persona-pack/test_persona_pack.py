"""persona-pack 单元测试：不依赖 AstrBot 运行时，直接验证注入与指令逻辑。"""

import asyncio
import atexit
import importlib.util
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "data" / "plugins" / "astrbot_plugin_persona_pack" / "main.py"


def load_plugin():
    spec = importlib.util.spec_from_file_location("persona_pack_main", PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["persona_pack_main"] = mod
    spec.loader.exec_module(mod)
    return mod


def make_event(message_str="", group_id="10001", user_id="20002"):
    msg = types.SimpleNamespace(group_id=group_id, message_str=message_str)
    ev = types.SimpleNamespace(message_obj=msg, message_str=message_str)
    ev.get_sender_id = lambda: user_id
    ev.get_sender_name = lambda: "测试甲"
    ev.plain_result = lambda text: types.SimpleNamespace(text=text)
    return ev


async def main():
    mod = load_plugin()
    src_dir = PLUGIN.parent / "personas"
    names = [n for n in sorted(p.stem for p in src_dir.glob("*.md")) if not n.startswith("_")]
    assert names, f"人设目录为空: {src_dir}"
    name = "小鲸鱼" if "小鲸鱼" in names else names[0]

    # 在临时目录里跑：直接改线上人设文件会把 CRLF 读成 LF，还原后仍有 diff
    persona_dir = Path(tempfile.mkdtemp(prefix="persona-test-"))
    atexit.register(lambda: shutil.rmtree(persona_dir, ignore_errors=True))
    for _p in src_dir.glob("*.md"):
        shutil.copy2(_p, persona_dir / _p.name)

    # 测试会写入 state.json（切换默认人设/会话绑定），结束后必须还原，否则污染线上机器人
    state_file = PLUGIN.parent / "state.json"
    if state_file.exists():
        _original_state = state_file.read_text("utf-8")
        atexit.register(lambda: state_file.write_text(_original_state, "utf-8"))

    plugin = mod.PersonaPack(types.SimpleNamespace(), {"personas_dir": str(persona_dir), "default_persona": name})

    print("[1] 可用人设:", plugin._list_personas())
    assert name in plugin._list_personas(), f"没找到 {name}.md"

    # 注入测试
    ev = make_event("@小鲸鱼 在吗")
    req = types.SimpleNamespace(system_prompt="BASE_PROMPT")
    await plugin.inject_persona(ev, req)
    assert "角色卡" in req.system_prompt or "小鲸鱼" in req.system_prompt, "人设没注入"
    assert req.system_prompt.endswith("BASE_PROMPT"), "原系统提示被覆盖"
    print("[2] 注入成功，system_prompt 前 80 字:", req.system_prompt[:80].replace("\n", " "))

    # 指令测试
    async def collect(name):
        out = []
        async for r in plugin.persona_cmd(make_event(name)):
            out.append(r.text)
        return "\n".join(out)

    print("[3] /persona list ->", (await collect("/persona list")).splitlines()[0])
    print("[4] /persona use", name, "->", await collect(f"/persona use {name}"))
    print("[5] /persona show ->", (await collect("/persona show"))[:60].replace("\n", " "))
    print("[6] /persona history ->", (await collect("/persona history"))[:120])
    print("[7] /persona reload ->", await collect("/persona reload"))

    # 热重载：改文件后应读到新内容
    target = persona_dir / f"{name}.md"
    original = target.read_text("utf-8")
    try:
        target.write_text(original + "\n\n<!-- hot-reload-test -->\n", "utf-8")
        ev2 = make_event("test")
        req2 = types.SimpleNamespace(system_prompt="")
        await plugin.inject_persona(ev2, req2)
        assert "hot-reload-test" in req2.system_prompt, "热重载没生效"
        print("[8] 热重载生效")
    finally:
        target.write_text(original, "utf-8")

    print("\n全部通过")


if __name__ == "__main__":
    asyncio.run(main())
