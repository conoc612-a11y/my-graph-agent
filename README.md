# 부동산 뉴스 GraphRAG (`my-graph-agent`)

60건 뉴스 → 356노드·319엣지 → n홉 답변+경로. 모델 gpt-4.1-mini, 전체 API 비용 약 $0.5.

## 실행 (Windows)

```bat
python -m venv venv
venv\Scripts\python -m pip install -r requirements.txt
```

키: `keys.env`에 `OPENAI_API_KEY=...` 한 줄. 없으면 환경변수 →
`news collector/my-newsletter/keys.env` → `matjip/keys.env` 순으로 찾는다.

```bat
venv\Scripts\python scripts\collect_corpus.py 96 60   # 코퍼스 (무료)
venv\Scripts\python build_graph.py                    # 추출+정제 → output/graph.json(.graphml)
venv\Scripts\python agent.py "GTX-A노선과 같은 기관이 맡은 다른 노선은?"
venv\Scripts\python evaluate.py                       # 홉별+basic RAG → output/eval.json
venv\Scripts\python -m streamlit run app.py           # 데모 http://localhost:8501
```

자세한 설계·측정·실패 분석은 [REPORT.md](REPORT.md).
공개 배포 시 `keys.env`를 올리지 마세요 (`.gitignore`済).
