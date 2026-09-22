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


def classify(item, r, gtriples):
    if item["refuse_expected"]:
        return ("pass", "-") if r["refused"] else ("fail", "generation")
    exp = {directed(s) for s in item["expected_path"]}
    got = {directed(s) for p in r["paths"] for s in p}
    rec = len(exp & got) / len(exp) if exp else 1.0
    ent_ok = all(ent_hit(r["answer"], e) for e in item["expected_entities"])
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
        b_ok = (("모르겠습니다" in b_ans) == item["refuse_expected"]) and all(ent_hit(b_ans, e) for e in item["expected_entities"])
        rows.append({"id": item["id"], "hops": item["hops"], "verdict": verdict, "layer": layer,
                     "path_recall": round(len(exp & got) / len(exp), 2) if exp else None,
                     "baseline_ok": b_ok})
        runs.write(json.dumps({"id": item["id"], "answer": r["answer"], "refused": r["refused"],
                               "baseline": b_ans}, ensure_ascii=False) + "\n")
    by_hop = {}
    for h in sorted({r["hops"] for r in rows}):
        sub = [r for r in rows if r["hops"] == h]
        by_hop[str(h)] = {"n": len(sub),
                          "graph_acc": round(sum(r["verdict"] == "pass" for r in sub) / len(sub), 2),
                          "baseline_acc": round(sum(r["baseline_ok"] for r in sub) / len(sub), 2)}
    fails = Counter(f'{r["id"]}:{r["layer"]}' for r in rows if r["verdict"] == "fail")
    out = {"by_hop": by_hop, "fails": dict(fails),
           "items": [{"id": r["id"], "hops": r["hops"], "verdict": r["verdict"],
                      "layer": r["layer"], "path_recall": r["path_recall"]} for r in rows],
           "overall": {"n": len(rows),
                       "graph_acc": round(sum(r["verdict"] == "pass" for r in rows) / len(rows), 2),
                       "baseline_acc": round(sum(r["baseline_ok"] for r in rows) / len(rows), 2)}}
    (HERE / "output" / "eval.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
