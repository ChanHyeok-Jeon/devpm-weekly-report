"""시연 데이터로 지표를 손으로 센 값과 비교한다."""
from datetime import date

import pytest

from report.metrics import analyze, load
from report.writer import verify

M = analyze(load(open("data/sample_issues.csv", encoding="utf-8").read()), date(2026, 11, 6), date(2026, 11, 27), "알파 빌드")


def test_progress():
    assert (M["progress"]["tasks_done"], M["progress"]["tasks_total"], M["progress"]["pct"]) == (6, 22, 27)


def test_week_plan():
    # 10/31~11/6에 기한이 있던 작업 4개(DEV-131·133·121·132) 중 DEV-131만 완료
    assert (M["week_plan"]["planned"], M["week_plan"]["done"]) == (4, 1)


def test_overdue_and_late():
    assert [t["key"] for t in M["overdue"]] == ["DEV-133"]
    assert M["late_done"][0]["key"] == "DEV-112" and M["late_done"][0]["late_days"] == 3


def test_blocked_and_downstream():
    assert {b["key"] for b in M["blocked"]} == {"DEV-122", "DEV-134"}
    top = M["risks"][0]
    assert top["key"] == "DEV-134" and top["impact"] == 5  # 밸런스 2 + QA 1 + 현지화·공지 2


def test_bugs():
    assert M["bugs"]["severity"] == {"S1": 1, "S2": 2, "S3": 0, "S4": 1}
    assert (M["bugs"]["new_this_week"], M["bugs"]["closed_this_week"]) == (4, 1)


def test_buffer():
    assert M["milestone"]["buffer_days"] == 1


def test_verify_flags_made_up_values():
    v = verify("DEV-999가 지연되어 진척률이 63%입니다 (DEV-134)", M)
    assert v["unknown_keys"] == ["DEV-999"] and "63" in v["unknown_numbers"] and not v["ok"]


def test_missing_columns():
    with pytest.raises(ValueError):
        load("key,summary\nA-1,x\n")


def test_verify_with_korean_particles():
    v = verify("22개 작업 중 6개 완료, 진척률 27%입니다. DEV-134가 막혔고 뒤의 5개 작업이 기다립니다.", M)
    assert v["ok"], v
    v = verify("작업 9개가 남았습니다", M)
    assert "9" in v["unknown_numbers"] or v["ok"]  # 9가 집계에 없으면 잡혀야 한다
