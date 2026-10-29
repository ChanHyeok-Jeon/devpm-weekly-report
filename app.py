"""개발 진행 주간 리포트 API. 집계는 코드가, 글은 AI가, 확인은 다시 코드가 한다."""
import os
import time
from collections import defaultdict, deque
from datetime import date
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from report.metrics import analyze, load
from report.writer import write_report

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(BASE_DIR, "data", "sample_issues.csv")
app = FastAPI(title="개발 진행 주간 리포트 AI")
_calls = defaultdict(deque)


def _rate_limit(request: Request, limit=20, window=3600):
    ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "")
    q, now = _calls[ip], time.time()
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "잠시 후 다시 시도해 주세요.")
    q.append(now)


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE_DIR, "web", "index.html"))


@app.get("/api/sample.csv")
def sample():
    return PlainTextResponse(open(SAMPLE, encoding="utf-8").read(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=sample_issues.csv"})


@app.post("/api/analyze")
async def run(request: Request, as_of: str = Form(...), milestone: str = Form(""), milestone_name: str = Form("마일스톤"),
              use_sample: bool = Form(False), with_report: bool = Form(True), file: Optional[UploadFile] = File(None)):
    try:
        if use_sample or file is None:
            text = open(SAMPLE, encoding="utf-8").read()
        else:
            raw = await file.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("CSV는 2MB까지 올릴 수 있습니다.")
            text = raw.decode("utf-8-sig", errors="ignore")
        m = analyze(load(text), date.fromisoformat(as_of),
                    date.fromisoformat(milestone) if milestone else None, milestone_name or "마일스톤")
    except ValueError as e:
        raise HTTPException(400, str(e))
    out = {"metrics": m, "report": None}
    if with_report:
        _rate_limit(request)
        out["report"] = write_report(m)
    return out


@app.get("/health")
def health():
    return {"status": "ok"}
