"""이슈 CSV → 개발 진행 지표. 숫자는 전부 여기서 계산하고, AI는 이 결과만 보고 글을 쓴다."""
import csv
import io
from datetime import date, timedelta

DONE = {"done", "closed", "resolved", "완료"}
BLOCKED = {"blocked", "막힘"}

# Jira 영문 내보내기 열 이름도 받는다
ALIASES = {
    "issue key": "key", "summary": "summary", "issue type": "type", "status": "status",
    "assignee": "assignee", "created": "created", "start date": "start", "due date": "due",
    "resolved": "resolved", "story points": "points", "component": "stage", "components": "stage",
    "blocked by": "blocked_by", "severity": "severity",
}
REQUIRED = ("key", "summary", "type", "status")


def _d(v):
    v = (v or "").strip()[:10].replace("/", "-").replace(".", "-")
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        return None


def load(text):
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    if not rows:
        raise ValueError("CSV에 이슈가 없습니다.")
    issues = []
    for r in rows:
        r = {ALIASES.get(k.strip().lower(), k.strip().lower()): (v or "").strip() for k, v in r.items() if k}
        missing = [c for c in REQUIRED if c not in r]
        if missing:
            raise ValueError(f"필수 열이 없습니다: {', '.join(missing)}")
        issues.append({
            "key": r["key"], "summary": r["summary"], "type": r["type"].lower(),
            "stage": r.get("stage") or "미분류", "status": r["status"], "assignee": r.get("assignee", ""),
            "created": _d(r.get("created")), "start": _d(r.get("start")), "due": _d(r.get("due")),
            "resolved": _d(r.get("resolved")),
            "points": float(r["points"]) if r.get("points") else 0.0,
            "blocked_by": [b.strip() for b in (r.get("blocked_by") or "").replace(";", ",").split(",") if b.strip()],
            "severity": (r.get("severity") or "").upper(), "rework": int(r["rework"]) if r.get("rework") else 0,
        })
    return issues


def _done(i, as_of):
    return i["status"].lower() in DONE and (i["resolved"] is None or i["resolved"] <= as_of)


def analyze(issues, as_of, milestone=None, milestone_name="마일스톤"):
    tasks = [i for i in issues if i["type"] != "bug"]
    bugs = [i for i in issues if i["type"] == "bug"]
    by_key = {i["key"]: i for i in issues}
    week_start = as_of - timedelta(days=6)

    done = [t for t in tasks if _done(t, as_of)]
    pts_total = sum(t["points"] for t in tasks)
    pts_done = sum(t["points"] for t in done)

    # 단계별 진행 (CSV에 나온 순서 유지)
    stages = []
    for st in dict.fromkeys(t["stage"] for t in tasks):
        ts = [t for t in tasks if t["stage"] == st]
        d = [t for t in ts if _done(t, as_of)]
        stages.append({"stage": st, "done": len(d), "total": len(ts),
                       "pct": round(100 * len(d) / len(ts)) if ts else 0})

    overdue = [t for t in tasks if t["due"] and t["due"] < as_of and not _done(t, as_of)]
    due_today = [t for t in tasks if t["due"] == as_of and not _done(t, as_of)]

    # 막힌 작업: 상태가 Blocked이거나, 선행 작업이 아직 안 끝난 상태에서 시작일이 지난 것
    blocked = []
    for t in tasks:
        if _done(t, as_of):
            continue
        waiting = [b for b in t["blocked_by"] if b in by_key and not _done(by_key[b], as_of)]
        if t["status"].lower() in BLOCKED or (waiting and t["start"] and t["start"] <= as_of + timedelta(days=3)):
            blocked.append({"key": t["key"], "summary": t["summary"], "waiting_on": waiting, "due": t["due"]})

    # 연쇄 영향: 어떤 미완료 작업이 늦어지면 뒤에서 기다리는 작업 수
    def downstream(key, seen=None):
        seen = seen or set()
        for t in tasks:
            if key in t["blocked_by"] and t["key"] not in seen and not _done(t, as_of):
                seen.add(t["key"])
                downstream(t["key"], seen)
        return seen

    # 이번 주 계획 대비 완료 (기한이 이번 주였던 작업 중 끝난 비율)
    planned_week = [t for t in tasks if t["due"] and week_start <= t["due"] <= as_of]
    done_on_plan = [t for t in planned_week if _done(t, as_of)]
    late_done = [t for t in done if t["due"] and t["resolved"] and t["resolved"] > t["due"]]

    open_bugs = [b for b in bugs if not _done(b, as_of)]
    sev = {s: sum(1 for b in open_bugs if b["severity"] == s) for s in ("S1", "S2", "S3", "S4")}
    new_bugs = [b for b in bugs if b["created"] and week_start <= b["created"] <= as_of]
    closed_bugs = [b for b in bugs if b["resolved"] and week_start <= b["resolved"] <= as_of]

    rework = [t for t in tasks if t["rework"] >= 2]

    buffer_days = None
    if milestone:
        open_due = [t["due"] for t in tasks if t["due"] and not _done(t, as_of)]
        buffer_days = (milestone - max(open_due)).days if open_due else None

    risks = []
    for t in overdue:
        dn = downstream(t["key"])
        risks.append({"key": t["key"], "type": "기한 초과", "detail": f"{t['summary']} · {(as_of - t['due']).days}일 지남",
                      "impact": len(dn), "score": 3 + len(dn)})
    for b in blocked:
        dn = downstream(b["key"])
        risks.append({"key": b["key"], "type": "막힘", "detail": f"{b['summary']} · 선행 작업 대기: {', '.join(b['waiting_on']) or '상태 Blocked'}",
                      "impact": len(dn), "score": 2 + len(dn)})
    for t in rework:
        dn = downstream(t["key"])
        risks.append({"key": t["key"], "type": "재작업 반복", "detail": f"{t['summary']} · 재작업 {t['rework']}회 · {t['assignee']}",
                      "impact": len(dn), "score": 2 + len(dn)})
    for b in open_bugs:
        if b["severity"] == "S1":
            risks.append({"key": b["key"], "type": "S1 버그", "detail": b["summary"], "impact": 0, "score": 6})
    risks.sort(key=lambda r: -r["score"])

    k = lambda t: {"key": t["key"], "summary": t["summary"], "due": t["due"].isoformat() if t["due"] else "",
                   "assignee": t["assignee"], "status": t["status"]}
    return {
        "as_of": as_of.isoformat(), "week": f"{week_start.isoformat()} ~ {as_of.isoformat()}",
        "milestone": {"name": milestone_name, "date": milestone.isoformat() if milestone else "", "buffer_days": buffer_days},
        "progress": {"tasks_done": len(done), "tasks_total": len(tasks),
                     "pct": round(100 * len(done) / len(tasks)) if tasks else 0,
                     "points_done": pts_done, "points_total": pts_total,
                     "points_pct": round(100 * pts_done / pts_total) if pts_total else 0},
        "week_plan": {"planned": len(planned_week), "done": len(done_on_plan),
                      "pct": round(100 * len(done_on_plan) / len(planned_week)) if planned_week else None,
                      "missed": [k(t) for t in planned_week if not _done(t, as_of)]},
        "late_done": [k(t) | {"late_days": (t["resolved"] - t["due"]).days} for t in late_done],
        "stages": stages,
        "overdue": [k(t) | {"days": (as_of - t["due"]).days} for t in overdue],
        "due_today": [k(t) for t in due_today],
        "blocked": [b | {"due": b["due"].isoformat() if b["due"] else ""} for b in blocked],
        "bugs": {"open": len(open_bugs), "severity": sev, "new_this_week": len(new_bugs), "closed_this_week": len(closed_bugs),
                 "s1": [k(b) for b in open_bugs if b["severity"] == "S1"]},
        "rework": [k(t) | {"rework": t["rework"]} for t in rework],
        "risks": risks[:5],
        "keys": sorted(by_key),
    }
