# Tokyo Grid EMS 운영 관측

예측을 언제 실행하고 어떤 데이터를 채택할지는 기존 ETL과 발행 정책이 결정한다.
이 스택은 그 결정을 바꾸지 않고 **어떤 단계가 늦었는지, 어느 입력이 실패했는지,
실제로 공개된 자료가 얼마나 오래됐는지** 조사하는 별도 도구다.
Trace 유실은 가능하다. Trace가 없다고 작업 실패로 보거나, Trace가 있다고 봉인·배포 성공으로 보지 않는다.

## 빠른 시작

저장소 루트에서 PowerShell과 Docker Desktop의 Linux 엔진을 사용한다.

```powershell
pwsh -NoProfile -File ops/observability/stack.ps1 Start
pwsh -NoProfile -File ops/observability/stack.ps1 Verify
```

- Grafana: <http://127.0.0.1:3300>. 계정은 `admin`, 최초 비밀번호는
  `ops/observability/.local/admin_password`. 이 파일을 로그·이슈·채팅에 붙이지 않는다.
  기존 DB의 비밀번호를 바꾸려면 Grafana의 보안 메뉴를 사용한다. 시크릿 파일만 바꿔서는 기존 계정이 바뀌지 않는다.
- OTLP/HTTP: `http://127.0.0.1:4318`. Tempo와 Prometheus 포트는 호스트에 공개하지 않는다.
  Grafana Explore에서 **Traces** 및 **Metrics**를 선택한다. 예:
  `{ resource.service.name = "tgems-public" && name = "public.observe" }`.
- 독립 Compose project는 `tgems-observe`다. 별도 env 파일을 사용하며 운영 `.env`, Git credential,
  Docker socket, 생산 데이터 디렉터리를 마운트하지 않는다. 중지는 `stack.ps1 Stop`,
  재시작·readiness 확인은 `stack.ps1 Restart`, 컨테이너 제거는 `stack.ps1 Down`.
  **Down은 볼륨을 보존한다.** `down -v`는 롤백 명령이 아니다.

### 공개 자료를 실제로 관측하기

격리된 Python 환경에 [관측용 의존성](requirements.txt)을 설치한다. 모델 환경이나 기본 ETL 이미지에 설치하지 않는다.

```powershell
python -m venv tmp/otel-public
& tmp/otel-public/Scripts/python.exe -m pip install -r ops/observability/requirements.txt
& tmp/otel-public/Scripts/python.exe -m python.observability.public --live-public --watch --cycles 3
```

Windows용 시간대 데이터도 관측용 의존성에 포함돼 있다.
`--watch`는 **수동 foreground** 관측이다. 한 번만 읽으려면 플래그를 생략한다.
이 예시는 상시 작업을 설치하기 전의 일회성 진단으로, 세 번 수집하고 종료한다. 이미 상시 Reader가 있다면 이 명령 대신 `reader-task.ps1 Status` 또는 Grafana를 사용한다.
Ctrl+C로 중지해도 ETL은 계속된다. 호스트 환경변수나 운영 Git 갱신이 필요 없다.
각 tick에서 익명 HTTPS로 공개 data SHA를 확인하고, 해당 SHA의 허용된 상태·실측·품질 JSON만 읽는다.
새 SHA이면 이전 캐시를 폐기한다. 원격 확인 실패 시 로컬 Git이나 이전 값을 최신으로 대체하지 않는다.
각 수집 후 60초를 쉬며 Prometheus는 15초마다 스크레이프한다. 기본 대시보드는 최근 6시간, 30초 refresh, JST다.
기존 `--live-public` 없는 모드는 별도 opt-in한 로컬 `origin/data` 진단용이며 두 reader를 동시에 실행하지 않는다.

- [Champion Quality](http://127.0.0.1:3300/d/tgems-quality): 공개 data 커밋 기준 최근 확정 대상일의 24시간 지표이다. MAE·RMSE·band bias는 MW, WAPE는 비율을 %로 표시한다. intraday 때 날짜별 품질이 그대로여도 정상이다.
- [System Operations](http://127.0.0.1:3300/d/tgems-ops): GitHub Pages 배포 성공 기록의 시각, data 커밋의 상태 생성 시각, 실제 Pages URL에서 확인한 상태 생성 시각을 구분한다. 배포 성공은 현재 방문자에게 동일 내용이 보인다는 증거가 아니다. 배포 시각은 고정 저장소의 최근 github-pages 배포 3개의 공개 status에서 성공만 읽고 6분간 캐시한다. 확인할 수 없으면 unavailable이다.
- [Data Acquisition](http://127.0.0.1:3300/d/tgems-input): 같은 수집에서 Pages/data 상태 시각 일치 여부를 직접 확인한다. 0은 불일치이지 곧바로 발행 실패는 아니다. 관측이 멈추면 현재 품질은 freshness gate를 통과하지 못한다. 과거 차트의 마지막 점과 현재값을 혼동하지 않는다.

### Windows 상시 Reader

등록명은 **TokyoGridEMS Observability Public Reader**다. 등록한 사용자가 로그인하면 제한 권한으로 실행하며 암호를 저장하지 않는다. 기존 EMS 예약과 Docker 엔진의 시작 설정은 변경하지 않는다. PC가 꺼져 있거나 사용자가 로그인하지 않으면 수집하지 않는다. Docker가 늦게 켜지면 reader가 대기한다. 관측 스택 4개 컨테이너는 Docker가 돌아오면 `unless-stopped` 정책으로 복구된다. 명시적으로 중지한 서비스까지 켜는 정책은 아니다.

최초 설치 시 저장소 루트에서 안정적인 전용 venv를 만든다(위 임시 진단용 venv와 별개).

```powershell
python -m venv ops/observability/.local/reader-venv
& ops/observability/.local/reader-venv/Scripts/python.exe -I -m pip --isolated install -r ops/observability/requirements.txt
pwsh -NoProfile -File ops/observability/reader-task.ps1 Install
```

| 작업 | `reader-task.ps1` 인자 | 결과 |
|---|---|---|
| 현재 상태 | `Status` | 등록 상태, 실행 결과, 다음 트리거, 기록한 PID의 생존 여부, 마지막 공개 read/heartbeat(Unix 초) |
| 시작·자동 실행 재개 | `Start` 또는 `Enable` | 전용 작업 활성화 후 시작 |
| 정상 재시작 | `Restart` | 현재 generation에만 종료 요청 후 재실행 |
| 중단·자동 실행 해제 | `Stop` 또는 `Disable` | 정상 종료 대기, 트리거 비활성화. 30초 경과 시 전용 작업만 강제 중지 |
| 등록 삭제 | `Remove` | 해당 경로·소유 표시가 일치하는 작업만 제거. Prometheus·Grafana 데이터는 보존 |

로그인 트리거와 3분 간격 복구 트리거는 **같은 작업**이다. 실행 중에는 `IgnoreNew`로 무시하므로 추가 프로세스나 API 호출을 만들지 않는다. Windows가 수동 시작 프로세스의 비정상 종료를 재시도하지 않는 경우도 있어 1분 오류 재시도 단독에 의존하지 않는다. 별도 수동 reader도 OS 잠금으로 거부한다(종료 코드 73). 프로세스 종료 시 잠금이 해제되므로 lock 파일을 지우지 않는다. 새 설치 위치로 이전할 때는 기존 위치에서 먼저 Remove한다.

스케줄러의 `LastStart`·`LastTaskResult`는 중복 트리거 요청 시에도 바뀔 수 있다. 장애 판정은 이 값 하나가 아니라 `RecordedProcessAlive`, generation의 `started`, 로컬 `heartbeat`, Grafana의 실제 수신 시각을 함께 본다. Docker Desktop이 로그인 시 자동 기동하는지는 PC 설정에 달려 있다. 엔진이 꺼져 있다면 Reader가 이를 강제로 시작하지 않는다.

전용 인터프리터는 `-I -B`로 실행한다. Windows Job Object로 프로세스 커밋 메모리 256 MiB와 시스템 CPU 10% 상한을 적용한다. 적용할 수 없으면 무제한으로 실행하지 않는다. 고정 공개 주소·응답 크기 제한·동일 SHA 캐시를 사용하며, 1회 읽은 후 60초 대기한다. 한 주기에 공개 요청은 최대 11회, 응답 본문 읽기 상한의 합은 8 MiB 미만이다(TLS·헤더 제외). 동일 SHA/날짜에서는 raw 파일을 다시 받지 않으며, 공개 배포 API는 6분마다 최대 4회다. Collector가 닫혀 있으면 공개 입력을 다시 읽지 않고 loopback만 10/20/40/60초 간격으로 확인한다. 외부 API 장애, PC 절전, Collector/Prometheus 중단 구간을 소급해 채우지 않는다. `logs/observability/public-reader/status.json`에는 해당 generation의 공개 HTTPS 시도 수·응답 본문 바이트도 남으며, 이 파일 자체는 전달 확인 영수증이 아니다.

[Observability Health](http://127.0.0.1:3300/d/tgems-health): 최근 공개 read 성공 + 90초 미만 heartbeat는 **Receiving**, 90~180초는 **Delayed**, 읽기 실패는 **Source read failed**. Collector scrape 실패·180초 이상 미수신은 **No recent delivery**다. Prometheus 자체 장애는 Grafana datasource 오류이며 모델 실패로 간주하지 않는다. 마지막 성공 시각은 최근 24시간 중 실제 수신한 성공 시각이다. 품질에는 0을 대입하지 않는다. Reader가 돌아가는 동안 데이터 SHA가 그대로이면 관측 시각만 전진하는 것이 정상이다.

실제 사용자 로그·상태·가상환경·비밀번호·TSDB·trace는 Git 대상이 아니다. 공개 reader는 운영 ETL 내부 계측을 활성화하지 않는다.

새 clone에 배포할 때는 작업 스크립트만 복사하지 않는다. `python/observability`의 공개 reader·runtime·contract·로컬 로그 모듈, 관측 전용 `requirements.txt`, 이 디렉터리의 스택 설정과 Grafana provisioning, 대시보드 생성기·생성 JSON, Windows 진입점과 테스트가 함께 있어야 한다. 가상환경·예약 작업 XML·사용자별 절대 경로는 클론에서 재생성한다. 작업 제거는 등록만 없애며 시계열 볼륨이나 기존 연구 데이터를 삭제하지 않는다.

### ETL과 발행의 선택적 계측

[observe.ps1](observe.ps1)은 기존 CLI 하나를 새 프로세스에서 한 번 호출한다. 필수 스케줄에 설치하지 않는다.
호스트에는 기존 업무 의존성과 선택적 SDK가 필요하다. SDK가 없으면 업무 CLI는 원래대로 실행된다.
기존 실행 스크립트와 공유 모듈에는 계측 코드를 삽입하지 않았다.

| 선택 가능한 명령 | 실제 동작과 관측 경계 |
| --- | --- |
| `restore` | 실제 Git fetch와 remote probe 후 `web/public`을 복원/정리한다. 읽기 전용이 아니며 재시도를 추가하지 않는다. |
| `fetch` | 실제 TEPCO 월별 ZIP 취득. 다운로드와 파일 신규 생성/덮어쓰기 유무를 구분한다. |
| `batch` | 실제 ETL. 파싱·품질, 기상·캐시, 모델 로딩·feature·추론, 보정·freeze, forecast 쓰기와 snapshot/origin 저장을 관측한다. `--status-only`는 기존 intraday 경로다. |
| `validate` | 기존 발행 전 검증. `--public-dir`로 지정된 디렉터리에서 읽는다. |
| `publish`, `dispatch` | **실제 Git publish 또는 Actions 요청**이다. 요청 수락은 Pages 반영과 다르다. |

**운영 입력에 위 명령을 사용해 설치를 시험하지 않는다.** batch/fetch는 파일을 바꾸며, 기존 설정에 따라
batch가 유료 AI 리포트를 호출할 수 있다. publish/dispatch도 실제 부작용이 있다. 설치 확인에는 아래의 오프라인 테스트를 사용한다.
`-NoTelemetry`는 해당 수동 호출의 계측만 끈다. **dry-run 스위치가 아니다.** 업무까지 중단하고 싶으면 명령을 실행하지 않는다.

수동 Docker 사용 시 기존 로컬 ETL 이미지를 먼저 식별한다. [별도 Dockerfile](manual-etl.Dockerfile)은
그 이미지를 기반으로 `/opt/tgems-observer`를 기존 패키지 경로 뒤에 추가한다.
운영 이미지 태그·내용을 바꾸지 않으며 사용 직전 기준 이미지 ID와 Python/ML 패키지 일치를 확인한다.

```powershell
docker build --pull=false --build-arg ETL_BASE=tokyogridems-etl:latest -t tgems-manual-observed-etl:1 -f ops/observability/manual-etl.Dockerfile .
```

`observe.ps1 -Docker`는 **승인된 수동** batch/fetch만 호스트 부모 span 아래 이어준다.
업무 컨테이너는 기존 Compose의 운영 데이터/환경을 사용하지만 관측 스택과 네트워크를 공유하거나
스택 시작에 의존하지 않는다. Docker Desktop에서 `host.docker.internal:4318`을 사용한다.
새 Linux 호스트에서 이 경로가 localhost listener까지 도달하는지는 **재검증**한다.
연결을 위해 OTLP를 공개 인터페이스에 바인딩하지 않는다.

## 신호 및 대시보드

| 대시보드 | 읽는 신호 | 읽어서는 안 되는 의미 |
| --- | --- | --- |
| System Operations | ETL·Git·dispatch span, Pages status age, 공개 관측 시각 | Git 성공이 배포 성공을 증명하지 않는다. |
| Data Acquisition | TEPCO/기상 fetch 성공/실패, 파싱·품질 경고, 명시된 observed/fallback 슬롯 | 슬롯 시각은 다운로드 시각이 아니다. Pages timestamp 일치는 원격 입력 hash 일치가 아니다. |
| Forecast Pipeline | 모델 로드·추론·보정 시간, freeze/snapshot/forecast 쓰기 | 호출됐다는 것과 가드가 실제로 예측을 수정했다는 것은 다르다. |
| Champion Quality | 확정 공개 일별 MAE·RMSE·WAPE, 표본 수, 시간대별 MAE·signed bias, 평가일 | Published latest-value만 표시한다. vintage/동일 run stage/후보와 섞지 않는다. |
| Observability Health | scrape 상태, trace exporter queue/failure, TSDB blocks, projector 상태 | 실패 counter 없음은 유실 0의 증거가 아니다. TSDB blocks는 전체 디스크 사용량이 아니다. |

- OTLP 신호는 [유한 어휘](../../python/observability/contract.py)로 제한한다. 업무 span에서
  `tgems_stage_calls_total`과 `tgems_stage_duration_seconds_bucket`를 Collector가 생성한다.
  같은 counter를 SDK에서 다시 증가시키지 않는다. outcome은 ok/failed/skipped/degraded/unknown.
  `source.fetch`는 TEPCO, `weather.fetch`는 기상 공급자 호출이다. 성공률은 **계측된 호출**의 비율이지 전수 수집률이 아니다.
- 공개 gauge 계약은 [public.py](../../python/observability/public.py)의 `NAMES`, [허용 목록](collector.yml),
  [대시보드 쿼리](dashboards.py)를 함께 갱신한다. Timestamp는 Unix seconds, 지연은 s, 오차는 MW,
  WAPE는 %가 아닌 ratio다. label은 고정 basis/window/band/kind뿐이다.
- 품질은 같은 public Git revision의 `.etl_state.json.okDates`, 전일까지의 최신 확정일,
  방법론·LGBM family·포함 여부·24시간 모집단을 확인한다. 시간대별 값은 일간 리포트의
  날짜·timezone·family·요약값·밴드별 표본 수까지 일치해야 표시한다. 미확인 값은 0이 아니라 결측이다.
  interval coverage/width는 이 확정·공개 모집단에 대응하는 증거가 없어 미제공이다.
- 업무 span/로컬 JSONL은 trace ID·span ID로 연결한다. 프로세스 간에는 검증된 W3C traceparent와
  별도 상관 ID만 전달한다. 이 ID들은 metric label이나 업무 JSON에 쓰지 않는다.
  오류 메시지/stack, 원시 입력·예측, URL, 파일명, env, 모델·후보 identity, 연구 결과는 수집하지 않는다.
- 로그는 `logs/observability/`의 새 JSONL만 회전한다. 기존 업무 로그는 전달하지 않는다.
  큐 포화·파일 잠금·ENOSPC 때 계측 이벤트는 버릴 수 있다. 엄격한 감사·재현성 자료로 사용하지 않는다.
- 공개 상태 시각의 차이는 조사를 시작할 신호일 뿐이다. 입력 동일성, 후보 상태, 공식 발행 여부는 원래의 기록으로 검증한다.
  Shadow·비공개 평가·GitHub-hosted Actions는 이 reader로 계측하지 않는다.

## 보존, 보안 및 장애 대응

Tempo trace 14일, Prometheus 30일 또는 2GB 중 먼저 도달하는 제한을 사용한다.
TSDB WAL/임시 파일은 이 용량과 별개다. JSONL은 최대 약 8MiB × 4, UTC 일 경계 또는 크기 회전,
7일 초과분은 **다음 쓰기에서** 삭제된다. 서비스별 Docker 로그는 4MiB × 2다.
전용 볼륨도 Docker Desktop과 물리 디스크를 공유한다. 사용량은 전용 볼륨 및 호스트 여유 공간을 모두 확인한다.
Tempo는 시간 보존이지 하드 바이트 quota가 아니다. 포화 시 수집기를 중단하고 용량부터 확보한다.
운영 원본, 평가 봉인, 다른 프로젝트의 볼륨을 지우지 않는다.

Grafana 인증/localhost 포트/전용 backend/allowlist는 기본 방어다. OTLP listener 자체는 localhost용으로
인증하지 않으므로 **같은 PC의 악성 프로세스를 격리하는 보안 경계는 아니다**.
원격 서버에서는 그대로 외부에 열지 말고 터널 또는 TLS·인증·방화벽을 먼저 설계한다.
Prometheus rule은 경보 상태만 제공하며 외부 알림·SaaS는 설정하지 않는다.

Collector/Tempo가 내려가면 trace가 유실될 수 있다. 이때 업무를 재실행하지 말고
`Verify` → Health 대시보드 → 해당 서비스의 전용 로그 순서로 확인한다.
Grafana/Prometheus 중단은 예측과 독립이다. 문제가 지속되면 **일반 기존 CLI로 복귀**하고 projector를 중지한다.
SDK의 비동기 batch 큐는 512, 로컬 로그 큐는 256이다. 종료 flush 대기는 최대 약 650ms로 제한하며,
전체 프로세스 시작·종료·OS 지연 상한을 보장하지 않는다.

## 재현 및 변경 관리

```powershell
python -m pytest -q tests/test_observability.py tests/test_observability_cli.py tests/test_observability_canary.py tests/test_observability_log_contract.py tests/test_observability_public_source.py tests/test_public_reader_service.py
python ops/observability/dashboards.py
python -m ops.observability.verify --require-public
```

통합 테스트는 운영 환경이 아닌 별도 시험 환경에서 프로젝트 개발 의존성과 관측용 SDK를 설치한 뒤 실행한다.
fixture span은 업무 counter와 운영 TraceQL에서 제외한다. 대시보드 JSON은 생성 소스와 함께 관리한다.
`verify --require-public`은 로컬 스택과 실행 중인 reader를 확인하는 명령이다. 모델 성능이나 배포를 승인하지 않는다.
Loki·Mimir·외부 알림은 현재 사용하지 않는다.
