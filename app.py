"""웹 데모: 질문 → 답변 + 탄 경로·근거 삼중항·출처 문서 + 그래프 망. 실행: streamlit run app.py"""
import tempfile

import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network

from agent import ask, ev_for, neighbors
from common import read_config, read_docs, read_graph

COLORS = {"Region": "#4dabf7", "Project": "#ffa94d", "Agency": "#69db7c",
          "Policy": "#e599f7", "Person": "#ff8787"}


def key(nm, typ):
    return f"{nm}|{typ}"


def draw_net(center, g, hot):
    """질문 주변 부분망만. 전체 356개는 털뭉치라 의미 없음. 탄 경로는 빨강."""
    cfg = read_config()
    seen, nodes, edges = {center}, [center], []
    frontier = [center]
    for _ in range(cfg["max_hops"]):
        nxt = []
        for cur in frontier:
            for rel, nb in neighbors(g, cur):
                edges.append((cur, rel, nb))
                if nb not in seen and len(seen) < 60:
                    seen.add(nb)
                    nodes.append(nb)
                    nxt.append(nb)
        frontier = nxt
    net = Network(height="550px", width="100%", directed=True)
    for name, typ in nodes:
        net.add_node(key(name, typ), label=name, title=typ,
                     color=COLORS.get(typ, "#ccc"),
                     size=25 if (name, typ) == center else 15)
    hot = {tuple(x) for p in hot for x in p}
    for (s, st), rel, (o, ot) in edges:
        on_path = (s, st, rel, o, ot) in hot
        net.add_edge(key(s, st), key(o, ot), label=rel.lstrip("^"),
                     color="#ff8787" if on_path else "#aaa",
                     width=3 if on_path else 1)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        net.save_graph(f.name)
        return f.name

st.set_page_config(page_title="부동산 뉴스 GraphRAG", layout="wide")
st.title("부동산 뉴스 GraphRAG 데모")
st.caption("60건 RSS 코퍼스 → 356노드·319엣지. 경로는 실제로 탄 것만, 근거 없으면 거절합니다.")

G = read_graph()
DOCS = {d["id"]: d for d in read_docs()}
gold = {g["question"] for g in __import__("json").loads(
    open("data/goldenset.json", encoding="utf-8").read())}

# ★`?q=질문` 으로도 물을 수 있다 — 결과 화면을 «링크 하나로» 건넬 수 있고,
#   캡처 스크립트(docs/capture)가 클릭 없이 이 경로로 찍는다.
_qp = st.query_params.get("q", "")
q = st.text_input("질문", _qp or "GTX-A노선과 같은 기관이 맡은 다른 노선은?")
samples = ["GTX-A노선과 같은 기관이 맡은 다른 노선은?",
           "경기 고양시에 있는 개발사업은?",
           "부산 해운대구 재건축 사업의 시행사는?"]
for c, s in zip(st.columns(3), samples):
    if c.button(s, key=s):
        q = s

if (st.button("물어보기", type="primary") or _qp) and q:
    with st.spinner("그래프를 타는 중…"):
        r = ask(q)
    if r["refused"]:
        st.warning(r["answer"])
    else:
        st.success(r["answer"])
    if r["anchor"]:
        st.subheader("그래프 망 (빨강=탄 경로, 드래그 가능)")
        html = draw_net(tuple(r["anchor"]), G, r["paths"][:12])
        components.html(open(html, encoding="utf-8").read(), height=580)
    st.subheader(f"탄 경로 {len(r['paths'])}개 (시작: {r['anchor']})")
    for i, p in enumerate(r["paths"][:12]):
        steps = " → ".join(f"{s} -{rel}→ {o}" for s, _, rel, o, _ in p)
        with st.expander(f"경로 {i+1}: {steps}"):
            for t in ev_for(G, [((s, st), rel, (o, ot)) for s, st, rel, o, ot in p]):
                d = DOCS[t["doc"]]
                st.markdown(f"- `{t['s']} {t['rel']} {t['o']}` — {t['doc']}: “{t['quote']}”")
                st.markdown(f"  출처: [{d['title']}]({d['url']}) · {d['source']}")
