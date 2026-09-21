#!/usr/bin/env python
"""真机联调脚本：真实 LLM（配置所选，如 DeepSeek）+ 真实 Context Recall 服务。

覆盖链路：organizer（LLM 总结）→ snapshot → import → search（query_memory）。

运行（工作目录任意，路径自适应）：
    cd main/xiaozhi-server
    .venv/bin/python test/test_context_recall_live.py [--cr-url URL] [--workspace WS] [--role ROLE]

说明：
- 读取 data/.config.yaml + config.yaml 合并后的真实配置；不打印任何密钥；
- 默认写入 CR 的独立 workspace "xiaozhi-livetest"（additive，不污染正式 workspace）；
- 每次运行会产生真实 LLM 调用（约 2k tokens 内）。
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.config_loader import load_config  # noqa: E402
from core.providers.memory.context_recall.cr_client import CRClient  # noqa: E402
from core.utils import llm as llm_utils  # noqa: E402
from core.utils import memory as memory_utils  # noqa: E402
from core.utils.dialogue import Message  # noqa: E402

# 合成对话：含持久事实（灯光偏好 / 家人 / 作息），用于检验组织质量
DIALOGUE = [
    ("user", "你好呀，给我介绍一下你都能干什么。"),
    ("assistant", "你好，我可以陪你聊天、帮你控制家里的设备，也能记住你说过的事情。"),
    ("user", "先说下我家的灯：客厅的灯是暖光的，以后我说开灯就是开客厅的那盏暖光灯。"),
    ("assistant", "好的，我记得客厅的灯是暖光的，开灯默认就是它。"),
    ("user", "我儿子叫小明，今年五岁，最喜欢的动物是恐龙。"),
    ("assistant", "记住了，小明五岁，喜欢恐龙。"),
    ("user", "我平时工作日早上七点起床，周末一般会睡到九点。"),
    ("assistant", "好的，工作日七点起，周末九点起。"),
]

QUERIES = [
    "我儿子叫什么名字？",
    "客厅的灯是什么颜色的光？",
    "我早上几点起床？",
]


def build_llm(config):
    name = config["selected_module"]["LLM"]
    conf = config["LLM"][name]
    llm_type = conf.get("type", name)
    return llm_utils.create_instance(llm_type, conf), name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cr-url", default=None, help="覆盖 Memory.context_recall.service_url")
    parser.add_argument("--workspace", default="xiaozhi-livetest")
    parser.add_argument("--role", default="live-test-device")
    args = parser.parse_args()

    config = load_config()
    llm, llm_name = build_llm(config)
    mem_conf = dict(config["Memory"]["context_recall"])
    if args.cr_url:
        mem_conf["service_url"] = args.cr_url
    mem_conf["workspace_id"] = args.workspace

    print(f"LLM: {llm_name}（type={config['LLM'][llm_name].get('type')}）")
    print(f"CR : {mem_conf.get('service_url')} | workspace={args.workspace} | role={args.role}")

    provider = memory_utils.create_instance("context_recall", mem_conf)
    provider.init_memory(role_id=args.role, llm=llm, save_to_file=True)

    user_turns = sum(1 for role, _ in DIALOGUE if role == "user")
    msgs = [Message(role=role, content=content) for role, content in DIALOGUE]
    print(f"\n── 1) save_memory：{len(msgs)} 条消息（用户发言 {user_turns} 轮）→ 真实 LLM 组织 → 快照导入 CR")
    asyncio.run(_save(provider, msgs, mem_conf))
    print("\n── 2) query_memory：经 provider 检索 CR")
    asyncio.run(_query(provider))


async def _save(provider, msgs, mem_conf):
    client = CRClient(mem_conf.get("service_url", ""), timeout=5.0)
    healthy = await client.health()
    print(f"CR /health → {'OK' if healthy else '不可达'}")
    if not healthy:
        print("CR 不可达：请检查 service_url 或先启动 CR 服务")
        return
    await provider.save_memory(msgs)
    print("save_memory 完成")


async def _query(provider):
    for question in QUERIES:
        result = await provider.query_memory(question)
        print(f"\nQ: {question}")
        print("A: " + (result if result else "（未命中/空）"))


if __name__ == "__main__":
    main()
