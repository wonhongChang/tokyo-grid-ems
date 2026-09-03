# 모델 점검 기록

정기 모델 점검에서 확인한 근거, 사전에 고정한 합격 기준, 승격 판단과 남은 위험을 날짜순으로 기록합니다.

이 문서는 [모델 개선 이력](../model-improvements/README.md)과 성격이 다릅니다. 점검 결과 코드 변경이나 승격이 필요하지 않을 수 있으며, 실제 변경이 채택된 경우에만 별도의 개선 문서를 작성합니다.

언어: [English](../../en/model-reviews/README.md) / [日本語](../../ja/model-reviews/README.md)

## 점검 목록

- [2026-09-03 v14-r2 운영 모델 점검](model-review-2026-09-03.md) - 완료. v14-r2를 임시 유지하되 상태를 `review_required`로 판단하고, calibration 정합성 수정과 contract별 health 분리, v15 Challenger 실험을 우선 과제로 정리했습니다.
- [2026-08-18 모델 운영 점검](model-review-2026-08-18.md) - 완료. 8월 14~18일 단계 복원 결과 v11을 임시 유지하되, raw q50·오전 guard·잔차 반전 후보의 즉시 replay를 결정했습니다.
- [2026-08-11 모델 운영 점검](model-review-2026-08-11.md) - 완료. v11 유지, v13 승격 거부, replay를 통과한 비영업일 오전 guard만 채택했습니다.
