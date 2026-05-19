# 데이터 보존 및 아카이브 전략

> GitHub Pages 기반 공개 대시보드를 유지하면서 repository가 무한히 커지지 않도록 하기 위한 운영 정책입니다.

언어: [English](../en/data-retention-strategy.md) · [日本語](../ja/data-retention-strategy.md)

---

## 배경

TokyoGridEMS는 GitHub Pages를 통해 정적 JSON 파일을 공개합니다. GitHub Actions가 TEPCO/JMA 기상 데이터를 수집하고, JSON/parquet/model 산출물을 만든 뒤, GitHub Pages가 별도 백엔드 없이 이를 서빙합니다.

이 단순한 구조는 공개 포트폴리오 프로젝트에 잘 맞습니다. 하지만 Git은 장기 데이터베이스가 아니므로, 모든 일별 JSON, 모델 pickle, cache snapshot을 영구 커밋하면 clone 크기와 Actions checkout 시간이 점점 늘어날 수 있습니다.

## 운영 원칙

repository는 영구 데이터 저장소가 아니라 공개 서빙 계층으로 사용합니다.

- GitHub Pages에는 최신 대시보드 상태와 제한된 최근 이력만 둡니다.
- 과거 전력 실측의 source of truth는 TEPCO CSV/ZIP입니다.
- 모델 forecast JSON은 운영 산출물이자 검증 자료지만, 무한히 쌓이는 일별 파일 저장소가 되어서는 안 됩니다.
- 장기 공개 이력은 GitHub Pages에서 그대로 fetch 가능한 월별 archive 또는 metrics 파일로 압축합니다.

## 권장 보존 정책

| 데이터 종류 | 일별 JSON 유지 기간 | 장기 형태 | 비고 |
|---|---:|---|---|
| `status.json` | 현재만 | 없음 | 최신 대시보드 요약 |
| `actual/YYYY-MM-DD.json` | 최근 180-365일 | 월별 archive JSON | 과거 실측은 TEPCO CSV/ZIP로 재구성 가능 |
| `forecast/YYYY-MM-DD.json` | 최근 180-365일 | 월별 archive 또는 일별 metrics | 과거 예측은 주로 평가용 |
| `forecast_snapshots/YYYY-MM-DD/*.json` | 최근 21일, 날짜별 최대 16개 | 추후 compact lead-time metrics | 각 갱신 시점의 모델 판단을 분석하기 위한 자료 |
| `alerts/YYYY-MM-DD.json` | 최근 180-365일 | 월별 archive 또는 요약 metrics | UI 응답성 유지 |
| `metrics/*.json` | 유지 | rolling/monthly metrics | 작고 포트폴리오 가치가 높음 |
| `.hourly_cache.parquet` | 현재 snapshot만 | 원천 데이터에서 재생성 가능 | Actions에는 유용하지만 Git history 비대화 위험 |
| `.lgbm_model.pkl` | 현재 모델만 | 재학습 가능한 artifact | 바이너리 history가 빠르게 커질 수 있음 |

## 제안하는 공개 파일 구조

```text
web/public/
  status.json
  actual/YYYY-MM-DD.json
  forecast/YYYY-MM-DD.json
  forecast_snapshots/YYYY-MM-DD/index.json
  forecast_snapshots/YYYY-MM-DD/YYYY-MM-DDTHH-MM-SS-09-00.json
  alerts/YYYY-MM-DD.json

  archive/
    actual/2026-05.json
    forecast/2026-05.json
    alerts/2026-05.json

  metrics/
    forecast_accuracy.json
    model_backtest.json
    daily_mae.json
```

대시보드는 기본적으로 최근 일별 파일만 로드합니다. 나중에 UI에서 오래된 데이터를 볼 필요가 생기면, 해당 월의 archive 파일만 필요할 때 fetch하면 됩니다.

## 아직 외부 DB를 쓰지 않는 이유

S3, R2, Supabase, managed database 같은 외부 저장소를 쓰면 repository 성장은 줄일 수 있습니다. 하지만 CORS, 공개 권한, credential, 비용, 추가 장애 지점이 생깁니다.

이 프로젝트에서는 다음 절충안이 더 적합합니다.

- GitHub Pages를 유일한 공개 호스팅 계층으로 유지
- 오래된 공개 데이터는 정적 월별 파일로 압축
- 첫 화면 로딩은 가볍게 유지
- private API key나 별도 백엔드 인프라를 피함

## Forecast 데이터 경계

과거 모델 forecast JSON은 학습용 actual로 사용하지 않습니다. 학습과 lag feature는 TEPCO 실측을 기준으로 만들고, 최신 intraday에서 아직 실측이 공개되지 않은 시간대에만 TEPCO forecast fallback을 임시 사용합니다.

이 경계 덕분에 모델이 자기 자신의 예측값을 미래 학습 데이터로 다시 먹는 순환을 피할 수 있습니다.

## 현재 스냅샷 정책

lead-time 예측 스냅샷은 ETL과 intraday 실행 시 `forecast_snapshots/` 아래에 저장합니다.

- 최근 21개 target date를 유지합니다.
- target date별 최대 16개 스냅샷만 유지합니다.
- 생성 시점의 실측/TEPCO fallback 관측 개수를 함께 기록합니다.
- 예측 series와 peak 요약을 저장해 나중에 운영 관점에서 원인을 분석할 수 있게 합니다.
- 공개 UI에는 직접 연결하지 않고, 모델 검토와 사고 분석용으로만 사용합니다.

## 향후 구현 작업

1. ETL 마지막 단계에 오래된 `actual`, `forecast`, `alerts` 일별 JSON을 `archive/{actual,forecast,alerts}/YYYY-MM.json`으로 압축하는 cleanup을 추가합니다.
2. archive 생성 후 최근 일별 JSON만 남깁니다.
3. UI에서 과거 월을 탐색할 필요가 생기면 archive month index 파일을 추가합니다.
4. forecast snapshot 이력이 커지면 오래된 스냅샷을 compact lead-time metrics로 변환합니다.
5. repository 크기가 문제가 되면 `.hourly_cache.parquet`, `.lgbm_model.pkl`을 재생성 가능하게 하거나 장기 Git history 밖으로 분리하는 방안을 검토합니다.
