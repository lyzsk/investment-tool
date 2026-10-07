#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ASR 谐音纠错（本地 qwen3:14B + 实体词典）
原理：拼音索引召回（stock_dict 5563 股票名 + entity_dict 热点实体 + 内置指数/板块词表）
      → 候选映射喂给本地 14B 终审 → 输出校正文+勘误表
用法:  python asr_correct_local.py <asr文本文件> [--model qwen3:14b] [--json]
依赖:  uv run --with pypinyin,requests python asr_correct_local.py ...
"""
import json, re, sys, os, argparse, difflib
from pypinyin import pinyin, Style

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # investment-tool/scripts/
MODELS = os.path.join(BASE, "models")
sys.path.insert(0, MODELS)
from local_llm import chat as llm_chat  # 10/7 统一客户端(去 requests 依赖; 剥<think>/超时一致)

# 内置指数/板块/常见术语（stock_dict 只含个股，指数板块在此补）
EXTRA_TERMS = [
    "中证2000", "中证1000", "中证500", "沪深300", "上证50", "科创50", "创业板指", "上证指数",
    "深证成指", "北证50", "微盘股", "创业板", "科创板", "主板", "北交所", "恒生科技", "纳斯达克",
    "长鑫科技", "中芯国际", "中际旭创", "新易盛", "天孚通信", "寒武纪", "海光信息",
]

def py_norm(s):
    """归一化拼音：前后鼻音合并(ng→n)——覆盖南方口音谐音(常兴↔长鑫 xing/xin)"""
    return "".join(p[0][:-1] if p[0].endswith("g") else p[0] for p in pinyin(s, style=Style.NORMAL))

def load_dicts():
    stocks = json.load(open(os.path.join(MODELS, "stock_dict.json"), encoding="utf-8"))
    entities = json.load(open(os.path.join(MODELS, "entity_dict.json"), encoding="utf-8"))
    names = list(stocks.keys()) + entities + EXTRA_TERMS
    idx = {}
    for n in set(names):
        idx.setdefault(py_norm(n), set()).add(n)  # 10/7 修: 键也走归一化(原 py() 未定义+两侧不一致, 归一化从未生效)
    return idx, set(names)

def find_candidates(text, idx, valid_names, min_n=2, max_n=6):
    """扫文本 n-gram，归一化拼音精确匹配词典 → (原文片段 → [候选正名])（宁缺毋滥，禁模糊召回）"""
    cands = {}
    chars = re.findall(r"[一-鿿0-9A-Za-z]+", text)
    text_clean = "".join(chars)
    L = len(text_clean)
    for n in range(max_n, min_n - 1, -1):
        for i in range(0, L - n + 1):
            gram = text_clean[i:i+n]
            if gram in valid_names:
                continue  # 本来就是正名
            hit = {h for h in idx.get(py_norm(gram), set()) if h != gram and abs(len(h) - len(gram)) <= 1}
            if hit:
                cands[gram] = sorted(hit)
    # 按长度去重（长 gram 优先，去掉被包含的短 gram）
    keys = sorted(cands, key=len, reverse=True)
    keep = {}
    for k in keys:
        if not any(k != j and k in j for j in keep):
            keep[k] = cands[k]
    return dict(list(keep.items())[:40])  # 上限 40 条防爆 prompt

def correct(text, model):
    idx, valid = load_dicts()
    cands = find_candidates(text, idx, valid)
    cand_str = "\n".join(f"  「{k}」→ 候选: {'/'.join(v)}" for k, v in cands.items()) or "  （无召回）"
    prompt = f"""你是A股财经语音转写纠错器。规则:
1. 只改金融实体的谐音错字(股票名/指数/板块/机构/术语), 其他口语一字不动
2. 优先使用下面召回的候选映射; 候选外但语境上明显是金融实体错字的也可改(在fix后标注[候选外])
3. 输出JSON: {{"corrected": "校正后全文", "fixes": [{{"orig": "原词", "fix": "正名"}}]}}
4. fixes只列实际改动的; 没改动则fixes为空数组

召回候选:
{cand_str}

原文:
{text}

只输出JSON, 不要解释:"""
    out = llm_chat(model, prompt, temperature=0.1, timeout=300)
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return {"corrected": text, "fixes": [], "_raw": out[:300], "_cands": len(cands)}
    try:
        d = json.loads(m.group(0))
        d["_cands"] = len(cands)
        return d
    except Exception:
        return {"corrected": text, "fixes": [], "_raw": out[:300], "_cands": len(cands)}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--model", default="qwen3:14b")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    text = open(a.input, encoding="utf-8").read() if os.path.isfile(a.input) else a.input
    res = correct(text, a.model)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print("=== 校正文 ===")
        print(res["corrected"])
        print("=== 勘误 ===")
        for f in res.get("fixes", []):
            print(f"  {f['orig']} → {f['fix']}")
        print(f"(召回候选 {res.get('_cands')} 条)")