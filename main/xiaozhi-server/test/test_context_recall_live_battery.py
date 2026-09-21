#!/usr/bin/env python
"""真机召回电池：多话题对话 → 查询矩阵（直连命中 / 摘要兜底 / 负例空结果）。

运行（main/xiaozhi-server 下）：
    .venv/bin/python test/test_context_recall_live_battery.py [--workspace xiaozhi-battery]

说明：
- 会产生 2 次真实 LLM 组织调用（配置所选 LLM，如 DeepSeek）；
- 写入独立 workspace（additive，不影响正式数据）；
- 判级：✅ 关键词在直连命中（非会话摘要行）；🟡 仅会话摘要兜底；❌ 未命中；
  负例 ⬜ 正确返回空；并检查跨 scope 污染（LVGL/continuity 等无关内容）。
"""

import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
from config.config_loader import load_config  # noqa: E402
from core.providers.memory.context_recall.cr_client import CRClient  # noqa: E402
from core.utils import llm as llm_utils  # noqa: E402
from core.utils import memory as memory_utils  # noqa: E402
from core.utils.dialogue import Message  # noqa: E402

SESSION_1 = [
    ("user", "说下我家的情况：我儿子叫小明，五岁，最喜欢恐龙。"),
    ("assistant", "好的，小明五岁，喜欢恐龙。"),
    ("user", "我女儿叫小雨，八岁，在学钢琴。"),
    ("assistant", "记住了，小雨八岁，学钢琴。"),
    ("user", "客厅的灯是暖光的，以后说开灯就是开客厅这盏灯。"),
    ("assistant", "好的，开灯默认指客厅暖光灯。"),
    ("user", "我们周末一般会去爬山。"),
    ("assistant", "好的，周末爬山。"),
]

SESSION_2 = [
    ("user", "我工作日早上七点起床，周末睡到九点。"),
    ("assistant", "好的，工作日七点，周末九点。"),
    ("user", "我的早餐固定是豆浆和油条。"),
    ("assistant", "记住了，早餐豆浆油条。"),
    ("user", "每周三记得提醒我倒垃圾。"),
    ("assistant", "好的，每周三倒垃圾。"),
    ("user", "我平时喜欢听周杰伦的歌。"),
    ("assistant", "好的，喜欢周杰伦。"),
]

# (问句, 期望关键词[任一], 是否为空例)
MATRIX = [
    ("我儿子叫什么名字？", ["小明"], False),
    ("小明喜欢什么动物", ["恐龙"], False),
    ("我女儿在学什么乐器？", ["钢琴", "小雨"], False),
    ("小雨几岁了？", ["八", "8"], False),
    ("客厅的灯是什么颜色的光？", ["暖"], False),
    ("怎么开客厅的灯？", ["暖", "开灯"], False),
    ("我们周末有什么安排？", ["爬山"], False),
    ("我早上几点起床？", ["七点", "7点", "七"], False),
    ("我早餐吃什么？", ["豆浆", "油条"], False),
    ("垃圾什么时候倒？", ["垃圾"], False),
    ("我喜欢听谁的歌？", ["周杰伦"], False),
    ("小明", ["小明"], False),
    ("开灯", ["开灯"], False),
    ("今天天气怎么样？", [], True),
    ("帮我订一张机票", [], True),
    ("我养过什么宠物？", [], True),
]

CONTAMINATION_MARKERS = ("LVGL", "continuity:")


def build_llm(config):
    name = config["selected_module"]["LLM"]
    conf = config["LLM"][name]
    return llm_utils.create_instance(conf.get("type", name), conf), name


async def save_session(provider, turns):
    msgs = [Message(role=role, content=content) for role, content in turns]
    await provider.save_memory(msgs)


async def run_matrix(provider, client, workspace):
    results = []
    for query, keywords, expect_empty in MATRIX:
        out = await provider.query_memory(query)
        lines = [line for line in out.split("\n") if line.strip()]
        direct = [line for line in lines if not line.startswith("- 会话 ")]
        summary = [line for line in lines if line.startswith("- 会话 ")]

        if expect_empty:
            grade = "⬜" if not lines else "❌"
            detail = "空" if not lines else f"有结果({len(lines)})"
        else:
            in_direct = any(kw in line for kw in keywords for line in direct)
            in_summary = any(kw in line for kw in keywords for line in summary)
            grade = "✅" if in_direct else ("🟡" if in_summary else "❌")
            detail = f"直连{len(direct)}/摘要{len(summary)}"
        contamination = [m for m in CONTAMINATION_MARKERS if any(m in line for line in lines)]
        if contamination:
            grade = "❌"
            detail += f" 污染={contamination}"
        results.append((query, grade, detail, out))
        time.sleep(0.05)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default="xiaozhi-battery")
    args = parser.parse_args()

    config = load_config()
    llm, llm_name = build_llm(config)
    mem_conf = dict(config["Memory"]["context_recall"])
    mem_conf["workspace_id"] = args.workspace

    print(f"LLM: {llm_name} | CR: {mem_conf.get('service_url')} | workspace: {args.workspace}")
    client = CRClient(mem_conf.get("service_url", ""), timeout=5.0)
    print(f"CR /health: {'OK' if asyncio.run(client.health()) else '不可达'}")
    try:
        health = httpx.get(
            f"{mem_conf.get('service_url')}/health", timeout=5, trust_env=False
        ).json()
        if health.get("neo4j", {}).get("configured"):
            print("⚠️ 该 CR 实例启用了 Neo4j：导入会同步进图谱（建议改用 graph-off 实例测试）。")
    except Exception:  # noqa: BLE001 - 健康检查不影响主流程
        pass
    print()

    provider = memory_utils.create_instance("context_recall", mem_conf)
    provider.init_memory(role_id="battery-device", llm=llm, save_to_file=True)

    for index, turns in enumerate((SESSION_1, SESSION_2), start=1):
        print(f"── 导入会话 {index}（{sum(1 for r, _ in turns if r == 'user')} 轮用户发言）")
        asyncio.run(save_session(provider, turns))
        time.sleep(2)  # 保证两次会话的 session_id 不同

    print("\n── 查询矩阵")
    results = asyncio.run(run_matrix(provider, client, args.workspace))
    for query, grade, detail, out in results:
        print(f"{grade} {query}  — {detail}")
        for line in out.split("\n")[:3]:
            if line.strip():
                print(f"     {line[:96]}")

    direct = sum(1 for _, g, _, _ in results if g == "✅")
    partial = sum(1 for _, g, _, _ in results if g == "🟡")
    failed = sum(1 for _, g, _, _ in results if g == "❌")
    empty_ok = sum(1 for _, g, _, _ in results if g == "⬜")
    print("-" * 60)
    print(f"总计：✅直连 {direct} ｜ 🟡摘要兜底 {partial} ｜ ❌失败 {failed} ｜ ⬜负例正确 {empty_ok}"
          f"（共 {len(results)} 条）")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
