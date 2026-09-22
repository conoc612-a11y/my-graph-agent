"""RSS 5곳에서 부동산 뉴스 코퍼스 수집 → data/docs/dXXXX.json (API 비용 0).

재사용: news collector/my-newsletter/graph.py 의 SOURCES·수집 판정 그대로.
72h 창·라운드로빈으로 소스 편중을 막고, 본문 600자 미만은 버린다.
"""
import json
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone

import feedparser
import requests
import trafilatura

HERE = pathlib.Path(__file__).resolve().parent.parent
OUT = HERE / "data" / "docs"
UA = {"User-Agent": "Mozilla/5.0 (graphrag-course)"}
SOURCES = [
    ("하우징헤럴드", "https://www.housingherald.co.kr/rss/allArticle.xml"),
    ("한경부동산", "https://www.hankyung.com/feed/realestate"),
    ("동아경제", "http://rss.donga.com/economy.xml"),
    ("매경", "https://www.mk.co.kr/rss/30000001/"),
    ("연합경제", "https://www.yna.co.kr/rss/economy.xml"),
]
HOURS = int(sys.argv[1]) if len(sys.argv) > 1 else 72
TARGET = int(sys.argv[2]) if len(sys.argv) > 2 else 60
MIN_BODY = 600


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def main():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS)
    OUT.mkdir(parents=True, exist_ok=True)
    seen, per_feed, per_source = set(), {}, {}
    for name, url in SOURCES:  # 한 곳이 죽어도 나머지는 계속. RSS 목록은 가볍게 전부 모은다
        try:
            feed = feedparser.parse(requests.get(url, headers=UA, timeout=20).content)
        except Exception as e:
            print(f"수집 실패 {name}: {type(e).__name__}", flush=True)
            continue
        cands = []
        for e in feed.entries:
            t = e.get("published_parsed") or e.get("updated_parsed")
            at = datetime(*t[:6], tzinfo=timezone.utc) if t else None
            if not at or at < cutoff:
                continue
            key = e.link.split("?")[0].rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            title = re.sub(r"\s*-\s*[^-]+$", "", e.title).strip()
            cands.append({"title": title or e.title, "url": e.link,
                          "source": name, "published": at.isoformat()})
        per_feed[name] = cands
    items = []  # 무거운 본문 fetch만 라운드로빈: 연합 쏠림·한경 독식을 막는다
    order = [n for n in (n for n, _ in SOURCES) if n in per_feed]
    for i in range(max((len(v) for v in per_feed.values()), default=0)):
        for name in order:
            if len(items) >= TARGET or i >= len(per_feed[name]):
                continue
            meta = per_feed[name][i]
            try:
                dl = trafilatura.fetch_url(meta["url"])
                body = trafilatura.extract(dl) if dl else None
            except Exception:
                body = None
            if not body or len(body) < MIN_BODY:
                continue
            meta["body"] = body
            items.append(meta)
            per_source[name] = per_source.get(name, 0) + 1
            if len(items) >= TARGET:
                break
        if len(items) >= TARGET:
            break
    for i, it in enumerate(items):  # ponytail: 파일 1건=문서 1건, DB 없이 그대로 골든셋·추출 입력
        it["id"] = f"d{i+1:04d}"
        (OUT / f"{it['id']}.json").write_text(
            json.dumps(it, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"수집 {len(items)}건 ({', '.join(f'{k} {v}' for k, v in per_source.items())})")


if __name__ == "__main__":
    main()
