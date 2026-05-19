# 2026-05-20 상대 기온과 누적 열 관성 피처

> 고정 온도 보정 규칙 대신 상대 기온 변화와 3일 누적 열 관성을 모델 입력으로 반영한 개선 기록.

언어: [English](../../en/model-improvements/model-improvement-2026-05-20-relative-morning-weather-features.md) / [日本語](../../ja/model-improvements/model-improvement-2026-05-20-relative-morning-weather-features.md)

---

## 왜 필요했나

2026-05-20 오전 예측은 운영상 더 높은 수요가 예상되는 날씨였는데도 전날 실측과 거의 비슷한 선에 머물렀다.

모델에는 이미 CDD/HDD 성격의 기온 피처가 있었지만, 오전 수요는 여전히 아래 피처에 강하게 묶여 있었다.

- `recent_same_business_type_mean`
- `lag_24h`
- 같은 시간대 과거 패턴

그 결과 아침 기온 조건이 최근 기준보다 달라져도, 예측이 전날 같은 시간 수요를 너무 많이 따라가는 문제가 남았다.

---

## 변경 내용

날씨 피처를 다시 검토했고, CDD/HDD 형태의 degree 피처는 유지했다.

- `cooling_degree = max(0, temp_c - cooling_base_temp_c)`
- `heating_degree = max(0, heating_base_temp_c - temp_c)`

이 값들은 "몇 도 이상이면 보정"하는 운영 규칙이 아니라, LightGBM이 쾌적 온도대에서 멀어질 때의 비선형 수요 반응을 학습하기 위한 설정 가능한 입력 피처다.

난방 기준점은 10.0°C에서 18.0°C로 변경했다. 기존 10°C는 도쿄의 겨울 난방 수요가 나타나기 전에 너무 늦게 반응하는 기준이었다.

평일 오전 램프 시간대, 현재 05~11시에 대해 LightGBM 피처 세 개를 추가했다.

- `business_morning_x_temp_delta_24h`
- `business_morning_x_temp_anomaly_7d`
- `business_morning_x_temp_anomaly_doy`

이 피처들은 절대 온도가 아니라 상대 기온 신호를 사용한다.

- 어제 같은 시간보다 따뜻한지/추운지
- 최근 7일 평균보다 따뜻한지/추운지
- 같은 월/같은 시간의 과거 기준보다 따뜻한지/추운지

따라서 "몇 도 이상이면 보정" 같은 고정 온도 규칙은 쓰지 않는다.

또한 3일 누적 열 관성을 보기 위해 아래 피처를 추가했다.

- `temp_72h_mean`
- `cooling_degree_72h_mean`
- `heating_degree_72h_mean`

폭염이나 한파가 이어질 때 건물과 도시가 열을 머금는 효과를 모델이 직접 학습하게 하는 목적이다.

---

## 기대 효과

평일 오전 수요가 전날 `lag_24h`만 따라가지 않고, 최근 기온 레짐 변화에 더 민감하게 반응할 수 있다.

특히 아침부터 기온이 상대적으로 높은 날에 05~11시 예측이 전날 수요에 과하게 고정되는 현상을 줄이는 것이 목표다.

72시간 피처는 단일 시간대 기온에 과하게 흔들리지 않으면서, 지속적인 더위/추위는 반영하도록 돕는다.

---

## 메모

- 기존 degree 스타일 기온 피처는 설정 가능한 모델 입력으로 유지한다.
- 습도 기반 heat-index 피처는 이번에 추가하지 않았다. 현재 운영에서 우선 사용하는 일본 기상청 공식 예보 피드가 시간별 습도를 제공하지 않기 때문이다. `apparent_temp_c`는 데이터 소스가 제공할 때 사용하고, 없으면 `temp_c`로 대체한다.
- 운영 guard에서는 optional absolute warm-day temperature floor를 제거했다.
- LightGBM interval version을 올려서 다음 ETL/intraday 실행 시 새 피처 세트로 재학습되게 했다.
