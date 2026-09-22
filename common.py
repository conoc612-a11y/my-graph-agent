"""공용: 키 로딩·코퍼스·그래프 입출력. (3파일이 함께 쓰니 분리한 유일한 예외)"""
import json
import os
import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def load_key():
    from openai import OpenAI  # ponytail: 죽은 키를 먼저 잡으면 뒤의 살은 키에 못 간다 — 1회 대조로 통과한 키만 쓴다
    cands = []
    if os.environ.get("OPENAI_API_KEY"):
        cands.append(os.environ["OPENAI_API_KEY"])
    for p in (HERE / "keys.env",
              HERE.parent / "news collector" / "my-newsletter" / "keys.env",
              HERE.parent / "matjip" / "keys.env"):
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.startswith("OPENAI_API_KEY=") and len(line) > 15:
                    cands.append(line.split("=", 1)[1].strip())
    for k in dict.fromkeys(cands):
        os.environ["OPENAI_API_KEY"] = k
        try:
            OpenAI().models.list()
            return
        except Exception:
            continue
    raise SystemExit("쓸 수 있는 OPENAI_API_KEY 없음: 새 키를 my-graph-agent/keys.env에 넣어주세요")


def read_config():
    return json.loads((HERE / "config.json").read_text(encoding="utf-8"))


def read_docs():
    out = []
    for f in sorted((HERE / "data" / "docs").glob("*.json")):
        out.append(json.loads(f.read_text(encoding="utf-8")))
    return out


def read_graph():
    return json.loads((HERE / "output" / "graph.json").read_text(encoding="utf-8"))


def norm(name, cfg):
    n = " ".join(name.strip().split())
    return cfg["aliases"].get(n, n)
