"""집계 결과 → AI 주간 리포트. AI는 숫자를 새로 만들지 않고, 쓴 숫자·이슈 번호는 코드가 다시 확인한다."""
import json
import os
import re

import boto3

MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "apac.amazon.nova-pro-v1:0")
_client = None

SYSTEM = """당신은 게임 개발팀 개발 PM을 돕는 보조입니다. 아래 <집계>는 코드가 이슈 데이터에서 계산한 값입니다.
주간 진행 리포트를 한국어 마크다운으로 쓰세요. 팀원과 리드가 1분 안에 읽을 수 있게 짧게 씁니다.

규칙:
- 숫자, 날짜, 이슈 번호는 <집계>에 있는 것만 쓰세요. 새로 계산하거나 추정하지 마세요.
- 리스크와 제안에는 근거 이슈 번호를 괄호로 붙이세요. 예: (DEV-134)
- risks의 impact는 그 작업이 늦어지면 뒤에서 기다리는 작업 수입니다. 리스크를 설명할 때 함께 쓰세요.
- 결정 기한을 새로 만들지 마세요. 기한이 필요하면 관련 이슈의 due나 마일스톤 날짜를 근거로 쓰세요.
- 누구를 탓하는 표현 없이, 사실과 다음 행동 위주로 쓰세요.
- 존댓말로 쓰세요.

형식:
## 이번 주 요약
- 세 줄 이내
## 리스크 Top 3
1. 리스크 — 영향 — 제안 행동 (근거 이슈)
## 다음 주 우선순위
- 세 개 이내
## 결정이 필요한 사항
- 누가 무엇을 언제까지 정해야 하는지. 없으면 "없음"
"""


def _bedrock():
    global _client
    if _client is None:
        _client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "ap-northeast-2"))
    return _client


def _facts_for_prompt(m):
    m = dict(m)
    m.pop("keys", None)
    return json.dumps(m, ensure_ascii=False, indent=1)


def verify(text, m):
    """리포트 속 이슈 번호와 숫자가 집계에 있는지 확인한다."""
    facts = _facts_for_prompt(m)
    keys = set(m["keys"])
    # 한글 조사가 바로 붙어도("DEV-134가", "6개") 잡히도록 \b 대신 앞뒤 문자를 직접 본다
    unknown_keys = sorted({k for k in re.findall(r"(?<![A-Za-z])[A-Z]{2,10}-\d+(?!\d)", text) if k not in keys})
    nums_in_facts = set(re.findall(r"\d+(?:\.\d+)?", facts))
    # 날짜(2026-11-06, 11/6, 11월 6일)는 집계의 날짜와 맞는지 따로 보지 않고 숫자 단위로 대조한다
    unknown_nums = sorted({n for n in re.findall(r"(?<![A-Za-z0-9.\-])\d+(?:\.\d+)?(?![\d.])", text)
                           if n not in nums_in_facts and n not in {"1", "2", "3"}}, key=lambda x: float(x))
    return {"unknown_keys": unknown_keys, "unknown_numbers": unknown_nums,
            "ok": not unknown_keys and not unknown_nums}


def write_report(m):
    res = _bedrock().converse(
        modelId=MODEL_ID,
        system=[{"text": SYSTEM}],
        messages=[{"role": "user", "content": [{"text": "<집계>\n" + _facts_for_prompt(m) + "\n</집계>"}]}],
        inferenceConfig={"maxTokens": 1200, "temperature": 0.2},
    )
    text = "".join(c.get("text", "") for c in res["output"]["message"]["content"]).strip()
    return {"markdown": text, "check": verify(text, m)}
