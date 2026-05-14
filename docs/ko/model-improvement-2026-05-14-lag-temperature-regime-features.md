# 2026-05-14 전주 대비 기온 변화 피처

> 전주 같은 시간대 수요가 계절 전환기에 너무 낮은 기준점이 되는 문제를 줄이기 위한 피처 개선 기록입니다.

언어: [English](../en/model-improvement-2026-05-14-lag-temperature-regime-features.md) · [日本語](../ja/model-improvement-2026-05-14-lag-temperature-regime-features.md)

---

## 왜 필요했나

2026-05-14 예측에서는 전날 TEPCO 실측이 `lag_24h`로 들어가고 있었습니다. 하지만 09:00-13:00 예측은 더 낮은 `lag_168h`, 낮은 4주 같은 시간대 평균, 약한 기온 신호에 끌려 내려갔습니다.

이 상황은 피처의 빈틈을 보여줍니다. 계절이 바뀌는 시기에는 전주 같은 시간대 수요가 현재 수요의 좋은 기준점이 아닐 수 있습니다.

## 예측 개선 내용

LightGBM 피처에 다음 값을 추가했습니다.

- `temp_delta_168h`: 현재 같은 시간대 기온 - 168시간 전 같은 시간대 기온
- `cooling_delta_168h`: 현재 같은 시간대 냉방 degree - 168시간 전 같은 시간대 냉방 degree

또 냉방/난방 degree의 기준온도는 피처 코드에 하드코딩하지 않고 `config.yaml`로 분리했습니다.

```yaml
weather_features:
  cooling_base_temp_c: 22.0
  heating_base_temp_c: 10.0
```

피처 컬럼이 바뀌었기 때문에 LightGBM 모델 호환 버전도 올렸습니다. 기존 저장 모델은 stale로 보고 다음 ETL/intraday 실행에서 재학습됩니다.

또 `actual_mw`가 아직 비어 있는 가상 예측 기온 행은 intraday 실행 때마다 새 Open-Meteo 값으로 갱신합니다. 이로써 오전에 받아온 낡은 기온 예측이 하루 종일 모델 입력에 고정되는 문제를 막습니다.

## 설계 경계

이 변경은 TEPCO 예측값을 모델 입력으로 사용하지 않습니다. 기온에서 파생한 맥락을 추가해서, 모델이 전주 수요 lag를 덜 믿어야 하는 상황을 배울 수 있게 하는 개선입니다.
