# AI 운영 리포트 가드레일

이 문서는 TokyoGridEMS의 일일 AI 운영 리포트가 어떻게 근거 없는 해설을 피하고, 운영자가 신뢰할 수 있는 형태로 생성되는지 설명합니다.

리포트 생성기는 자유 대화형 챗봇이 아닙니다. Python이 사실과 지표를 계산하고, OpenAI가 해설을 작성하며, deterministic merge layer가 최종 JSON을 검증한 뒤 대시보드에 표시하는 운영 리포팅 파이프라인입니다.

언어: [English](../en/ai-report-guardrails.md) · [日本語](../ja/ai-report-guardrails.md)

---

## 하드코딩인가?

아닙니다. 현재 구현은 특정 날짜, 예측값, 원인, 개선 결론을 고정해서 넣는 방식이 아닙니다.

다만 deterministic guardrail은 사용합니다. 즉 지표 용어, 근거 품질, 추천 대상, 요약 정합성에 대해서는 고정 규칙을 둡니다. 실제 수치와 판단은 여전히 daily report, diagnostics, calibration snapshot, actual, forecast, metrics JSON에서 계산됩니다.

구분하면 다음과 같습니다.

| 좋지 않은 하드코딩 | 현재 구조 |
|---|---|
| “항상 warm-day bias 때문에 실패했다고 말해라.” | 입력 근거가 있을 때만 해당 feature/guard를 언급합니다. |
| “항상 600MW freeze gap을 넣어라.” | serving line과 recalculated line의 gap이 실제로 있을 때만 freeze를 설명합니다. |
| “항상 자체 모델이 좋아 보이게 써라.” | MAE/WAPE/RMSE 사실을 기준으로 TEPCO 대비 성능을 요약합니다. |
| “OpenAI가 지표를 마음대로 판단하게 둬라.” | Python이 지표를 계산하고 OpenAI는 설명만 작성합니다. |

따라서 deterministic한 부분은 예측이나 진단을 속이는 하드코딩이 아니라, 리포트 출력 계약에 가깝습니다.

---

## 파이프라인

```text
일간 지표 / 진단 / 보정 메타데이터
  -> compact FactPacket
  -> OpenAI 영어 master analysis
  -> 한국어/일본어 현지화
  -> deterministic merge and validation
  -> reports/ai/daily/{ko,en,ja}/YYYY-MM-DD.json
  -> 운영 리포트 탭
```

OpenAI는 자연어 해설 레이어를 만듭니다. 최종 사실 판단의 소유자는 아닙니다.

최종 리포트는 Python 검증 단계를 통과하며, 계산된 근거와 충돌하는 문구는 교정되거나 제거됩니다.

---

## 역할 분담

| 레이어 | 역할 |
|---|---|
| Python fact builder | MAE, WAPE, RMSE, 최대 오차, 커버리지, time-band bias, freeze gap, calibration facts를 계산합니다. |
| OpenAI master analysis | fact packet을 읽고 운영자가 이해하기 쉬운 해설을 작성합니다. |
| Localization step | 영어 master를 한국어/일본어로 옮기되 숫자와 구조를 보존합니다. |
| Merge/guardrail layer | 근거 없는 주장 제거, 용어 교정, 추천 대상 검증, 출력 정합성 강제를 수행합니다. |
| React UI | 브라우저에서 OpenAI를 호출하지 않고 검증된 JSON만 표시합니다. |

---

## deterministic 가드레일

| 가드레일 | 목적 |
|---|---|
| 지표 용어 교정 | 현재 프로젝트의 공식 백분율 오차 지표는 WAPE이므로 MAPE로 잘못 표현하지 않게 합니다. |
| TEPCO 용어 교정 | TEPCO 값은 외부 forecast/reference이며, 이 프로젝트의 모델처럼 표현하지 않습니다. |
| 부호 검증 | positive error는 과대예측, negative error는 과소예측입니다. 이 규칙과 충돌하는 가설은 제거합니다. |
| 근거 필터링 | 가설은 실제 miss, diagnostics, calibration, freeze metadata 중 하나 이상의 구체적 근거를 가져야 합니다. |
| 커버리지 분리 | 확정 actual coverage와 intraday calibration snapshot coverage를 섞어 말하지 않게 합니다. |
| freeze-gap 검증 | serving-vs-recalculated gap이 실제로 있을 때만 forecast freeze를 언급합니다. |
| 추천 대상 whitelist | 개선 후보는 실제 존재하는 feature나 운영 guard를 대상으로만 허용합니다. |
| 추천-가설 연결 | 추천 항목은 유효한 root-cause hypothesis와 연결되어야 합니다. |
| `autoApply: false` | AI 추천은 검토/백테스트 후보이며 자동 적용 대상이 아닙니다. |

---

## OpenAI가 여전히 담당하는 부분

가드레일이 있다고 해서 OpenAI의 가치가 사라지는 것은 아닙니다. OpenAI는 여전히 다음 역할을 합니다.

- 지표와 shape risk를 사람이 읽기 쉬운 문장으로 설명합니다.
- 주요 오차를 lag, weather, calendar, calibration 관점의 가설로 연결합니다.
- 한국어/영어/일본어 운영 요약을 작성합니다.
- 숫자 진단을 실험 티켓 형태의 개선 후보로 바꿉니다.
- evidence를 `confirmed`, `partial`, `not_observed`로 사람이 이해하기 쉽게 표현합니다.

목표는 리포트를 기계적으로 만드는 것이 아니라, OpenAI가 근거의 울타리 안에서만 말하게 만드는 것입니다.

---

## 품질 기준

좋은 운영 리포트는 다음 조건을 만족해야 합니다.

- 일간 성능 우세 판단이 MAE/WAPE 사실과 일치합니다.
- WAPE를 MAPE로 부르지 않습니다.
- TEPCO를 외부 forecast/reference로 표현합니다.
- 확정 actual coverage와 calibration snapshot coverage를 분리해서 설명합니다.
- 각 root-cause hypothesis는 구체적 근거를 갖습니다.
- 각 root-cause hypothesis는 원인 메커니즘과 다음 확인 포인트를 명시합니다.
- freeze 정책 설명은 실제 freeze gap이 있을 때만 등장합니다.
- 개선 후보는 실제 feature 또는 post-processing layer를 대상으로 합니다.
- 개선 후보는 단순 검토 문구가 아니라 검증 구간, threshold, guard, replay 대상을 포함합니다.
- 추천은 자동 적용이 아니라 review/backtest 후보로 남습니다.
- 한국어/일본어 리포트가 영어 master의 숫자와 논리를 바꾸지 않습니다.

---

## 유지보수 체크리스트

모델 feature, post-processing guard, report field를 추가하거나 이름을 바꿀 때는 다음을 확인합니다.

1. AI report feature catalog에 추가합니다.
2. OpenAI가 다른 이름으로 부를 가능성이 있으면 alias를 추가합니다.
3. 실제 튜닝 대상일 때만 recommendation whitelist에 추가합니다.
4. hypothesis filtering과 recommendation linking 테스트를 갱신합니다.
5. AI report 단위 테스트를 실행합니다.
6. 공개 전 최신 1일 리포트를 로컬에서 생성해 확인합니다.

권장 테스트:

```powershell
py -3 -m pytest tests\test_ai_daily_report.py -q
py -3 -m pytest -q
```

최신 1일 리포트 smoke test:

```powershell
$env:OPENAI_DAILY_REPORT_MODEL='gpt-4o-mini'
$env:OPENAI_DAILY_REPORT_LOCALIZATION_MODEL='gpt-4o-mini'
py -3 python\eval\ai_daily_report.py --public-dir web\public --out-dir tmp_ai_report_check --max-days 1 --languages ko,en,ja --use-openai --overwrite-existing --openai-max-calls 3
```

생성된 JSON과 UI를 확인한 뒤 `tmp_ai_report_check`는 삭제합니다.

---

## 운영상 trade-off

현재 구조는 의도적으로 보수적입니다. 그래서 리포트가 완전히 자유로운 문장보다 조금 더 정형적으로 보일 수 있습니다. 대신 근거 없는 멋진 해설이 공개되는 위험을 줄입니다.

전력 수요 예측 대시보드에서는 이 trade-off가 적절합니다. 리포트는 읽기 쉬워야 하지만, 숫자와 주장은 추적 가능해야 하기 때문입니다.
