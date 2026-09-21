#!/usr/bin/env python
"""真机加强版召回测试 v3：更新/冲突、精度噪声、时延、组织质量审计。

与 battery 的区别（battery = 基础事实检索冒烟）：
- 三段会话：基础事实 → 设备/日程 → **更正与变更 + 设备杂音**（考组织器过滤与更新行为）
- 26 条查询矩阵：正例 / 负例 / **数字变体** / 短词；带**噪声关键词**与**陈旧值检测**
- 指标：直连命中率、摘要兜底、噪声行数、陈旧冲突标记、时延 p50/p95
- 快照审计：拦截 import 载荷 → 检查"设备杂音未入库"、"事实覆盖率"
- 稳定性：3 条关键查询 ×3 次重复，判级必须一致

安全阀：目标若为启用 Neo4j 的实例（如 8765），默认拒绝运行（避免再写用户图谱）；
确需运行加 --allow-neo4j。建议指向 graph-off 实例（如 8876）。

用法：
    .venv/bin/python test/test_context_recall_live_hard.py --cr-url http://127.0.0.1:8876
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
    ("user", "我儿子叫小明，五岁，最喜欢恐龙。"),
    ("assistant", "好的，小明五岁，喜欢恐龙。"),
    ("user", "我女儿叫小雨，八岁，在学钢琴。"),
    ("assistant", "记住了，小雨八岁，学钢琴。"),
    ("user", "我不喝咖啡，喝了睡不着。"),
    ("assistant", "好的，不喝咖啡。"),
    ("user", "我的生日是3月15日。"),
    ("assistant", "记住了，3月15日。"),
]

SESSION_2 = [
    ("user", "客厅的灯是暖光的，以后说开灯就打开客厅这盏灯。"),
    ("assistant", "好的，开灯默认指客厅暖光灯。"),
    ("user", "我们周末一般去爬山。"),
    ("assistant", "好的，周末爬山。"),
    ("user", "每月10号要交房租，记得提醒我。"),
    ("assistant", "好的，每月10号提醒交房租。"),
    ("user", "每周三记得提醒我倒垃圾。"),
    ("assistant", "好的，每周三倒垃圾。"),
    ("user", "我平时喜欢听周杰伦的歌。"),
    ("assistant", "好的，喜欢周杰伦。"),
]

SESSION_3 = [
    ("user", "更正一下：我女儿小雨其实九岁了，之前说错了。"),
    ("assistant", "好的，更正为九岁。"),
    ("user", "周末的安排改了，以后不去爬山了，改成去游泳。"),
    ("assistant", "好的，周末改游泳。"),
    ("user", "咖啡我改喝美式了，不过每周最多两杯。"),
    ("assistant", "好的，改喝美式，每周最多两杯。"),
    ("user", "把客厅的灯打开。"),
    ("assistant", "好的，已打开客厅的暖光灯。"),
    ("user", "谢谢，就这样。"),
    ("assistant", "好的。"),
]

# 查询矩阵：query / relevant（期望关键词任一）/ noise（不应出现在直连行的词）/ stale（陈旧值警示）
MATRIX = [
    {"q": "我儿子叫什么名字？", "rel": ["小明"], "noise": ["钢琴"]},
    {"q": "小明喜欢什么动物", "rel": ["恐龙"], "noise": ["钢琴"]},
    {"q": "我女儿在学什么乐器？", "rel": ["钢琴", "小雨"], "noise": ["恐龙"]},
    {"q": "小雨几岁了？", "rel": ["九", "9"], "stale": ["八", "8"]},
    {"q": "客厅的灯是什么颜色的光？", "rel": ["暖"], "noise": ["咖啡"]},
    {"q": "怎么开客厅的灯？", "rel": ["开灯", "暖"]},
    {"q": "我们周末有什么安排？", "rel": ["游泳"], "stale": ["爬山"]},
    {"q": "我平时喝咖啡吗？", "rel": ["咖啡"], "noise": ["垃圾"]},
    {"q": "我的生日是什么时候？", "rel": ["3月15", "3 月 15", "三月十五", "315"]},
    {"q": "几号交房租？", "rel": ["房租"], "noise": ["垃圾"]},
    {"q": "垃圾什么时候倒？", "rel": ["垃圾"], "noise": ["房租"]},
    {"q": "我喜欢听谁的歌？", "rel": ["周杰伦"]},
    {"q": "咖啡", "rel": ["咖啡"]},
    {"q": "房租", "rel": ["房租"]},
    {"q": "小雨", "rel": ["小雨"]},
    {"q": "游泳", "rel": ["游泳"]},
    {"q": "我的女儿叫什么？", "rel": ["小雨"], "noise": ["恐龙"]},
    {"q": "每月十号要做什么？", "rel": ["房租"]},
    {"q": "今天天气怎么样？", "empty": True},
    {"q": "帮我订一张机票", "empty": True},
    {"q": "我养过什么宠物？", "empty": True},
    {"q": "推荐一部电影", "empty": True},
]

STABILITY_QUERIES = ["我儿子叫什么名字？", "小雨几岁了？", "垃圾什么时候倒？"]
DEVICE_CHATTER_MARKERS = ("已打开", "好的，已")


class RecordingClient:
    """包一层真实 CRClient：透传检索，截获导入快照用于审计。"""

    def __init__(self, real):
        self.real = real
        self.snapshots = []

    async def search(self, *args, **kwargs):
        return await self.real.search(*args, **kwargs)

    async def import_snapshot(self, snapshot, timeout=10.0):
        self.snapshots.append(snapshot)
        return await self.real.import_snapshot(snapshot, timeout)

    async def health(self):
        return await self.real.health()


def build_llm(config):
    name = config["selected_module"]["LLM"]
    conf = config["LLM"][name]
    return llm_utils.create_instance(conf.get("type", name), conf), name


def grade(spec, out):
    lines = [line for line in out.split("\n") if line.strip()]
    direct = [line for line in lines if not line.startswith("- 会话 ")]
    summary = [line for line in lines if line.startswith("- 会话 ")]
    noise = [line for line in direct if any(word in line for word in spec.get("noise", []))]
    stale = [word for word in spec.get("stale", []) if any(word in line for line in direct)]

    if spec.get("empty"):
        result = "⬜" if not lines else "❌"
        return result, ("空" if not lines else f"非空({len(lines)})"), noise, []
    hit_direct = any(word in line for word in spec["rel"] for line in direct)
    hit_summary = any(word in line for word in spec["rel"] for line in summary)
    result = "✅" if hit_direct else ("🟡" if hit_summary else "❌")
    note = f"直连{len(direct)}/摘要{len(summary)}"
    if noise:
        note += f" 噪声{len(noise)}"
    if stale:
        note += f" ⚠️残留{stale}"
    return result, note, noise, stale


async def save_session(provider, turns):
    msgs = [Message(role=role, content=content) for role, content in turns]
    await provider.save_memory(msgs)


def audit_snapshots(snapshots):
    """快照审计：设备杂音、事实覆盖、节点清单。"""
    print("\n── 快照审计")
    problems = []
    all_nodes = []
    for index, snapshot in enumerate(snapshots, start=1):
        nodes = snapshot.get("nodes", [])
        all_nodes.extend(nodes)
        print(f"  会话 {index}: {len(nodes)} 节点")
        for node in nodes:
            print(f"    [{node.get('kind')}] {str(node.get('label'))[:42]}")

    chatter = [
        node
        for node in all_nodes
        if any(marker in (node.get("label", "") + node.get("summary", "")) for marker in DEVICE_CHATTER_MARKERS)
    ]
    if chatter:
        problems.append(f"设备杂音入库: {len(chatter)} 条")
    else:
        print("  ✓ 设备杂音（'已打开…'）未入库")

    fact_groups = {
        "小明": ["小明"],
        "小雨": ["小雨"],
        "钢琴": ["钢琴"],
        "不喝咖啡/美式": ["咖啡"],
        "生日": ["生日", "3月15"],
        "暖光/开灯": ["暖光", "开灯"],
        "游泳": ["游泳"],
        "房租": ["房租"],
        "垃圾": ["垃圾"],
        "周杰伦": ["周杰伦"],
    }
    blob = "\n".join(
        (node.get("label", "") + node.get("summary", "")) for node in all_nodes
    )
    missing = [name for name, words in fact_groups.items() if not any(word in blob for word in words)]
    if missing:
        problems.append(f"事实未覆盖: {missing}")
    else:
        print("  ✓ 10 组事实全部有节点覆盖")
    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cr-url", default=None)
    parser.add_argument("--workspace", default="xiaozhi-hard")
    parser.add_argument("--allow-neo4j", action="store_true")
    args = parser.parse_args()

    config = load_config()
    llm, llm_name = build_llm(config)
    mem_conf = dict(config["Memory"]["context_recall"])
    if args.cr_url:
        mem_conf["service_url"] = args.cr_url
    mem_conf["workspace_id"] = args.workspace
    cr_url = mem_conf.get("service_url")

    try:
        health = httpx.get(f"{cr_url}/health", timeout=5, trust_env=False).json()
    except Exception as exc:  # noqa: BLE001
        print(f"CR 不可达: {cr_url} ({type(exc).__name__})")
        return 2
    neo4j_on = health.get("neo4j", {}).get("configured", False)
    if neo4j_on and not args.allow_neo4j:
        print(f"拒绝运行：{cr_url} 启用了 Neo4j，导入会同步进图谱（需 --allow-neo4j 才继续）")
        return 2
    print(f"LLM: {llm_name} | CR: {cr_url} | workspace: {args.workspace} | neo4j: {neo4j_on}")

    provider = memory_utils.create_instance("context_recall", mem_conf)
    recorder = RecordingClient(CRClient(cr_url, timeout=5.0))
    provider.client = recorder
    provider.init_memory(role_id="hard-device", llm=llm, save_to_file=True)

    for index, turns in enumerate((SESSION_1, SESSION_2, SESSION_3), start=1):
        print(f"── 导入会话 {index}（{sum(1 for role, _ in turns if role == 'user')} 轮用户发言）")
        asyncio.run(save_session(provider, turns))
        time.sleep(2)

    print("\n── 查询矩阵（26 条含负例）")
    failures = 0
    noise_total = 0
    stale_total = 0
    latencies = []
    for spec in MATRIX:
        started = time.perf_counter()
        out = asyncio.run(provider.query_memory(spec["q"]))
        latencies.append((time.perf_counter() - started) * 1000)
        result, note, noise, stale = grade(spec, out)
        noise_total += len(noise)
        stale_total += len(stale)
        if result == "❌":
            failures += 1
        print(f"{result} {spec['q']}  — {note}")
        if result == "❌":
            for line in out.split("\n")[:4]:
                if line.strip():
                    print(f"      {line[:94]}")

    print("\n── 稳定性（3 查询 ×3 次，判级需一致）")
    stability_ok = True
    for query in STABILITY_QUERIES:
        spec = next(item for item in MATRIX if item["q"] == query)
        grades = []
        for _ in range(3):
            out = asyncio.run(provider.query_memory(query))
            grades.append(grade(spec, out)[0])
            time.sleep(0.1)
        consistent = len(set(grades)) == 1
        stability_ok = stability_ok and consistent
        print(f"{'✅' if consistent else '❌'} {query}  — {grades}")

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[max(0, int(len(latencies) * 0.95) - 1)]
    print(f"\n── 时延：p50={p50:.0f}ms p95={p95:.0f}ms max={latencies[-1]:.0f}ms（{len(latencies)} 次查询）")

    problems = audit_snapshots(recorder.snapshots)

    print("\n" + "-" * 60)
    print(f"矩阵：❌{failures} ｜ 噪声行 {noise_total} ｜ 陈旧冲突 {stale_total} ｜ 稳定性{'OK' if stability_ok else 'FAIL'}")
    if problems:
        print("审计问题：" + "；".join(problems))
    ok = failures == 0 and stability_ok and not problems
    print("结论：" + ("通过（⚠️项见上）" if ok else "不通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
