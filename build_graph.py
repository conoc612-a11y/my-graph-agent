"""추출 + 정제·병합 → output/graph.json · graph.graphml"""
import json
import xml.etree.ElementTree as ET

from openai import OpenAI
from pydantic import BaseModel

from common import HERE, load_key, norm, read_config, read_docs


class Triple(BaseModel):
    s: str
    s_type: str
    rel: str
    o: str
    o_type: str
    quote: str


class DocGraph(BaseModel):
    triples: list[Triple]


SYS = ("부동산 뉴스에서 지식그래프 삼중항을 뽑는다. 반드시 한국어 고유명만 노드로: "
       "지역·사업(단지·노선·지구)·기관·정책제도·인물. 일반명사·대명사는 금지. "
       "관계는 아래 목록만, 방향을 지켜라. 각 삼중항에 원문 인용 1개를 붙여라.")


def extract(client, cfg, doc):
    rels = "\n".join(f"- {r}: {cfg['relation_desc'][r]}" for r in cfg["relations"])
    out = client.chat.completions.parse(
        model=cfg["model"], temperature=0,
        messages=[{"role": "system", "content": f"{SYS}\n노드: {cfg['node_types']}\n{rels}"},
                  {"role": "user", "content": f"제목: {doc['title']}\n{doc['body'][:3000]}"}],
        response_format=DocGraph).choices[0].message.parsed
    return out.triples


def main():
    load_key()
    cfg = read_config()
    client = OpenAI()
    nodes, edges, n_doc = {}, [], 0
    for doc in read_docs():  # 문서 1건=1회 호출. 끊기면 거기까지 저장하고 죽는다(부분 저장 금지 아님: 아래 덮어쓰기 전까진 옛 파일 유지)
        try:
            triples = extract(client, cfg, doc)
        except Exception as e:
            print(f"추출 실패 {doc['id']}: {type(e).__name__}")
            continue
        n_doc += 1
        for t in triples:
            if t.rel not in cfg["relations"]:
                continue
            if t.s_type not in cfg["node_types"] or t.o_type not in cfg["node_types"]:
                continue
            s, o = norm(t.s, cfg), norm(t.o, cfg)
            if s in cfg["stopwords"] or o in cfg["stopwords"] or s == o:
                continue
            nodes.setdefault((s, t.s_type), {"name": s, "type": t.s_type, "docs": []})
            nodes.setdefault((o, t.o_type), {"name": o, "type": t.o_type, "docs": []})
            nodes[(s, t.s_type)]["docs"].append(doc["id"])
            nodes[(o, t.o_type)]["docs"].append(doc["id"])
            edges.append({"s": s, "s_type": t.s_type, "rel": t.rel,
                          "o": o, "o_type": t.o_type,
                          "doc": doc["id"], "quote": t.quote[:200]})
    for v in nodes.values():  # ponytail: 병합=정확일치+별칭표. 임베딩 병합은 측정이 말할 때만
        v["docs"] = sorted(set(v["docs"]))
    g = {"nodes": list(nodes.values()), "edges": edges}
    (HERE / "output" / "graph.json").write_text(
        json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
    to_graphml(g)
    print(f"추출 {n_doc}건 → 노드 {len(nodes)} · 엣지 {len(edges)}")


def to_graphml(g):
    root = ET.Element("graphml", xmlns="http://graphml.graphdrawing.org/xmlns")
    for k in ("type", "docs"):
        ET.SubElement(root, "key", id=k, **{"for": "node", "attr.name": k, "attr.type": "string"})
    for k in ("rel", "doc", "quote"):
        ET.SubElement(root, "key", id=k, **{"for": "edge", "attr.name": k, "attr.type": "string"})
    gr = ET.SubElement(root, "graph", id="G", edgedefault="directed")
    ids = {n["name"]: f"n{i}" for i, n in enumerate(g["nodes"])}
    for n in g["nodes"]:
        nd = ET.SubElement(gr, "node", id=ids[n["name"]])
        ET.SubElement(nd, "data", key="type").text = n["type"]
        ET.SubElement(nd, "data", key="docs").text = ",".join(n["docs"])
    for e in g["edges"]:
        ed = ET.SubElement(gr, "edge", source=ids[e["s"]], target=ids[e["o"]])
        for k in ("rel", "doc", "quote"):
            ET.SubElement(ed, "data", key=k).text = e[k]
    ET.indent(root)
    ET.ElementTree(root).write(HERE / "output" / "graph.graphml", encoding="utf-8")


if __name__ == "__main__":
    main()
