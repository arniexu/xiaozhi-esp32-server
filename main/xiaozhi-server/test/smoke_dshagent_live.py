#!/usr/bin/env python3
"""真机冒烟：直接拿 ACP 客户端连本机 DSH agent，确认能拿到成句回复。

跑之前先执行 deploy/dsh-agent/install.sh（建好 elder_helper_acp 配置档）。

运行：cd main/xiaozhi-server && .venv/bin/python test/smoke_dshagent_live.py
      [--profile elder_helper_acp] [--workspace ~/.dsh/elder-workspace]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.providers.llm.dshagent.acp_client import AcpClient  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="elder_helper_acp")
    parser.add_argument("--workspace", default=os.path.expanduser("~/.dsh/elder-workspace"))
    parser.add_argument("--text", default="你好，我今天有点冷，想喝点热的")
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()

    os.makedirs(args.workspace, exist_ok=True)
    env = dict(os.environ)
    env.setdefault("DSH_ELDER_LITE", "1")  # 关掉与老人场景无关的重 MCP

    client = AcpClient(
        ["dsh", "--profile", args.profile],
        request_timeout=args.timeout,
        chunk_timeout=args.timeout,
        env=env,
    )
    try:
        client.start()
        hello = client.initialize()
        print(f"[acp] initialize -> {hello}")
        session_id = client.new_session(args.workspace)
        print(f"[acp] session -> {session_id}")
        print(f"[user] {args.text}")
        parts = []
        for chunk in client.prompt(session_id, args.text):
            parts.append(chunk)
            sys.stdout.write(chunk)
            sys.stdout.flush()
        print()
        reply = "".join(parts).strip()
        if not reply:
            print("[FAIL] agent 没吐任何正文", file=sys.stderr)
            return 1
        print(f"[ok] 回复 {len(reply)} 字")
        return 0
    finally:
        if not client.alive:
            print(f"[stderr]\n{client.stderr_tail()}", file=sys.stderr)
        client.close()


if __name__ == "__main__":
    sys.exit(main())
