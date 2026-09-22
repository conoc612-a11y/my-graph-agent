"""웹 데모: 질문 → 답변 + 탄 경로·근거 삼중항·출처 문서. 실행: streamlit run app.py"""
import streamlit as st

from agent import ask, ev_for
from common import read_docs, read_graph

st.set_page_config(page_title="부동산 뉴스 GraphRAG", layout="wide")
st.title("부동산 뉴스 GraphRAG 데모")
st.caption("60건 RSS 코퍼스 → 356노드·319엣지. 경로는 실제로 탄 것만, 근거 없으면 거절합니다.")

G = read_graph()
DOCS = {d["id"]: d for d in read_docs()}
gold = {g["question"] for g in __import__("json").loads(
    open("data/goldenset.json", encoding="utf-8").read())}

q = st.text_input("질문", "GTX-A노선과 같은 기관이 맡은 다른 노선은?")
samples = ["GTX-A노선과 같은 기관이 맡은 다른 노선은?",
           "경기 고양시에 있는 개발사업은?",
           "부산 해운대구 재건축 사업의 시행사는?"]
for c, s in zip(st.columns(3), samples):
    if c.button(s, key=s):
        q = s

if st.button("물어보기", type="primary") and q:
    with st.spinner("그래프를 타는 중…"):
        r = ask(q)
    if r["refused"]:
        st.warning(r["answer"])
    else:
        st.success(r["answer"])
    st.subheader(f"탄 경로 {len(r['paths'])}개 (시작: {r['anchor']})")
    for i, p in enumerate(r["paths"][:12]):
        steps = " → ".join(f"{s} -{rel}→ {o}" for s, _, rel, o, _ in p)
        with st.expander(f"경로 {i+1}: {steps}"):
            for t in ev_for(G, [((s, st), rel, (o, ot)) for s, st, rel, o, ot in p]):
                d = DOCS[t["doc"]]
                st.markdown(f"- `{t['s']} {t['rel']} {t['o']}` — {t['doc']}: “{t['quote']}”")
                st.markdown(f"  출처: [{d['title']}]({d['url']}) · {d['source']}")
