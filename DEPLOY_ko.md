# GitHub Pages 배포 가이드

언어: [English](DEPLOY.md) / [日本語](DEPLOY_ja.md)

## 사전 준비

- GitHub 계정
- Public repository, 또는 private Pages를 지원하는 GitHub 플랜
- GitHub Pages Source를 **GitHub Actions**로 설정
- Actions workflow permissions를 **Read and write permissions**로 설정
- 로컬 historical ETL용 Docker Desktop 설치

`web/public/` 아래의 생성 데이터는 `main`에 커밋하지 않습니다. 생성 데이터는 `data` 브랜치에 publish하고, Pages 배포 workflow가 이 브랜치를 복원한 뒤 Vite 앱을 빌드합니다.

## 운영 구조

TEPCO 월별 ZIP 다운로드는 GitHub-hosted runner에서 HTTP 403이 발생할 수 있으므로 로컬 PC의 Docker ETL로 처리합니다. 당일 intraday 갱신은 GitHub Actions에서 계속 처리합니다.

```text
Windows 작업 스케줄러
  -> scripts/local_etl.ps1 -Publish
    -> origin/data 를 web/public 로 복원
    -> Docker ETL 및 OpenAI 일일 리포트 생성
    -> web/public 을 origin/data 로 push
    -> Deploy Only workflow 호출
    -> Intraday Update workflow 호출
```

## Workflows

| Workflow | Trigger | 역할 |
|---|---|---|
| `Manual ETL + Deploy` | 수동 실행만 | 비상용 historical ETL. GitHub-hosted runner에서 TEPCO ZIP fetch가 막힐 수 있으므로 schedule은 비활성화했습니다. |
| `Intraday Update` | 스케줄 + 수동 | 당일 실측, 예측, status 갱신 및 배포. 로컬 ETL 스크립트가 publish/deploy 후 호출하여 아침 차트를 최신 당일 CSV 기준으로 한 번 더 갱신합니다. |
| `Deploy Only` | 수동 dispatch | ETL 없이 `origin/data`를 복원하고 Vite 앱만 빌드/배포. 로컬 ETL 스크립트가 data publish 후 호출합니다. |

## 로컬 Docker ETL

첫 실행:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\local_etl.ps1 -Publish -Build
```

평소 실행:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\local_etl.ps1 -Publish
```

publish 전에는 로컬 스크립트가 `web/public`을 검증합니다.

- `status.json`이 `availability: ok`여야 합니다.
- `coverageTo`가 어제 날짜 이상이어야 합니다.
- 어제 `actual/YYYY-MM-DD.json`에 실제 관측 24시간이 있어야 합니다.
- 오늘/내일 forecast JSON에 24시간 예측 행이 있어야 합니다.

Docker fetch 단계는 TEPCO의 지연 수정분을 흡수하기 위해 최근 3일 JST CSV를 `data/raw`에서 덮어씁니다.

권장 로컬 스케줄, 07:30 / 08:30 / 09:30 JST 등록:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_local_etl_task.ps1
```

스케줄 삭제:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\unregister_local_etl_task.ps1
```

## 모니터링

- Windows 작업 스케줄러: `LastRunTime`, `LastTaskResult`, `NextRunTime` 확인
- 로컬 로그: `logs/local_etl/*.log`
- 로컬 상태 JSON: `web/public/ops/local_etl_status.json`
- GitHub: `data` 브랜치 최신 커밋과 `Deploy Only` workflow 결과 확인
- Docker Desktop: ETL은 배치 작업이므로 완료 후 `Exited` 상태가 정상

## 문제 해결

| 문제 | 원인 | 해결 |
|---|---|---|
| Actions에서 TEPCO 월별 ZIP이 `403` 반환 | GitHub-hosted runner IP가 TEPCO에서 차단됨 | 로컬 Docker ETL 실행: `scripts\local_etl.ps1 -Publish` |
| Deploy Only 호출 실패 | 로컬에서 GitHub token을 찾지 못함 | `GH_TOKEN` 또는 `GITHUB_TOKEN` 설정, GitHub CLI 로그인, 또는 Actions에서 `Deploy Only` 수동 실행 |
| 로컬 ETL 후 Intraday 호출 실패 | 로컬 GitHub token 없음 또는 GitHub Actions dispatch 실패 | Actions에서 `Intraday Update`를 수동 실행하고 `logs/local_etl/*.log` 확인 |
| OpenAI 리포트가 fallback | API 키 누락, 인증 실패, timeout | `.env`와 `logs/local_etl/*.log` 확인 후 로컬 ETL 재실행 |
| 차트가 오래된 데이터 표시 | `data` 브랜치는 갱신됐지만 Pages 배포가 안 됨 | `Deploy Only` 수동 실행 |
| data push 권한 오류 | 호스트 Git 인증 없음 | Windows GitHub 인증 재설정 |

## Vite Base Path

workflow는 `VITE_BASE_PATH: /${{ github.event.repository.name }}/`를 설정합니다. 저장소 이름을 바꾸면 base path도 저장소 이름을 따라갑니다.
