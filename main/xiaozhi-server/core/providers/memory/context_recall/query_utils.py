# -*- coding: utf-8 -*-
"""检索增强：把自然语言问句拆成候选检索词（调用方模拟 OR 语义）。

背景（2026-09-21 真机联调实测，见 docs/singleton-mode-plan.md §8）：
- CR 词法门对 CJK 查询做"连续子串 AND"匹配：查询里每个连续 CJK 片段必须**原样
  出现**在记忆文本中——``儿子`` 能命中，但整句 ``我儿子叫什么名字`` 必然漏；
- 语义通道要求调用方随请求携带 embedding（xiaozhi 侧没有嵌入器）→ 不参与。
因此 provider 侧把问句拆成内容片段，多路检索后在客户端合并去重（OR 语义）。

拆分规则（保守、确定性、可单测）：
1. 原文永远作为第 1 路候选；
2. 多字停用词（疑问/礼貌/虚词框）整体剔除、单字停用词逐字剔除，剔除处=片段分隔；
3. 剩余 CJK 片段按出现顺序取多字片段；**单字片段只作兜底**（整句没有多字片段时，
   如“灯在哪”）——实测单字子串噪声大：候选“光”会把 workspace 为空的历史决策
   拉进客厅灯检索；
4. 去重、限量（默认 6 路，含原文）。

注意：拆分只发生在**检索侧**，不改变落库内容与组织结果；候选生成失败时退化为
"只用原文单路"（与拆分前行为一致）。
"""

import re

CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")

# 多字停用词：疑问/礼貌/虚词框（按长度降序剔除，"为什么"先于"什么"）
MULTI_STOPWORDS = (
    "为什么",
    "什么样",
    "怎么样",
    "什么",
    "几点",
    "多少",
    "怎么",
    "怎样",
    "如何",
    "为何",
    "请问",
    "告诉",
    "知道",
    "记得",
    "帮我",
    "帮忙",
    "一下",
    "时候",
    "哪里",
    "哪儿",
    "哪个",
    "干什么",
    "干啥",
)

# 单字停用词：代词/助词/疑问字/常见虚词（不含 不/没/无 等否定词，避免改变语义）
SINGLE_STOPWORDS = set(
    "的了吗呢吧啊呀嘛哦嗯哈我你您他她它们谁哪几啥咋是在叫会有能想要说给到过着也和与把被这那都就还再很太更最"
)

MAX_CANDIDATES = 6


def _strip_stopwords(text: str) -> str:
    """剔除停用词（替换为空格以保留片段边界）。"""
    result = text
    for word in sorted(MULTI_STOPWORDS, key=len, reverse=True):
        result = result.replace(word, " ")
    return "".join(" " if char in SINGLE_STOPWORDS else char for char in result)


def build_query_candidates(query: str, max_candidates: int = MAX_CANDIDATES):
    """生成候选检索词列表：``[原文, 多字片段..., 单字片段...]``（去重、限量）。"""
    text = (query or "").strip()
    if not text:
        return []
    candidates = [text]
    stripped = _strip_stopwords(text)
    fragments = CJK_RUN.findall(stripped)
    multi = [fragment for fragment in fragments if len(fragment) >= 2]
    singles = [fragment for fragment in fragments if len(fragment) == 1]
    # 单字子串噪声大（会跨 scope 命中），只在整个查询没有多字片段时兜底
    ordered = multi if multi else singles
    for fragment in ordered:
        if len(candidates) >= max_candidates:
            break
        if fragment not in candidates:
            candidates.append(fragment)
    return candidates[:max_candidates]


def merge_hit_lists(hit_lists, limit=None):
    """按路序合并多路检索结果：按 id 去重、保持"原文路优先"的顺序、可限量。"""
    merged = []
    seen = set()
    for hits in hit_lists or []:
        for hit in hits or []:
            if not isinstance(hit, dict):
                continue
            key = hit.get("id") or f"{hit.get('summary', '')}|{hit.get('resolution', '')}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(hit)
            if limit is not None and len(merged) >= limit:
                return merged
    return merged


def build_fallback_candidates(query: str, max_candidates: int = MAX_CANDIDATES):
    """二阶段兑底候选：对多字片段做滑动二字组 + 单字片段（仅在首轮全空时使用）。

    背景（真机电池实测）：
    - 停用词剔除会把手邻内容字粘连成不存在的字面（"早餐吃"、"开客厅"）；
    - 内容片段本身较长、或词间有虚词分隔后不连续（"小明喜欢"）——
    首轮字面 AND 全空时，用二字组做 OR 回退（如 "早餐吃"→ 早餐；"小明喜欢"→ 小明）。
    """
    text = (query or "").strip()
    if not text:
        return []
    stripped = _strip_stopwords(text)
    fragments = CJK_RUN.findall(stripped)
    candidates = []
    for fragment in fragments:
        if len(fragment) >= 3:
            for index in range(len(fragment) - 1):
                bigram = fragment[index : index + 2]
                if bigram not in candidates:
                    candidates.append(bigram)
    for fragment in fragments:
        if len(fragment) == 1 and fragment not in candidates:
            candidates.append(fragment)
    return candidates[:max_candidates]
