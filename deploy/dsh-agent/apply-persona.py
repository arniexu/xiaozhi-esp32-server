#!/usr/bin/env python3
"""把 persona/elder-persona.md 写进两个 DSH 配置档。

装到哪：
  1) ~/.dsh/profiles/elder_helper_acp/cordis.patch.yml
     → system-prompt.personaPrefix（小智语音链路，ACP 档）
  2) ~/.dsh/profiles/elder_helper/cordis.patch.yml
     → preset-standard.plugins.persona.prefix（web UI）
     注意：web 档的会话走 preset-standard，preset 里的 persona 行会 shadow 部署级
     人设（dsh-persona 源码写明的机制），所以必须整列替换 preset 的 plugins。

幂等：web 档会先删掉上次写的那段（以 "# ── 老人陪伴人设" 开头），
再重新 `dsh --dump-config` 取干净的 preset-standard，然后写回。

用法：
    python3 deploy/dsh-agent/apply-persona.py            # 两个都装
    python3 deploy/dsh-agent/apply-persona.py --only acp  # 只装语音档
    python3 deploy/dsh-agent/apply-persona.py --only web
"""

import argparse
import io
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PERSONA = os.path.join(HERE, "persona", "elder-persona.md")
HOME = os.path.expanduser("~")
PROFILES = os.path.join(HOME, ".dsh", "profiles")
WEB_MARKER = "# ── 老人陪伴人设"


def persona_lines():
    text = io.open(PERSONA, encoding="utf-8").read()
    if "\n---\n" not in text:
        sys.exit(f"{PERSONA} 里缺少 `---` 分隔线（前面是说明，后面才是人设正文）")
    body = text.split("\n---\n", 1)[1].strip("\n")
    return body.split("\n")


def backup(path):
    """先备份再改：复制而不是移动，脚本中途失败也不会把原文件弄丢。"""
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak-persona")


def apply_acp(lines):
    path = os.path.join(PROFILES, "elder_helper_acp", "cordis.patch.yml")
    text = io.open(path, encoding="utf-8").read()
    start = text.index("- id: system-prompt")
    end = len(text)
    for marker in ("\n- id: agent-default-model", "\n- id: acp"):
        idx = text.find(marker, start)
        if idx != -1:
            end = min(end, idx)
    body = "\n".join("            " + line for line in lines)
    block = "- id: system-prompt\n  config:\n    personaPrefix: |-\n" + body + "\n"
    io.open(path, "w", encoding="utf-8").write(text[:start] + block + text[end:])
    print(f"[acp] 已写人设：{path}")


def dump_config(profile):
    with tempfile.NamedTemporaryFile("w+", suffix=".yml", delete=False) as handle:
        target = handle.name
    subprocess.run(
        ["dsh", "--profile", profile, "--dump-config"],
        stdout=open(target, "w", encoding="utf-8"),
        stderr=subprocess.DEVNULL,
        check=True,
    )
    return io.open(target, encoding="utf-8").read().split("\n")


def apply_web(lines):
    path = os.path.join(PROFILES, "elder_helper", "cordis.patch.yml")
    text = io.open(path, encoding="utf-8").read()

    # 先摘掉上次写的块，dump 出来才是干净的 preset
    if WEB_MARKER in text:
        text = text.split(WEB_MARKER)[0].rstrip() + "\n"
        io.open(path, "w", encoding="utf-8").write(text)

    dump = dump_config("elder_helper")
    start = next(i for i, line in enumerate(dump) if line.startswith("- id: preset-standard"))
    end = next(
        i
        for i, line in enumerate(dump[start + 1 :], start + 1)
        if line.startswith("- id: ") or line.startswith("# ==")
    )
    block = dump[start + 1 : end]
    cfg_start = next(i for i, line in enumerate(block) if line.startswith("  config:"))
    cfg = block[cfg_start:]

    out, replaced = [], False
    for line in cfg:
        if line.strip().startswith("prefix:"):
            out.append("          prefix: |-")
            out.extend("            " + item for item in lines)
            replaced = True
        else:
            out.append(line)
    if not replaced:
        sys.exit("preset-standard 里没找到 persona prefix，DSH 版本可能变了，人工看一下")

    text += (
        f"\n{WEB_MARKER}（preset 内的 persona 会 shadow 部署级人设，所以整列替换 preset-standard.plugins）\n"
        "- id: preset-standard\n" + "\n".join(out) + "\n"
    )
    io.open(path, "w", encoding="utf-8").write(text)
    print(f"[web] 已写人设：{path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=["acp", "web"], help="只装其中一个")
    args = parser.parse_args()

    lines = persona_lines()
    if not lines:
        sys.exit("人设正文是空的")

    for name, target in (("acp", os.path.join(PROFILES, "elder_helper_acp")),
                         ("web", os.path.join(PROFILES, "elder_helper"))):
        if args.only and args.only != name:
            continue
        if not os.path.isdir(target):
            print(f"[{name}] 跳过：{target} 不存在（先跑 install.sh）")
            continue
        backup(os.path.join(target, "cordis.patch.yml"))
        if name == "acp":
            apply_acp(lines)
        else:
            apply_web(lines)
        print(f"[{name}] 备份在 cordis.patch.yml.bak-persona；重启对应实例后生效")


if __name__ == "__main__":
    main()
