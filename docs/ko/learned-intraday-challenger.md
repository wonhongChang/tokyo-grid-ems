# 학습형 Intraday Challenger

[English](../en/learned-intraday-challenger.md) | [日本語](../ja/learned-intraday-challenger.md)

## 상태

2026-10-03 실험의 결론은 **RETAIN CHALLENGER: L2**다. 기존 post 예측 뒤에 남은 오차를 별도의 LightGBM으로 학습한다. 운영 champion, ETL, scheduler, published forecast, 기존 승격 정책은 변경하지 않았다. Shadow worker는 별도 실행 도구이며 자동 운영 경로에 등록되어 있지 않다.

전체 미래 예측에서는 개선했지만 근거리 예측에서는 악화했다. 따라서 운영 승격이나 shadow 합격으로 표현하지 않는다.

## 구조

```text
immutable issue-time calibration snapshot
  -> completed observations + same-run raw/pre/post context
  -> chronological learned error model
  -> isolated shadow prediction record
  -> finalized actual join
  -> daily / time-band / lead / cumulative numeric comparison
```

구현은 `python/eval/intraday_challenger/`에 있다. 운영 모듈에서 import하지 않는다. Jev, OpenAI 또는 다른 유료 API를 호출하지 않는다. 특정 시간의 수요를 규칙으로 올리거나 내리는 새 guard도 추가하지 않는다.

### 후보

| 후보 | 예측식 | 학습 target |
|---|---|---|
| L1 | raw + learned error | actual - raw |
| L2 | recorded post + learned remaining error | actual - post |
| L3 | pre + latest raw residual + learned residual change | actual - pre - latest raw residual |

L3는 연구에서만 기존 intraday 보정을 우회한다. L1/L2/L3의 모든 결과는 보존하며, 검증 구간에서 후보를 선택한 다음 train+validation으로 재학습하고 최종 holdout을 평가한다. Holdout 결과로 후보를 재선택하거나 설정을 수정하지 않는다.

공통 설정은 L1 loss, 240 trees, learning rate 0.035, 12 leaves, min-child 45, L2 regularization 10, 고정 seed 및 CPU thread 2다. 날짜/시간당 수집 횟수의 역수를 sample weight로 사용해 자주 수집된 시간의 과도한 비중을 줄인다.

## 근거와 누수 방지

- 동결 시각: `2026-10-03T18:00:50.748933+09:00`.
- Code revision: `fe1eaa84a6cc70d061a4c4d8d56782e373d055c4`.
- Data revision: `ea57d03155b4c5b3f86c97b1b8fb5cbcc3afd275` 및 해시를 확인한 기존 retained snapshots.
- 입력 manifest SHA-256: `2d9b919ca26df0245a0ec054079e00b873c18dee5cc2c05f154a24efa7ddc9e0`.
- 첫 후보 결과 전 preregistration SHA-256: `3ede9079a0305e916add1883d580d08f693a8151601452f0159018185ebbc568`. 이후 수정은 dataset 무결성 검사와 shadow 기록 경계였으며, 후보 설정·기간·선택식·합격 기준은 바꾸지 않았다.
- 최종 재현 실행 preregistration SHA-256: `7fa4c6b5b6d0538c40e7c688f677ce5dfb7727669d2623da58ea764d14b34bf6`.
- L2 native model SHA-256: `0bcd25b4133fa57fe446da5eb6beea537f65947aaa940d2c027718ac9b9a88f5`.

517개 실행으로부터 positive-lead issue-target 5,622행을 만들었다. 확정 라벨 5,235행, 잠정 라벨 294행, 미관측 93행이다. 미관측은 미래 55행, 진행 중인 시간 구간 11행, 과거 미수신 27행으로 구분한다. 반복 수집 행은 독립적인 관측 5,622개를 의미하지 않는다.

| 구간 | 날짜 | 확정 행 | Closest (0,120]분 |
|---|---|---:|---:|
| Train | 8/28~9/13 | 1,863 | 261 |
| Validation | 9/14~9/21 | 1,103 | 140 |
| Holdout | 9/22~10/1 | 2,269 | 229 |

46개 피처는 forecast path/delta, lead, calendar, 완료된 당일 actual path, 최근 residual과 trend, snapshot에 기록된 lag/anchor delta로 구성된다. `hour=h`의 관측은 `[h,h+1)`이 끝난 후에만 사용하며, recorded cutoff도 만족해야 한다. Forecast fallback은 실측으로 사용하지 않는다. 결측은 native missingness로 유지한다.

Final actual은 별도 label join에만 사용한다. TEPCO 예측과 출처 시각이 불명확한 기상 재구성 값은 학습 피처에 들어가지 않는다. 행별로 snapshot hash, pointer, issue/target/lead, 관측 cutoff, 라벨 hash를 보존한다.

### 해석 제한

- baseline은 **같은 실행에 기록된 post**다. Published 선이나 최신 정책을 과거에 재적용한 선과 혼합하지 않는다.
- 과거 snapshot의 정확한 champion artifact/policy identity는 미기록이며 null로 유지한다. 최신 model metadata로 소급해 채우지 않는다.
- 과거 final label의 정확한 ETL 전달 시각은 확인되지 않았다. 이것은 시간순 retrospective 학습 실험이며, 그 모델이 당시 배포되어 있었다는 증거는 아니다.
- Holdout은 이번 fitting에서 제외했지만 일부 날짜는 이전 연구에서 이미 검토한 날짜다. 새 독립 증거는 실제 이후 shadow에서 확보해야 한다.
- Native challenger interval은 없다. Champion 밴드를 복사해 challenger 신뢰구간인 것처럼 평가하지 않는다.
- 당일 00시 타깃과 다음 날짜 forecast는 현재 same-day positive-lead 모델의 평가 범위 밖이다.

## 정량 결과

모두 동일한 finalized issue-target population에서 비교한 값이다. MAE/RMSE/bias 단위는 MW다.

| 모델 | 전체 미래 MAE | 전체 RMSE | 전체 WAPE | Closest MAE | Closest RMSE |
|---|---:|---:|---:|---:|---:|
| Recorded champion | 1,006.0 | 1,321.1 | 3.354% | 576.7 | 771.9 |
| L1 | 952.2 | 1,308.4 | 3.174% | 649.1 | 838.7 |
| L2 | 915.4 | 1,272.9 | 3.052% | 604.9 | 782.0 |
| L3 | 938.6 | 1,300.0 | 3.129% | 619.4 | 807.5 |

L2는 전체 MAE 9.01% 개선, closest MAE 4.88% 악화다. 전체 bias는 +241.9에서 -85.9로, closest bias는 +138.0에서 +16.1로 변했다.

| L2 구간 | 전체 champion → L2 MAE | Closest champion → L2 MAE |
|---|---:|---:|
| 00~05 | 448.6 → 469.2 | 361.9 → 400.3 |
| 06~11 | 1,001.8 → 1,014.5 | 725.9 → 672.2 |
| 12~13 | 1,573.6 → 1,490.9 | 860.4 → 898.3 |
| 14~17 | 1,309.3 → 1,103.7 | 591.2 → 655.5 |
| 18~23 | 765.6 → 678.6 | 502.8 → 577.3 |
| 영업일 | 1,038.4 → 1,027.3 | 613.0 → 634.5 |
| 비영업일 | 957.6 → 747.7 | 522.8 → 560.8 |

전체 positive-lead 중 L2 개선/악화는 1,332/937행, 날짜별 승/패는 6/4다. Closest는 개선/악화 105/124행, 날짜별 승/패 3/7이다.

| 악화 행의 추가 절대 오차 | 전체 | Closest |
|---|---:|---:|
| p50 | 299.4 | 234.7 |
| p90 | 715.6 | 583.5 |
| p95 | 845.3 | 695.1 |
| 최대 | 1,513.8 | 1,264.3 |

최대 악화는 9/25 03:35 발행의 15시 타깃이다. Closest 최대 악화는 9/24 12:26 발행의 13시 타깃이다. 9/22 20시 guard-success 사례에서도 절대 오차가 689.1MW 악화했다. 과거 F/G/H의 16개 source-exact 재평가를 별도로 보존했다. 학습 구간 사례는 독립 성능 증거로 세지 않는다.

같은 run의 인접 target delta MAE는 415.2 → 362.4로 개선했지만, 인접 issue 간 동일 target의 평균 변경량은 167.7 → 284.4로 증가했다. **곡선 내부의 매끄러움 개선과 실행 간 안정성은 다른 문제다.**

### 10/3 잠정 관찰

같은 issue/target의 closest 관측 14개에서 raw MAE 629.2, champion 702.6, L2 781.5였다. 아직 오늘의 개선이라고 주장할 수 없다. 9/10시의 retained 근거리 pair와 00시 pair는 이 population에 없으며, 미래 실측은 평가하지 않았다.

## 사전 기준과 선택

후보 결과를 보기 전에 train champion 오차 분포를 사용했다. 평균 MAE/WAPE 5% 이상 개선, RMSE 증가 2% 이내, 날짜 승수 >= 패수, 시간대/레짐 악화 허용 168.8MW, 추가 악화 p95 <= 1,721.9MW, 최대 <= 2,976.5MW 등을 기록했다. 이것은 **실험용 shadow 기준**이지 운영 승격 threshold 변경이 아니다.

L2만 validation에서 사전 꼬리 위험 한도를 넘지 않았고 validation 선택 점수도 가장 낮았다. 최종 holdout에서는 전체 population 조건을 통과했지만 closest 평균 개선과 날짜 승패 조건에 실패했다. L1/L3도 근거리 조건을 통과하지 못했다. 결과 후 기준을 완화하지 않았다.

## 로컬 사용

CLI는 모든 출력에 명시적인 `--output-root`를 요구하며, 이름 있는 `data/intraday_challenger/<workspace>` 아래로 제한한다. 이 디렉터리는 Git 제외 대상이다.

| 명령 | 역할 | 필수 입력 |
|---|---|---|
| `prepare` | sealed dataset, baseline-derived preregistration | `--input-root`, `--input-sha`, `--periods` |
| `train-replay` | 3개 후보 학습/선택/holdout 평가 | `--registration-sha` |
| `shadow-capture` | immutable snapshot 기반 별도 예측 저장 | `--snapshot`, `--snapshot-sha`, `--model-root`, `--identity-sha` |
| `shadow-evaluate` | 확정/잠정/미관측 및 revision 분리 집계 | `--actual-root`, `--state-file` |
| `shadow-watch` | 새 snapshot 및 확정 actual을 감시하는 별도 worker | `--snapshots-root`, `--model-root`, `--identity-sha`, `--actual-root`, `--state-file` |

```powershell
python -m python.eval.intraday_challenger --help
```

`--periods`는 `train`, `validation`, `holdout`의 `[start,end]`를 가진 JSON이다. 입력 manifest 계약은 `intraday-input/1.0.0`이며 `asOf`, `runs`, `actuals`가 필요하다. 각 source는 input root에 상대적인 JSON path와 SHA-256을 갖는다. Run에는 `date`, `issuedAt`, actual에는 `date`, `state`가 필요하다. 입력 변경, vintage 불일치, 중복 issue-target, split 겹침은 실패한다.

Shadow는 issue 시각과 실제 `recordedAt`을 함께 저장한다. 저장 전에 이미 시작된 target은 retrospective capture로 분리하며 live confirmation에 넣지 않는다. 예측 파일은 재실행해도 덮어쓰지 않는다. Actual revision은 새로운 hash 기반 evaluation으로 남는다. 서로 다른 model identity는 합산하지 않는다.

Worker의 기본 sleep은 300초이며 Python 내부에서 대기한다. Source 동기화는 외부 운영 흐름의 책임이다. Worker를 시작하거나 scheduler/ETL에 연결하는 작업은 별도의 운영 결정이며 이번 실험에서는 수행하지 않았다.

## 검증 및 다음 판단

새 모듈 42개 테스트와 관련 intraday/replay/batch 회귀 테스트를 포함해 244개가 통과했다. 입력 불변성, 미래 실측 차단, fallback 제외, 결측/리드/휴일/시간대, 모델 저장/로드/해시, deterministic inference, shadow 출력 제한, actual revision, 과거 capture 제외를 검증했다. Windows Git의 LF/CRLF 변환은 source identity에서만 정규화하며 실제 데이터와 model artifact의 hash는 원본 bytes로 검증한다. 6개 native 학습 파일과 모든 수치 보고서의 재현 결과도 동일했다.

향후 최소 14개 확정 일자, 영업일 8일 이상/비영업일 4일 이상, 전체 prospective pair 300개 이상 및 closest target 150개 이상을 확보한 뒤 재검토한다. 정상 수집이면 10/18 ETL 후 첫 판단이 가능하다. 이는 표본 준비 조건이지 자동 승격 조건이 아니다.

기존 기준의 평균/꼬리/시간대/레짐 통과, 실행 간 revision 안정성, native interval 검증, champion policy/artifact attestation을 함께 확인해야 한다. 현재 미평가된 00시/next-day 경로를 검증하지 않은 채 전체 운영 모델을 교체하지 않는다. 운영 채택에는 별도 serving-policy identity/version 변경과 기존 promotion 절차가 필요하다.

Dataset, replay, native model 및 날짜별 shadow 파일은 로컬 ignored workspace에만 보관한다. 공개 대상은 코드, 테스트, 계약 설명과 요약 결과이며 대량 연구 산출물은 포함하지 않는다.
