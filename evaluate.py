"""홉별 측정 + basic RAG 대조 + 실패 층 분류. 결과 output/eval.json · runs.jsonl"""
import json
import re
from collections import Counter

from openai import OpenAI

from agent import ask
from common import HERE, load_key, read_config, read_docs, read_graph


def ent_hit(answer, entity):
    # ponytail: 부분문자열이 아니라 토큰 포함으로 본다. "목동 신시가지 재건축 사업"은 목동 재건축을 맞힌 것이다
    return all(t in answer for t in re.findall(r"[가-힣A-Z0-9]{2,}", entity))


def directed(step):
    s, st, rel, o, ot = step
    return (o, r_swap(rel), s) if rel.startswith("^") else (s, rel, o)


def r_swap(rel):
    return rel[1:]


def baseline_answer(client, cfg, docs, q):
    toks = set(re.findall(r"[가-힣A-Z0-9]{2,}", q))
    scored = sorted(docs, key=lambda d: len(toks & set(re.findall(r"[가-힣A-Z0-9]{2,}", d["title"] + d["body"][:2000]))), reverse=True)[:3]
    ctx = "\n".join(f"[{d['id']}] {d['title']}: {d['body'][:1200]}" for d in scored)
    out = client.chat.completions.create(
        model=cfg["model"], temperature=0,
        messages=[{"role": "system", "content": "아래 문서로만 한두 문장 답하라. 없으면 '모르겠습니다'라고만."},
                  {"role": "user", "content": f"질문: {q}\n{ctx}"}]).choices[0].message.content.strip()
    return out, [d["id"] for d in scored]


def forb_hit(answer, item):
    # 금지 개체 — 「있어야 할 것」만 보면 «있어서는 안 되는 것»이 섞여도 통과한다.
    # 값은 실측으로만 채운다. 지어내면 통과율만 깎고 아무것도 못 잡는다.
    return [f for f in item.get("forbidden", []) if ent_hit(answer, f)]


def classify(item, r, gtriples):
    if item["refuse_expected"]:
        return ("pass", "-") if r["refused"] else ("fail", "generation")
    exp = {directed(s) for s in item["expected_path"]}
    got = {directed(s) for p in r["paths"] for s in p}
    rec = len(exp & got) / len(exp) if exp else 1.0
    # 필수 개체 «전부» + 금지 개체 «하나도 없음» = 통과 (노드5 요건의 채점 정의)
    ent_ok = all(ent_hit(r["answer"], e) for e in item["expected_entities"])
    if forb_hit(r["answer"], item):
        return ("fail", "generation")  # 경로는 맞아도 답이 오염됐다
    if r["refused"] or not ent_ok:
        if not (exp & got):
            anchored = r.get("anchor") and any(r["anchor"][0] in (a, b) or a in r["anchor"][0] or b in r["anchor"][0] for a, _, b in exp)
            in_graph = exp <= gtriples
            if not anchored:
                return ("fail", "index")  # 시작 개체 자체가 그래프에 없음
            return ("fail", "index") if not in_graph else ("fail", "search")
        return ("fail", "generation")  # 경로는 탔는데 답이 빗나감·거절
    return ("pass", "-")


def main():
    load_key()
    cfg, client = read_config(), OpenAI()
    docs = read_docs()
    g = read_graph()
    gtriples = set()
    for e in g["edges"]:
        gtriples.add((e["s"], e["rel"], e["o"]))
    gold = json.loads((HERE / "data" / "goldenset.json").read_text(encoding="utf-8"))
    rows, runs = [], open(HERE / "output" / "runs.jsonl", "w", encoding="utf-8")
    for item in gold:
        r = ask(item["question"])
        verdict, layer = classify(item, r, gtriples)
        exp = {directed(s) for s in item["expected_path"]}
        got = {directed(s) for p in r["paths"] for s in p}
        b_ans, b_docs = baseline_answer(client, cfg, docs, item["question"])
        b_ok = (("모르겠습니다" in b_ans) == item["refuse_expected"]) \
            and all(ent_hit(b_ans, e) for e in item["expected_entities"]) \
            and not forb_hit(b_ans, item)   # 대조군에도 «같은» 잣대를 쓴다
        rows.append({"id": item["id"], "hops": item["hops"], "verdict": verdict, "layer": layer,
                     "refuse": item["refuse_expected"],
                     "path_recall": round(len(exp & got) / len(exp), 2) if exp else None,
                     "forbidden_hit": forb_hit(r["answer"], item),
                     "baseline_ok": b_ok})
        # ★`paths` 를 같이 남긴다 — 경로 재현율이 «어떤 경로를 타서» 나온 값인지
        #   숫자만으로는 사람이 확인할 수 없다 (요건 ④「탄 경로를 기록」).
        runs.write(json.dumps({"id": item["id"], "answer": r["answer"], "refused": r["refused"],
                               "paths": r["paths"], "baseline": b_ans}, ensure_ascii=False) + "\n")

    # ★거절을 홉 수에 섞지 않는다 — 거절은 경로가 없어 통과가 쉽고(path_recall null),
    #   섞으면 «무엇에 대한 정확도»인지 흐려진다. 정답/거절을 따로 센다.
    def agg(sub):
        return {"n": len(sub),
                "graph_acc": round(sum(r["verdict"] == "pass" for r in sub) / len(sub), 2),
                "baseline_acc": round(sum(r["baseline_ok"] for r in sub) / len(sub), 2)}

    by_kind = {}
    for h in sorted({r["hops"] for r in rows}):
        for refuse, tag in ((False, "정답"), (True, "거절")):
            sub = [r for r in rows if r["hops"] == h and r["refuse"] is refuse]
            if sub:
                by_kind[f"{h}홉-{tag}"] = agg(sub)
    ans_rows = [r for r in rows if not r["refuse"]]
    ref_rows = [r for r in rows if r["refuse"]]
    fails = Counter(f'{r["id"]}:{r["layer"]}' for r in rows if r["verdict"] == "fail")
    out = {"by_kind": by_kind, "fails": dict(fails),
           "items": [{"id": r["id"], "hops": r["hops"], "refuse": r["refuse"],
                      "verdict": r["verdict"], "layer": r["layer"],
                      "path_recall": r["path_recall"],
                      "forbidden_hit": r["forbidden_hit"]} for r in rows],
           "overall": {"n": len(rows), **agg(rows)},
           "overall_정답만": {"n": len(ans_rows), **agg(ans_rows)},
           "overall_거절만": {"n": len(ref_rows), **agg(ref_rows)}}
    (HERE / "output" / "eval.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
