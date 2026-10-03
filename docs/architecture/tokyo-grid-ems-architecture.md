# Tokyo Grid EMS Architecture

Verified against current repository revision: `ae9c4911cbe2f8bb7f9e54bbf415569d986d8d75`

- [Editable HTML](tokyo-grid-ems-architecture.html)
- [Architecture PNG](../assets/tokyo-grid-ems-architecture.png)
- HTML canvas: 1600 x 1120 CSS px
- PNG: 3200 x 2240 px

![Tokyo Grid EMS Architecture](../assets/tokyo-grid-ems-architecture.png)

## System Overview

Tokyo Grid EMS는 TEPCO 수요 데이터와 기상 데이터를 정규화하고, 저장된 LightGBM champion의 예측에 운영 보정과 prediction interval calibration을 적용한다. 이상 탐지, 성능 지표와 일일 리포트는 예측 및 실측/보존 근거를 사용하는 병렬 운영 기능이다. 서비스 산출물은 GitHub Actions의 정적 빌드를 거쳐 GitHub Pages와 React/Vite 대시보드에 제공된다.

녹색 production 영역이 주 서비스 경로다. 하단 Review, Research, Shadow는 별도의 지원 기능이며 자동으로 운영 예측을 변경하는 경로가 아니다. 모델 버전, 연구 후보명, 현재 가동/승격 상태는 이 메인 구조도의 범위에서 제외했다.

## Connections and Boundaries

### Serving and Evidence

하나의 산출물 카드 안에 두 역할을 나누었다.

- **Serving / public artifacts:** forecast, actual, alerts, metrics, reports. 카드의 delivery 쪽에 배치하고 `GitHub Actions -> GitHub Pages -> React / Vite dashboard` 연결을 이 영역에서 시작한다.
- **Retained evidence:** issue-time snapshots와 calibration stages. 하단 Review / Research / Shadow로 향하는 연결을 이 영역에서 시작한다. ETL state는 실측 확정 여부를 해석하는 운영 문맥이지 immutable issue-time snapshot 자체는 아니다.

**Arrows show logical delivery and evidence-consumption paths, not a deployment allowlist or access-control boundary.**

현재 `.github/workflows/deploy.yml`은 `data` branch를 `web/public`에 복원할 때 `.git`만 제외한다. Vite build에도 retained snapshots를 별도로 제거하는 repository 설정이 없다. 따라서 `web/public`에 보존된 snapshot 및 calibration 근거 일부도 정적 배포 패키지에 포함될 수 있다. 그림의 연결 분리는 주 사용 목적을 구별할 뿐, retained evidence가 비공개이거나 Pages 배포에서 제외된다는 뜻은 아니다.

운영 지표와 검토는 serving actuals/metrics도 함께 사용한다. 하단 연결은 모든 파일별 의존성을 나열한 것이 아니라 보존 근거를 읽는 대표 경로다.

### Scheduled Orchestration

TEPCO와 Weather만 Data sources에 둔다. Windows Task Scheduler/host orchestration/Docker ETL, GitHub Actions의 intraday와 build/deploy는 독립된 실행 제어 영역이다. 회색 점선 `scheduled runs`는 Data ingestion 진입점에 연결한다. 이는 pipeline 실행을 시작한다는 의미이며 모든 실행이 같은 historical fetch를 수행한다는 뜻은 아니다.

Historical ETL의 host orchestration은 데이터 복원, Docker ETL, publish와 workflow dispatch를 맡는다. Scheduled intraday는 `run_batch.py --status-only` 경로에서 관측/예측/산출물을 갱신한다. Docker ETL 컨테이너만 실행하는 것과 host의 전체 publish 절차는 구분된다.

### Production Detail

- Normalization은 JST 및 MW 기준을 다루며, historical TEPCO 품질 검사는 해당 수요 데이터의 완전성을 확인한다. 모든 입력원에 동일한 validator가 적용되는 것은 아니다.
- 저장된 호환 LightGBM 모델이 base/day-ahead quantile 예측을 생성한다. 당일 residual 보정과 보정 후 prediction interval은 별도 기능이다.
- Anomaly, metrics, reports는 예측 생성을 승인하는 직렬 gate가 아니다. 세 카드의 출력은 serving artifacts로 모이며, 보정된 예측에는 별도 직접 연결이 있다.
- Optional AI narrative는 일일 리포트 기능에만 속한다. LLM이 수요 예측이나 production 보정을 담당한다는 의미가 아니다.
- Review Bundle은 deterministic evidence 준비와 selective read-only 검토를 지원한다. Replay 계산 및 모델 연구와는 역할이 다르다.
- Isolated Shadow Evaluation은 별도 Docker 저장 공간에서 예측과 실측을 연결한다. Production forecast로 쓰는 경로는 없다.

## Repository Evidence

| Architecture capability | Implementation / configuration |
| --- | --- |
| TEPCO / weather ingestion | `python/etl/fetch_tepco.py`, `fetch_today.py`, `fetch_weather.py` |
| Normalization / quality / cache | `python/tepc_parser.py`, `python/etl/quality_gate.py`, `run_batch.py` |
| Feature preparation / forecast engine | `python/forecast/feature_builder.py`, `lgbm_model.py` |
| Calibration / intraday / intervals | `python/forecast/same_regime_calibration.py`, `adjustment.py`, `intraday_correction.py`, `interval_calibration.py`, `rolling_interval_calibration.py` |
| Anomaly / metrics / reports | `python/anomaly/detector.py`, `python/eval/forecast_accuracy.py`, `forecast_vintage_accuracy.py`, `daily_operation_report.py`, `ai_daily_report.py` |
| Serving artifacts / retained evidence | `python/etl/run_batch.py`, `scripts/publish_data_branch.py` |
| Local orchestration | `scripts/register_local_etl_task.ps1`, `local_etl.ps1`, `docker-compose.yml` |
| Intraday / static delivery | `.github/workflows/intraday.yml`, `deploy.yml`, `etl.yml` |
| Dashboard | `web/src/App.tsx`, `web/src/hooks/useFetch.ts`, `web/vite.config.ts` |
| Review Bundle / read-only validation | `python/eval/review_bundle/`, `python/eval/operational_replay.py` |
| Research / isolated shadow | `python/eval/intraday_challenger/`, `docker/shadow.Dockerfile`, `docker-compose.yml` |

Paths are relative to repository root; abbreviated filenames in a row share the preceding directory.

## Rendering and Scope

HTML/CSS Grid와 Flexbox가 주요 영역을 배치하며, inline SVG는 아이콘과 카드 경계에 맞춘 연결선을 표현한다. Production을 중앙에 강조하고 data sources와 delivery를 양옆에 배치했다. Review, Research, Shadow는 하단의 별도 지원 영역이다.

외부 폰트/CDN/이미지/API 없이 오프라인 Chromium에서 HTML을 렌더하여 PNG로 export했다. 텍스트 overflow, 카드 overlap 및 관계없는 카드의 connector 관통 검사에서 문제가 없었다. PNG를 직접 확인했고, 1000 px 폭 축소에서도 주요 제목과 서비스 경로를 확인했다. 작은 provenance/보조 문구는 고해상도 원본에서 읽는 것이 적합하다.

README용 PNG는 `docs/assets/tokyo-grid-ems-architecture.png` 한 파일로 관리한다. 편집용 HTML과 이 설명 문서는 `docs/architecture/`에 둔다. 이전 이미지 버전은 Git history로 확인할 수 있다.

### Export

Repository root에서 Playwright와 Chromium이 설치된 로컬 환경으로 다음 예시를 실행한다. 렌더링은 외부 리소스를 필요로 하지 않으며, PNG는 HTML의 `#poster` 요소를 캡처한다.

```javascript
const { chromium } = require('playwright');
const { pathToFileURL } = require('node:url');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({
    viewport: { width: 1640, height: 1160 },
    deviceScaleFactor: 2,
  });
  await page.goto(pathToFileURL(path.resolve(
    'docs/architecture/tokyo-grid-ems-architecture.html'
  )).href);
  await page.waitForFunction(() => window.architectureReady === true);
  await page.locator('#poster').screenshot({
    path: 'docs/assets/tokyo-grid-ems-architecture.png',
  });
  await browser.close();
})();
```

Forecast, ETL, 모델, workflow, scheduler, serving policy와 Docker runtime은 이미지 갱신 범위에 포함되지 않는다.
