# 부동산 뉴스 GraphRAG (`my-graph-agent`)

60건 뉴스 → 356노드·319엣지 → n홉 답변+경로. 모델 gpt-4.1-mini, 전체 API 비용 약 $0.5.

## 실행 (Windows)

```bat
python -m venv venv
venv\Scripts\python -m pip install -r requirements.txt
```

키: `keys.env`에 `OPENAI_API_KEY=...` 한 줄. **이것만 있으면 됩니다.**

> 없을 때의 폴백은 환경변수 → `news collector/my-newsletter/keys.env` →
> `matjip/keys.env` 순입니다. 뒤의 둘은 **제 다른 프로젝트 경로**라 남의 PC에는 없습니다 —
> 키를 여러 곳에 두지 않으려고 둔 것이고, **없어도 동작에 지장이 없습니다.**

```bat
venv\Scripts\python scripts\collect_corpus.py 96 60   # 코퍼스 (무료)
venv\Scripts\python build_graph.py                    # 추출+정제 → output/graph.json(.graphml)
venv\Scripts\python agent.py "GTX-A노선과 같은 기관이 맡은 다른 노선은?"
venv\Scripts\python evaluate.py                       # 홉별+basic RAG → output/eval.json
venv\Scripts\python -m streamlit run app.py           # 데모 http://localhost:8501
```

> 첫 실행에 `Email:`이 멈춰 있으면 그냥 Enter (streamlit 환영 프롬프트).
> 바로 넘기려면 `... run app.py --server.headless true`로 띄우고
> 브라우저에 주소를 직접 입력하세요.

자세한 설계·측정·실패 분석은 [REPORT.md](REPORT.md).
공개 배포 시 `keys.env`를 올리지 마세요 (`.gitignore` 에 등록해 뒀습니다).
