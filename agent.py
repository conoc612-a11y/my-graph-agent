"""시작 개체 → n홉 확장 → 근거만으로 답변. LangGraph 3노드: anchor → expand → answer."""
import json
import sys
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from openai import OpenAI

from common import HERE, load_key, norm, read_config, read_docs, read_graph


class S(TypedDict):
    question: str
    anchor: str
    paths: list
    answer: str
    refused: bool


def neighbors(g, key):
    out = []
    for e in g["edges"]:
        if (e["s"], e["s_type"]) == key:
            out.append((e["rel"], (e["o"], e["o_type"])))
        elif (e["o"], e["o_type"]) == key:
            out.append((f"^{e['rel']}", (e["s"], e["s_type"])))
    return out  # ponytail: 타입까지 키로. 이름만 맞추면 수원(지역)이 수원(기관)으로 샌다


def find_anchor(client, cfg, g, q):
    names = sorted({n["name"] for n in g["nodes"]}, key=len, reverse=True)
    hit = next((n for n in names if n and n in q), "")
    if not hit:
        out = client.chat.completions.create(
            model=cfg["model"], temperature=0,
            messages=[{"role": "system",
                       "content": f"질문에 나오는 고유명을 아래 목록에서 하나만 골라 그대로 적어라. 없으면 '없음'.\n{names}"},
                      {"role": "user", "content": q}]).choices[0].message.content.strip()
        hit = "" if out == "없음" else norm(out, cfg)
    if not hit:
        return None
    cands = [(n["name"], n["type"]) for n in g["nodes"] if n["name"] == hit]
    deg = {}
    for e in g["edges"]:
        deg[(e["s"], e["s_type"])] = deg.get((e["s"], e["s_type"]), 0) + 1
        deg[(e["o"], e["o_type"])] = deg.get((e["o"], e["o_type"]), 0) + 1
    return max(cands, key=lambda k: deg.get(k, 0))  # 동명이인은 연결이 많은 쪽


def expand(g, cfg, anchor):
    deg = {}
    for e in g["edges"]:
        deg[(e["s"], e["s_type"])] = deg.get((e["s"], e["s_type"]), 0) + 1
        deg[(e["o"], e["o_type"])] = deg.get((e["o"], e["o_type"]), 0) + 1
    hubs = {k for k, d in deg.items() if d >= cfg["hub_min_degree"]}
    paths, frontier = [], [(anchor, [])]
    for _ in range(cfg["max_hops"]):
        nxt = []
        for cur, p in frontier:
            for rel, nb in neighbors(g, cur):
                np = p + [(cur, rel, nb)]
                paths.append(np)
                if nb not in hubs and len(np) < cfg["max_hops"]:
                    nxt.append((nb, np))  # ponytail: 허브(서울특별시급)는 종점으로만. 중간에 두면 어디서든 이어져 경로가 무의미해진다
        frontier = nxt
    return paths, hubs


def ev_for(g, path):
    ev = []
    for s, rel, o in path:
        r = rel[1:] if rel.startswith("^") else rel
        fwd = not rel.startswith("^")
        for e in g["edges"]:
            same = (e["s"], e["s_type"]) == s and (e["o"], e["o_type"]) == o
            if e["rel"] == r and (same if fwd else
                                  (e["s"], e["s_type"]) == o and (e["o"], e["o_type"]) == s):
                ev.append(e)
                break
    return ev


def show(step):
    (s, st), rel, (o, ot) = step
    return f"{s}[{st}] -{rel}→ {o}[{ot}]"


def build(cfg):
    load_key()
    g, client = read_graph(), OpenAI()

    def anchor(s: S):
        return {"anchor": find_anchor(client, cfg, g, s["question"])}

    def expand_n(s: S):
        if not s["anchor"]:
            return {"paths": []}
        paths, _ = expand(g, cfg, s["anchor"])
        return {"paths": paths}

    def answer(s: S):
        if not s["paths"]:
            return {"answer": "모르겠습니다. 그래프에서 연결된 근거를 찾지 못했습니다.",
                    "refused": True}
        triples = [t for p in s["paths"][:12] for t in ev_for(g, p)]
        seen, ev = set(), []
        for t in triples:  # 같은 간선 중복 제거
            k = (t["s"], t["rel"], t["o"], t["doc"])
            if k not in seen:
                seen.add(k)
                ev.append(t)
        pros = "\n".join(f"- {t['s']} {t['rel']} {t['o']} ({t['doc']}: {t['quote']})" for t in ev)
        out = client.chat.completions.create(
            model=cfg["model"], temperature=0,
            messages=[{"role": "system",
                       "content": "근거로만 한두 문장 한국어 답을 쓰라. 관계명( BY_AGENCY 같은 영어)은 쓰지 말고 "
                                  "뜻을 풀어라(예: 국토교통부가 맡은). 끝에 근거 문서번호를 (d0010)처럼 붙여라. "
                                  "근거에 답이 없으면 '모르겠습니다'라고만 말하라."},
                      {"role": "user", "content": f"질문: {s['question']}\n근거:\n{pros}"}]
            ).choices[0].message.content.strip()
        if "모르겠습니다" in out:  # ponytail: 거절은 정형문 하나. 모델이 덧붙인 인용·여담을 잘라 지표가 흔들리지 않게 한다
            return {"answer": "모르겠습니다. 그래프에서 연결된 근거를 찾지 못했습니다.",
                    "refused": True}
        return {"answer": out, "refused": False}

    wf = StateGraph(S)
    for n, f in (("anchor", anchor), ("expand", expand_n), ("answer", answer)):
        wf.add_node(n, f)
    wf.add_edge(START, "anchor")
    wf.add_edge("anchor", "expand")
    wf.add_edge("expand", "answer")
    wf.add_edge("answer", END)
    return wf.compile(), g


def ask(question):
    cfg = read_config()
    app, g = build(cfg)
    r = app.invoke({"question": question, "anchor": None, "paths": [],
                    "answer": "", "refused": False})
    docs = {d["id"]: d for d in read_docs()}
    seen_src, sources = set(), []
    for p in r["paths"][:12]:
        for t in ev_for(g, p):
            if t["doc"] not in seen_src:
                seen_src.add(t["doc"])
                sources.append({"id": t["doc"], "title": docs[t["doc"]]["title"],
                                "url": docs[t["doc"]]["url"]})
    return {"question": question, "anchor": list(r["anchor"]) if r["anchor"] else None,
            "paths": [[[s, st, rel, o, ot] for (s, st), rel, (o, ot) in p]
                      for p in r["paths"][:12]],
            "answer": r["answer"], "refused": r["refused"],
            "sources": sources}


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "GTX-C노선과 같은 지역에 있는 다른 사업은?"
    r = ask(q)
    print(f"시작: {r['anchor']}\n답: {r['answer']}\n경로 {len(r['paths'])}개:")
    for p in r["paths"][:6]:
        print("  " + " → ".join(show(((s, st), rel, (o, ot)))
                                 for s, st, rel, o, ot in p))
    assert r["paths"] or r["refused"]  # ponytail: 경로 없이 답만 나오는 실패를 막는 최소 검사
