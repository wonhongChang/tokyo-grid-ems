# 2026-05-21 공식 JMA 예보와 습도 기반 체감온도 보정

> Open-Meteo JMA를 운영 예보 fallback에서 제거하고, 공식 JMA AMeDAS 습도 관측을 가까운 미래 체감온도 보정에 사용한 개선 기록.

언어: [English](../../en/model-improvements/model-improvement-2026-05-21-official-jma-humidity-correction.md) / [日本語](../../ja/model-improvements/model-improvement-2026-05-21-official-jma-humidity-correction.md)

---

## 왜 필요했나

최근 intraday 예측에서 모델은 날씨를 실제 운영 감각보다 차갑게 해석하는 경우가 있었다. 일본 기상청 공식 예보는 기온 가이던스를 제공하지만, 시간별 습도는 제공하지 않는다. Open-Meteo JMA는 체감온도와 습도 계열 신호를 제공할 수 있지만, 도쿄 시간별 예보가 공식 JMA 기준과 다르게 움직이는 경우가 있어 운영 fallback으로 신뢰하기 어려웠다.

운영 예측 모델에서는 모든 파생 필드를 채우는 것보다 소스 일관성이 더 중요하다. 미래 기온 곡선은 한 소스에서 가져오고 체감온도만 다른 소스에서 섞으면 모델 입력이 서로 다른 신호를 줄 수 있다.

---

## 변경 내용

미래 예보 기상 입력은 공식 JMA 도쿄 time-series endpoint만 사용한다.

```text
https://www.jma.go.jp/bosai/jmatile/data/wdist/VPFD/130010.json
```

`fetch_forecast_temps()`에서는 더 이상 Open-Meteo JMA를 호출하지 않는다. 공식 JMA 예보를 가져오지 못하면, 덜 신뢰하는 소스로 조용히 전환하지 않고 에러로 드러나게 했다.

최근 관측 기상은 계속 공식 JMA AMeDAS 도쿄 관측소 데이터를 사용한다. 파서는 이제 아래 값을 보관한다.

- `humidity_pct`
- `discomfort_index`
- 공식 관측 기온, 습도, 풍속으로 추정한 습도 반영 체감온도

공식 JMA 예보에는 시간별 습도가 없으므로, 습도를 LightGBM 직접 피처로 추가하지는 않았다. 대신 intraday 기상 bias 보정이 최근 관측 습도 때문에 체감온도가 예보 입력보다 높거나 낮아진 경우 가까운 미래의 `apparent_temp_c`를 보정할 수 있게 했다.

---

## 기대 효과

공식 JMA 기온 곡선에 Open-Meteo JMA 체감온도 신호가 섞이는 문제를 피할 수 있다.

습한 아침에는 최신 AMeDAS 관측이 가까운 미래 체감온도를 올릴 수 있다. 다만 내일의 습도를 만들어내는 방식은 아니며, 당일 단기 운영 보정으로만 제한한다.

---

## 운영 메모

- 오래된 캐시 결측을 채우는 과거 backfill에는 Open-Meteo archive가 남아 있을 수 있다.
- 운영용 미래 예보 입력에는 Open-Meteo JMA fallback을 사용하지 않는다.
- 공식 JMA 예보 row의 `humidity_pct`와 `discomfort_index`는 AMeDAS 관측이 생기기 전까지 `NaN`이다.
- 이 변경은 기상 소스 신뢰도와 보정 방식 변경이며, TEPCO 수요 데이터나 예비율 위험 기준은 바꾸지 않는다.

---

## 테스트

추가/수정한 테스트는 아래를 확인한다.

- `fetch_forecast_temps()`가 Open-Meteo JMA fallback을 호출하지 않음.
- 공식 JMA 예보 실패가 에러로 드러남.
- AMeDAS 습도와 불쾌지수를 파싱함.
- 원 기온 bias가 threshold보다 작아도 체감온도 bias가 크면 intraday 보정이 적용됨.
