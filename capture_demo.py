"""데모 화면 캡처 — 헤드리스 크롬 + CDP. 결과 docs/demo_answer.png · docs/demo_refuse.png

  venv\\Scripts\\python -m streamlit run app.py --server.port 8511 --server.headless true
  venv\\Scripts\\python capture_demo.py

★왜 스크립트로 만들었나
  ① 손으로 찍으면 탭·북마크바가 같이 찍힌다. 공개 저장소에 올리는 이미지라 안 된다.
  ② ★«다시 찍기» 가 한 줄이 된다. 화면 문구를 고쳤는데 캡처에 옛 문구가 남는 일을 막는다.

⛔ `chrome --screenshot --virtual-time-budget` 으로는 안 된다 — 가상 시간이라
   **LLM 호출의 실제 네트워크 대기를 건너뛴다.** 「그래프를 타는 중…」 스피너가 찍힌다.
   그래서 **결과가 나올 때까지 «본다»**(폴링). 고정 sleep 도 쓰지 않는다 —
   호출 시간이 매번 달라 짧게 잡으면 빈 화면을 찍는다.
"""
import asyncio
import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request

import websockets

PORT = 8511
CDP_PORT = 9222
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
# ★기다릴 문구는 «화면의 맨 뒤»에 나오는 것으로 잡는다.
#   「탄 경로」(제목)로 잡았더니 제목만 뜬 채 pyvis 망·경로 목록이 «빈 상태»로 찍혔다.
#   실제 목록의 첫 줄(「경로 1:」)까지 기다려야 앞의 것이 다 그려져 있다.
# ★거절은 문구를 «여러 개» 본다 — 정형문이 고정돼 있지 않기 때문이다(REPORT §3 g10).
#   `agent.py` 는 모델이 「모르겠습니다」를 썼을 때만 정형문으로 갈아 끼우는데,
#   모델이 「정보는 없습니다」로 답하는 회차가 있다. 캡처가 그것 때문에 한 번 죽었다.
SHOTS = [
    ("demo_answer.png", "GTX-A노선과 같은 기관이 맡은 다른 노선은?", ["경로 1:"]),
    ("demo_refuse.png", "부산 해운대구 재건축 사업의 시행사는?",
     ["모르겠습니다", "찾지 못했습니다", "없습니다"]),
]
HERE = os.path.dirname(os.path.abspath(__file__))


async def shot(ws_url, url, out, wait_any, timeout=120):
    async with websockets.connect(ws_url, max_size=None) as ws:
        n = 0

        async def cmd(method, **params):
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, "method": method, "params": params}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == n:
                    return msg.get("result", {})

        await cmd("Page.enable")
        await cmd("Emulation.setDeviceMetricsOverride",
                  width=1280, height=1700, deviceScaleFactor=1, mobile=False)
        await cmd("Page.navigate", url=url)
        # ★결과가 뜰 때까지 «본다». 스피너가 찍히는 것을 막는 유일한 방법이다.
        t0 = time.time()
        while time.time() - t0 < timeout:
            r = await cmd("Runtime.evaluate",
                          expression="document.body.innerText", returnByValue=True)
            text = r.get("result", {}).get("value") or ""
            hit = next((w for w in wait_any if w in text), None)
            if hit:
                break
            await asyncio.sleep(1)
        else:
            raise SystemExit(f"⛔ {timeout}초 안에 {wait_any} 중 아무것도 안 떴다 — {out}")
        # ★그래프 망은 pyvis 가 «iframe» 에 그린다 — 본문 텍스트가 다 떠도 아직 비어 있다.
        #   물리 시뮬레이션이 자리를 잡을 때까지 더 기다린다(실측: 2초로는 빈 상자가 찍혔다).
        await asyncio.sleep(8)
        r = await cmd("Page.captureScreenshot", format="png", captureBeyondViewport=True)
        path = os.path.join(HERE, "docs", out)
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["data"]))
        print(f"  ✔ docs/{out}  ({os.path.getsize(path):,} bytes)  «{hit}» 확인 후 촬영")


def main():
    os.makedirs(os.path.join(HERE, "docs"), exist_ok=True)
    prof = tempfile.mkdtemp(prefix="cap_")   # ★빈 프로필 — 북마크·확장·줌이 «없는» 곳에서 연다
    p = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
         f"--remote-debugging-port={CDP_PORT}", f"--user-data-dir={prof}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(30):
            try:
                tabs = json.loads(urllib.request.urlopen(
                    f"http://127.0.0.1:{CDP_PORT}/json", timeout=1).read())
                ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise SystemExit("⛔ 크롬 CDP 에 못 붙었다")
        for out, q, wait_any in SHOTS:
            url = f"http://localhost:{PORT}/?q={urllib.parse.quote(q)}"
            asyncio.run(shot(ws_url, url, out, wait_any))
    finally:
        p.terminate()
        p.wait(timeout=10)
        shutil.rmtree(prof, ignore_errors=True)


if __name__ == "__main__":
    main()
