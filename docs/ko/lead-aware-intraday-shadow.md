# Lead-Aware Intraday Shadow 연구

[English](../en/lead-aware-intraday-shadow.md) | [日本語](../ja/lead-aware-intraday-shadow.md)

## 결론

2026년 10월 3일 후속 연구는 **PROMOTE L5 TO SHADOW**다. 운영 승격이 아니다. 동결 L2는 비교 challenger로 유지한다. Champion, 공개 예측, serving policy, ETL, scheduler, production 승격 기준은 변경하지 않았다. Jev 및 모델 API 호출도 없다.

[기존 L1/L2/L3 결과](learned-intraday-challenger.md)는 그대로다. 동결 L2는 전체 MAE를 9.01% 개선했지만 closest는 4.88% 악화, 일별 승/패 3/7이며 issue revision도 증가했다. 원본 입력·분할·모델·replay·source-exact 반례를 보존한다.

## 학습 구조

| 후보 | 구조 | 누출 방지 |
|---|---|---|
| L2 reference | Post + 학습한 잔여 오차 | Outer fold별 과거 자료로 별도 재학습 |
| L4 | Post + `sqrt(1+lead/60)` × 정규화 학습 오차 | 기존 46개 + 연속 lead/context 파생 10개 |
| L5 | Post + 학습 weight × L2 correction | Gate 학습에 시간순 OOF correction만 사용 |

L4는 log/sqrt lead, 관측 경로 확보량·지연 및 lead로 정규화한 잔차/path 상호작용을 추가한다. Target은 `(actual-post)/sqrt(1+lead/60)`다. L5의 학습용 label은 `clip((actual-post)/OOF_correction,0,1)`이며 correction이 0이면 weight도 0이다. Gate의 59개 입력은 56개 issue-time 피처와 예측 correction/절댓값/정규화 값이다. 최종 실측은 추론에 들어가지 않는다. 특정 시각이나 120분으로 켜고 끄는 규칙은 없다.

L2/L4는 원래 LightGBM 설정을 사용한다. L5 gate는 squared-error regression, 100 trees, learning rate 0.035, 6 leaves, min child 60, regularization 20이다. 날짜/시간별 capture 수의 역수로 가중한다. Inner OOF는 첫 8일로 학습하고 이후 3일 블록을 이전 날짜만으로 예측한다. Random split과 결과 확인 후 재튜닝은 없다.

## 고정 평가

Freeze는 `2026-10-03T18:00:50.748933+09:00`, data revision은 `ea57d03155b4c5b3f86c97b1b8fb5cbcc3afd275`다. Dataset SHA-256은 `99aad1b55f6e5c1ada5f1aeae76faa906bde7ce85dff5e7a20231777f9409610`, 후속 사전등록 SHA-256은 `5ffbac417837274c441a3e265da2971e8b602e031c9018724410d12d462687d4`다.

| Fold | 학습 | 평가 | Pair |
|---|---|---|---:|
| 1 | 8/28–9/10 | 9/11–17 | 760 |
| 2 | 8/28–9/17 | 9/18–24 | 1,357 |
| 3 | 8/28–9/24 | 9/25–10/1 | 1,588 |

이미 본 historical 날짜이므로 시간순 retrospective 연구이지 **새 독립 확증이 아니다**. 당시 확정 label 도착 시각도 입증되지 않았다. 10/2·3 provisional과 새 live shadow 결과는 학습·선택에 쓰지 않는다.

Baseline은 same-run recorded post이며 published 또는 retrospective/latest와 다르다. Closest는 날짜/시간별 `(0,120]` 최소 positive lead 한 건으로 모든 근거리 issue 집계와 다르다. 당시 champion artifact/policy identity와 challenger 고유 밴드는 unavailable이다.

결과 전 연구용 기준을 고정했다: 전체 MAE/WAPE 3% 이상 개선, closest MAE 무악화, 전체/closest RMSE 증가 2% 이하, closest 일별 승 >= 패, 각 fold closest MAE 증가 10% 이하. 악화량 p95/max와 issue revision 평균/p95는 동일 표본의 재학습 L2 이하여야 한다. Band/regime 허용폭은 첫 fold 학습 champion 절대오차 중앙값 ×0.25다. Production threshold를 변경하지 않는다.

## 동일 표본 결과

확정 pair 3,705건, closest target 417건, 21일. 오차 단위는 MW다.

| 모델 | 전체 MAE | RMSE | WAPE | Bias | Closest MAE | RMSE | WAPE | Bias |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Champion | 838.3 | 1,158.7 | 2.792% | +156.8 | 558.6 | 730.7 | 1.906% | +72.5 |
| 재학습 L2 | 809.5 | 1,178.9 | 2.696% | -138.0 | 594.2 | 789.4 | 2.028% | -66.4 |
| L4 | 856.2 | 1,237.3 | 2.851% | -191.9 | 573.4 | 753.9 | 1.957% | -73.5 |
| L5 | 791.3 | 1,138.8 | 2.635% | -16.6 | 557.6 | 732.8 | 1.903% | -7.6 |

L5 전체 개선은 5.61%지만 closest 개선은 0.18%에 불과하다. 실질적 우월성 증명으로 보지 않는다. Closest 일별 승/패는 12/9다. Fold closest는 593.2/461.2/621.7, champion은 581.6/489.0/606.8이며 마지막 fold는 여전히 2.46% 악화한다. L4는 전체/근거리/tail/revision 기준에 실패했다. 사후 기준 완화는 없다.

마지막 fold의 동결 L2는 전체/closest 991.7/624.3, L5는 996.3/621.7이다. 학습 cutoff는 9/21과 9/24로 다르다. L5가 동결 L2보다 모든 구간에서 좋은 것은 아니다.

## Lead와 안정성

동결 L2의 원래 holdout을 후보 결과 전 등록한 구간으로 나눴다.

| Lead 분 | Pair | Champion MAE | 동결 L2 MAE |
|---|---:|---:|---:|
| (0,30] | 136 | 628.1 | 654.2 |
| (30,60] | 34 | 500.0 | 495.5 |
| (60,120] | 170 | 781.1 | 768.3 |
| (120,180] | 160 | 977.9 | 947.3 |
| (180,360] | 460 | 1,142.4 | 1,084.1 |
| >360 | 1,309 | 1,043.2 | 909.4 |

120분에서 깔끔히 전환되지 않으며 30–60분은 소표본이다. L5의 구간별 평균 weight는 약 0.52–0.55로, 주로 context 기반 shrinkage다. 단조 lead 신뢰도 법칙을 발견했다고 주장하지 않는다.

Walk-forward 전체 악화량 p90/p95/max는 재학습 L2 905.0/1,243.7/2,552.9에서 L5 546.2/754.8/1,952.9로 감소한다. Closest는 758.8/964.9/1,692.1에서 445.1/543.2/1,038.7로 줄었다. 무회귀는 아니다.

동일 target의 인접 issue 간격 <=120분인 2,838 pair에서 revision 평균/p95는 champion 164.8/661.4, 재학습 L2 273.6/780.4, L5 209.3/670.0이다. L2보다는 안정적이지만 champion보다는 더 변한다. Same-run shape와 cross-issue revision은 별개 지표다.

해당 issue run에서 L5 최대 추가 오차 반례는 9/14 09시 +474.9, 9/16 14시 +603.7, 9/22 20시 +210.0, 9/26 21시 +416.3 등이다. Outer-test 밖의 기존 사례는 historical context로 보존하며 독립 테스트로 세지 않는다.

## Worker와 기록

지속 수집에는 [격리된 Docker multi-challenger 서비스](docker-intraday-shadow.md)를 사용한다. 아래 terminal worker와 1.1 계약은 historical/manual 도구로 유지하며 독립 live inclusion은 새 서비스의 별도 계약으로 관리한다.

`feed.py`는 `data/intraday_challenger/<workspace>`의 별도 bare Git 저장소로 `data`만 가져온다. Allowlist의 snapshot/actual/ETL-state를 읽고 원본 bytes/hash/revision을 보존한다. `web/public` 복원·쓰기, production Git ref 변경, ETL 실행, 모델 API 호출은 없다.

Prediction `intraday-shadow/1.1.0`은 issue/capture 시각과 각 lead, target, raw/pre/post, cutoff, source pointer/hash, immutable identity를 보존한다. 시작된 target은 retrospective이며 기존 1.0 기록도 그대로 읽는다. 지연 수집은 제시각 발행이 아니므로 `captureDelayMinutes`, `capture_lead_minutes`를 확인한다.

Evaluation `intraday-shadow-evaluation/1.1.0`은 행별 actual state/hash, signed error와 absolute-error delta를 포함한다. 실측 revision은 별도 immutable 평가로 남기며 이전 평가·예측은 덮어쓰지 않는다. Identity, finalized/provisional, prospective/retrospective를 분리한다. 결측은 unavailable이고 forecast fallback은 실측이 아니다. Lead/time-band, 일별 승패, tail, revision을 집계한다. Sample readiness는 promotion readiness가 아니다.

```text
python -m python.eval.intraday_challenger lead-research --dataset <dataset.jsonl> --registration-file <preregistration.json> --registration-sha <sha256> --code-revision <revision> --output-root data/intraday_challenger/<new-research>
python -m python.eval.intraday_challenger.feed --remote https://github.com/wonhongChang/tokyo-grid-ems --model-root <frozen-model> --identity-sha <sha256> --output-root data/intraday_challenger/<identity-shadow> --start-date 2026-10-03 --interval-seconds 300
```

`--cycles 1`은 유한 수집 점검이다. 생략하면 Python 내부에서 대기하며 반복한다. 사용자 터미널에서 창을 유지해 실행하고 Ctrl+C로 중지한다. Scheduler/service/자동 부팅 등록은 없다. 정확한 historical 재현에는 Git에 포함하지 않은 로컬 frozen dataset/manifest가 필요하다.

## Identity와 다음 판단

L5는 10/1까지 확정 5,235행으로 학습했다. Identity SHA-256은 `e39715d5e956d6bb8f110df0b857f4af7baf94fa57fd3122fdce4f9e70a9a149`, 결합 fingerprint는 `614486238b55aaec6e705a686905b6264b9284c6ef38ed0cc75f2a4de6b393be`다. Artifact/dataset/피처/설정/OOF 기간/구현 hash를 고정했다. 원래 L2 모델·피처 source identity와 loader는 그대로다.

연구 단계에서는 L2 유한 worker cycle과 L5 첫 prospective capture를 확인했고 세션 background process를 남기지 않았다. 당시 지연 수집은 context이지 확정 독립 evidence가 아니다. 지속 수집은 별도 Docker 서비스가 담당하며 이 historical 확인을 현재 health로 해석하지 말고 status를 조회한다.

Identity별 기존 readiness를 유지한다: 확정 14일, 영업일 >=8, 비영업일 >=4, 확정 prospective pair >=300, closest target >=150. 실제 수집이 충족될 경우 10/18 ETL 후 재점검한다. 날짜 경과만으로 승인하지 않는다. Native interval/champion identity/정상 승격 절차도 여전히 필요하다.

추가 14개와 기존·관련 intraday/replay/batch 테스트 **총 258개 통과**. Leakage/cutoff, identity/hash, revision 불변성, 경로 격리, 직렬화/결정성, OOF/outer 시간순 분할, 표본 일치, lead 경계, unchanged-input worker를 검증했다. Generated dataset/model/capture, 사용량과 session 메모는 ignored로 남긴다.
