# 2026-05-21 공식 JMA 기온과 하이브리드 습도 보완

> 공식 JMA를 기온 기준으로 유지하면서, 습도 결측 때문에 체감온도 신호가 단순 기온으로 무너지는 문제를 막은 개선 기록.

언어: [English](../../en/model-improvements/model-improvement-2026-05-21-official-jma-humidity-correction.md) / [日本語](../../ja/model-improvements/model-improvement-2026-05-21-official-jma-humidity-correction.md)

---

## 왜 필요했나

최근 intraday 예측에서 오전 수요를 낮게 보는 문제가 반복됐다. 공식 JMA 예보는 기온 곡선을 제공하지만, 현재 사용 중인 Tokyo time-series endpoint에는 시간별 예보 습도가 없다.

그 결과 미래 예측 행이 다음 상태가 될 수 있었다.

- `temp_c`는 공식 JMA 값
- `apparent_temp_c`는 `temp_c`와 동일
- `humidity_pct = NaN`
- `discomfort_index = NaN`

전력 수요 예측에서는 이 차이가 중요하다. 같은 22도라도 습한 오전은 건조한 오전보다 냉방 수요가 더 빨리 올라갈 수 있는데, 습도가 비어 있으면 모델은 그 차이를 볼 수 없다.

---

## 변경 내용

운영 기상 데이터 우선순위를 다음처럼 정리했다.

1. **관측 완료 시간**
   - 기온, 습도, 불쾌지수, 습도 반영 체감온도는 JMA AMeDAS 관측값을 사용한다.

2. **미래 기온**
   - 공식 JMA time-series 예보만 사용한다.

3. **가까운 미래 습도**
   - 공식 JMA에 습도가 없으면, 최신 AMeDAS 관측 습도를 1-3시간만 짧게 forward fill 한다.

4. **그 이후 미래 습도**
   - Open-Meteo JMA는 습도 보완재로만 사용한다.
   - 공식 JMA `temp_c`는 덮어쓰지 않는다.
   - `apparent_temp_c`와 `discomfort_index`는 공식 JMA 기온과 보완 습도를 이용해 다시 계산한다.

5. **최종 fallback**
   - 모든 실시간 습도 소스가 실패하면 월별 보수 평균 습도를 사용한다.

캐시에는 `weather_source`도 저장한다. 예측이 튀었을 때 다음처럼 기상 입력 경로를 추적할 수 있다.

- `AMEDAS_ACTUAL`
- `JMA_FORECAST+FORWARD_FILL`
- `JMA_FORECAST+OPEN_METEO_JMA`
- `JMA_FORECAST+SEASONAL_MEAN`

---

## 기대 효과

공식 JMA 기온 곡선을 유지하면서, 습한 날의 체감온도 입력을 복구한다.

특히 raw 기온은 평범해 보이지만 실제로는 습해서 냉방 수요가 빨리 올라가는 오전/저녁 시간대에 도움이 된다. 동시에 다른 제공자의 기온 예보가 공식 JMA 기온을 덮어써서 생기던 운영 불신도 피한다.

---

## 운영 메모

- Open-Meteo JMA는 미래 예측 행의 습도 보완에만 사용한다.
- 기존 과거 캐시는 `humidity_pct`만 비어 있다는 이유로 강제 backfill하지 않는다. 그렇지 않으면 ETL이 몇 년치 archive를 한 번에 다시 채우려 할 수 있다.
- 기존 과거 `apparent_temp_c`는 모델 학습에 계속 사용한다.
- `weather_source`는 추적용 메타데이터이며 LightGBM 입력 피처에는 추가하지 않았다.

---

## 테스트

추가/수정한 테스트는 다음을 확인한다.

- Open-Meteo JMA 습도를 사용해도 공식 JMA 기온은 유지된다.
- 가까운 미래에는 AMeDAS 습도 forward fill이 우선된다.
- 계절 평균 습도는 최종 fallback으로만 사용된다.
- 과거 캐시에 습도만 비어 있어도 대량 archive 재수집을 하지 않는다.
- 전체 회귀 테스트: `306 passed`.
