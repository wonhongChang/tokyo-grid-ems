# Tokyo Grid EMS

TEPCO 공개 전력 데이터를 활용한 **전력 수요 예측 / 이상 탐지 / 모니터링 대시보드**

> [English](README.md) · [日本語](README_ja.md)

- 운영 대시보드: [https://wonhongchang.github.io/tokyo-grid-ems/](https://wonhongchang.github.io/tokyo-grid-ems/)

---

## 프로젝트 개요

도쿄전력 파워그리드(TEPCO)가 공개하는 시계열 전력 데이터를 기반으로, 아래 핵심 기능을 제공하는 **자동 갱신형 정적 EMS(에너지 관리) 프로토타입**입니다.

- 전력 수요 **예측** (시간별, 피크 시각/값 포함)
- 예측 대비 **이상 패턴 탐지** (급등/급락, 잔차 드리프트, 공급 예비율 위험)
- GitHub Pages로 공개 가능한 **정적 대시보드**

> 전제: GitHub Pages에 정적 JSON을 배포하는 구조지만, 당일 데이터는 TEPCO intraday CSV를 2시간마다 가져와 보강합니다.
> 따라서 **어제의 확정 이상 탐지 리포트** + **오늘/내일 예측 리포트** + **당일 실측/TEPCO 예측 비교**를 중심으로 화면을 구성합니다.

---

## 기술 스택

| 역할 | 기술 |
|------|------|
| ETL / 파싱 | Python (pandas) |
| 예측 / 이상 탐지 | Python (LightGBM + 통계 fallback, rule-based anomaly detection) |
| 대시보드 | React + Vite |
| 배포 | GitHub Pages (정적 JSON) |
| 자동 갱신 | GitHub Actions (매일 + 2시간마다) |
| 운영 리포트 | Python 규칙 기반 fallback + 선택적 OpenAI 해설/번역 |

---

## 아키텍처

![Tokyo Grid EMS Architecture](docs/assets/tokyo-grid-ems-architecture.png)

- **ETL**: TEPCO 월별 ZIP을 매일 다운로드 → 확정 이력 데이터 파싱 → JSON 생성 → GitHub Pages 배포
- **Intraday**: 2시간마다 당일 TEPCO intraday CSV 취득·갱신
- **검증 / 운영 리포트**: 전날 운영 리포트, TEPCO 예측 대비 운영 성능, LightGBM 백테스트, UI에 노출하지 않는 내부 진단 JSON, 선택적 AI 해설 리포트를 생성

---

## 대시보드 화면 구성

**상단 상태바 (항상 표시)**
- 최종 업데이트 시각 / 데이터 취득 상황

**탭 5개**

1. **어제** — 전날 실적 + 이상 이벤트
   - Spike / Drop: 예측 구간(95/99%) 초과 여부
   - Drift: 잔차(residual) 지속 편향 (EWMA)
   - Reserve Risk: 사용률/예비율 임계 기반 위험 구간

2. **오늘** — 시간별 예측 + 예측 구간 + 피크 예상 (시각/값)

3. **내일** — 시간별 예측 + 예측 구간 + 피크 예상 (시각/값)

4. **검증** — 전날 운영 리포트 + 자체 모델과 TEPCO 예측 비교 + LightGBM 백테스트

5. **운영 리포트** — deterministic 지표를 바탕으로 생성하는 일일 운영 해설
   - 전날 성능 지표, 주요 오차, 데이터 품질, 운영 보정 메타데이터를 사용
   - OpenAI 키가 없으면 규칙 기반 fallback 리포트로 표시
   - `OPENAI_API_KEY`가 있으면 영어 마스터 분석을 만들고 한국어/일본어로 현지화

---

## TEPCO CSV 데이터 포맷

| 항목 | 내용 |
|------|------|
| 출처 | TEPCO 공개 전력 수요/공급 데이터 |
| 인코딩 | **cp932 (Shift-JIS)** |
| 단위 | **万kW (= 10 MW)** |
| 포맷 | 여러 테이블이 빈 줄로 연결된 **멀티 섹션 CSV** |

### CSV 섹션 구조 (1파일 = 1일)

```
2026/5/6 23:55 UPDATE
[당일 요약 블록] × 4 (피크 공급력, 예상 최대 전력, 사용률 피크 등)

DATE,TIME,当日実績(万kW),予測値(万kW),使用率(%),供給力(万kW)
← 시간별(24행) →

最大使用率(%) 블록

[익일 요약 블록] × 4

DATE,TIME,当日実績(５分間隔値)(万kW),太陽光発電実績(...),太陽光発電量(...)
← 5분(288행) →
```

### 데이터 처리 규칙

- 인코딩: `cp932` (또는 자동 감지)
- 타임스탬프: `DATE + TIME` → `Asia/Tokyo` 기준 ISO 8601 (`+09:00` 포함)
- 품질 게이트: 시간별 24행 / 5분 288행 확인, 중복/단조성/갭 체크

---

## 리포지토리 구조

```
.
├── python/
│   ├── tepc_parser.py          # TEPCO 멀티 섹션 CSV 파서
│   ├── etl/
│   │   ├── run_batch.py        # 배치 실행 (CSV → JSON 생성)
│   │   ├── fetch_tepco.py      # TEPCO 월별 ZIP 다운로드
│   │   ├── fetch_today.py      # 당일 실시간 데이터 취득
│   │   └── quality_gate.py     # 품질 검사
│   ├── forecast/               # 수요 예측 모델
│   └── anomaly/                # 이상 탐지
├── web/                        # React/Vite 대시보드
├── docs/
│   ├── en/                     # 영어 문서
│   ├── ko/                     # 한국어 문서
│   ├── ja/                     # 일본어 문서
│   └── assets/                 # README와 문서용 이미지
└── data/
    └── raw/                    # 원본 CSV (Actions에서 자동 다운로드, git 제외)
        └── YYYY/
            └── YYYYMM_power_usage/
```

---

## 빠른 시작

### 로컬 실행

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# TEPCO 데이터 취득
python python/etl/fetch_tepco.py

# ETL 실행 → web/public/ 아래에 JSON 생성
python python/etl/run_batch.py --input data/raw --out web/public

# 선택 사항: OpenAI 기반 일일 운영 리포트 활성화
# Windows PowerShell:
# $env:OPENAI_API_KEY="..."
# $env:OPENAI_DAILY_REPORT_MODEL="gpt-5.4-mini"
# $env:OPENAI_DAILY_REPORT_LOCALIZATION_MODEL="gpt-4o-mini"

# 대시보드 로컬 미리보기
cd web && npm install && npm run dev
```

### GitHub Pages 배포

[DEPLOY_ko.md](DEPLOY_ko.md)를 참고하세요.

---

## 정적 JSON 산출물

ETL이 `web/public/` 아래에 생성하는 파일들입니다.

| 파일 | 내용 |
|------|------|
| `status.json` | 전체 상태 (최종 업데이트, 오늘/내일 예측 요약) |
| `alerts/YYYY-MM-DD.json` | 이상 탐지 이벤트 목록 |
| `forecast/YYYY-MM-DD.json` | 시간별 예측값 + 예측 구간(95/99%) |
| `actual/YYYY-MM-DD.json` | 시간별 실적값 (당일 실시간 포함) |
| `forecast_snapshots/YYYY-MM-DD/*.json` | 운영 분석용 lead-time 예측 스냅샷 (UI에는 직접 연결하지 않음) |
| `metrics/forecast_accuracy.json` | TEPCO 예측 대비 자체 모델 운영 성능 |
| `metrics/model_backtest.json` | 베이스라인 대비 LightGBM 백테스트 |
| `reports/daily/*.json` | 검증 탭에 표시하는 전날 운영 리포트 |
| `reports/ai/daily/{ko,en,ja}/*.json` | 운영 리포트 탭의 일일 해설. OpenAI 설정 시 AI 해설, 미설정 시 deterministic fallback 사용 |
| `reports/internal/daily-diagnostics/*.json` | 운영 산출물과 함께 저장하는 내부 분석용 lag/기온/shape 진단 JSON (UI에는 연결하지 않음) |
| `reports/internal/operational-calibration/*.json` | 운영 디버깅용 source confidence와 보정 메타데이터 |

> 타임스탬프는 전 산출물에서 `Asia/Tokyo (+09:00)` 기준 ISO 8601로 출력합니다.

### AI 운영 리포트 동작

- AI 리포트는 ETL 실행에서만 생성하며, intraday/status-only 실행은 리포트 본문을 다시 쓰지 않습니다.
- 같은 날짜/언어의 리포트 JSON이 이미 있으면 후속 ETL 재시도에서도 보존하여 API 비용이 반복 발생하지 않게 합니다.
- OpenAI 호출은 기본 2회로 제한합니다. 1차는 영어 마스터 분석(`OPENAI_DAILY_REPORT_MODEL`, 기본값 `gpt-5.4-mini`), 2차는 한국어/일본어 현지화(`OPENAI_DAILY_REPORT_LOCALIZATION_MODEL`, 기본값 `gpt-4o-mini`)입니다.
- GitHub Actions용 timeout 기본값은 `OPENAI_DAILY_REPORT_TIMEOUT_SECONDS=90`, `OPENAI_DAILY_REPORT_LOCALIZATION_TIMEOUT_SECONDS=180`입니다. GitHub repository variables를 설정하지 않아도 Python 기본값이 적용됩니다.
- 번역이 실패하거나 timeout되면 해당 언어 경로는 영어 마스터 본문으로 fallback하고 `localizationStatus: "fallback_en"`을 기록합니다.

---

## 문서

- [학생을 위한 프로젝트 전체 설명](docs/ko/project-walkthrough.md)
- [LightGBM 모델 설계](docs/ko/lgbm-design.md)
- [기온 데이터 연동 설계](docs/ko/weather-integration.md)
- [데이터 보존 및 아카이브 전략](docs/ko/data-retention-strategy.md)
- [모델 평가 리포트](docs/ko/model-evaluation.md)
- [이상탐지 기준](docs/ko/anomaly-criteria.md)
- [운영 리포트 탭 설명](docs/ko/ops-report-tab.md)
- [JSON 스키마 계약](docs/ko/json_schema.md)

---

## 모델 개선 이력

선별된 최근 운영 개선:

- [2026-05-25 영업일 복귀 anchor 부족분 가드](docs/ko/model-improvements/model-improvement-2026-05-25-business-return-anchor-shortfall.md)
- [2026-05-25 영업일 복귀 lag24 cap 수정](docs/ko/model-improvements/model-improvement-2026-05-25-business-return-lag24-cap.md)
- [2026-05-23 음수 잔차 회복 감쇄](docs/ko/model-improvements/model-improvement-2026-05-23-negative-residual-recovery-damping.md)
- [2026-05-23 비영업일 전환 보정](docs/ko/model-improvements/model-improvement-2026-05-23-non-business-transition-calibration.md)
- [2026-05-22 검증 지표 스코어카드](docs/ko/model-improvements/model-improvement-2026-05-22-validation-metrics-scorecard.md)

전체 날짜순 로그: [docs/ko/model-improvements/README.md](docs/ko/model-improvements/README.md)

---

## 로드맵

| 페이즈 | 내용 | 상태 |
|---------|------|------|
| Phase 1–3 | ETL / 예측 / 이상 탐지 / 대시보드 | ✅ 완료 |
| Phase 4 | GitHub Pages 자동 배포 | ✅ 완료 |
| Phase 5-A | LightGBM 예측 모델 | ✅ 운영 반영 |
| Phase 5-B | 기온 데이터 연동 (Open-Meteo) | ✅ 운영 반영 |
| Phase 6 | 검증 탭 / 백테스트 / TEPCO 비교 | ✅ 완료 |

---

## 작성자

- Chang Wonhong
- LinkedIn: https://www.linkedin.com/in/wonhong-chang-6660a0177/
