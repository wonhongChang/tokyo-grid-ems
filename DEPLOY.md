# GitHub Pages 배포 가이드

## 전제 조건

- GitHub 계정
- **Public 저장소** (Private은 GitHub Pro 필요)
- 로컬에서 모든 코드가 정상 동작 확인된 상태

---

## 1단계: 저장소 생성 및 코드 푸시

```bash
# GitHub에서 새 저장소 생성 후
git init
git remote add origin https://github.com/<USERNAME>/<REPO_NAME>.git
git add .
git commit -m "initial commit"
git push -u origin main
```

> `web/public/` 폴더(JSON, parquet 캐시 포함)도 함께 커밋해야 합니다.  
> 첫 배포 시 이 데이터로 바로 표시됩니다.

---

## 2단계: GitHub Pages 활성화

1. 저장소 → **Settings** → **Pages**
2. **Source**: `GitHub Actions` 선택 후 저장

---

## 3단계: Actions 권한 확인

1. 저장소 → **Settings** → **Actions** → **General**
2. **Workflow permissions**: `Read and write permissions` 선택
3. `Allow GitHub Actions to create and approve pull requests` 체크

> 워크플로가 ETL 결과를 `web/public/`에 커밋하고 push하기 때문에 쓰기 권한이 필요합니다.

---

## 4단계: 첫 배포 (수동 실행)

1. 저장소 → **Actions** → **ETL + Deploy**
2. **Run workflow** → `main` 브랜치 → **Run workflow**
3. 약 2~3분 후 완료
4. Pages URL 확인: `https://<USERNAME>.github.io/<REPO_NAME>/`

---

## 워크플로 구조

| 워크플로 | 실행 시각 | 역할 |
|---|---|---|
| `ETL + Deploy` | 매일 01:30 JST | TEPCO 전일 CSV 다운로드 → ETL → 배포 |
| `Intraday Update` | 2시간마다 | 당일 실시간 데이터 갱신 → 배포 |

---

## 확인 사항

```
Actions 탭 → 워크플로 실행 → 각 Step 로그 확인
```

자주 발생하는 문제:

| 오류 | 원인 | 해결 |
|---|---|---|
| `Permission denied` on git push | Workflow permissions 미설정 | 3단계 재확인 |
| 빌드 후 404 | Pages Source가 `Actions`가 아님 | 2단계 재확인 |
| `ModuleNotFoundError` | requirements.txt 누락 패키지 | 로컬에서 `pip install` 후 requirements.txt 업데이트 |
| 차트 데이터 없음 | `web/public/` 미커밋 | `git add web/public/` 후 재커밋 |

---

## Vite BASE_URL

워크플로에서 `VITE_BASE_PATH: /${{ github.event.repository.name }}/` 로 자동 설정됩니다.  
저장소 이름을 바꾸면 이 값도 자동으로 바뀌므로 별도 수정 불필요합니다.
