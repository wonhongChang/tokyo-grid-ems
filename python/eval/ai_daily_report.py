"""Build daily operation analysis reports.

The generator always produces a deterministic fallback report from the public
JSON artifacts.  When OPENAI_API_KEY is available it can ask OpenAI for the
narrative analysis layer, while keeping deterministic metrics and input
references owned by this script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TIMEZONE = "Asia/Tokyo"
JST = ZoneInfo(TIMEZONE)
SCHEMA_VERSION = "1.0.0"
PROMPT_VERSION = "fallback_rules_v1"
OPENAI_PROMPT_VERSION = "openai_ops_report_v2"
OPENAI_DEFAULT_MODEL = "gpt-5.4-mini"
OPENAI_DEFAULT_LOCALIZATION_MODEL = "gpt-4o-mini"
OPENAI_DEFAULT_LOCALES = "ko,en,ja"
OPENAI_DEFAULT_MAX_CALLS_PER_RUN = 2
OPENAI_DEFAULT_ANALYSIS_TIMEOUT_SECONDS = 90
OPENAI_DEFAULT_LOCALIZATION_TIMEOUT_SECONDS = 180
REPORT_TYPE = "ai_daily_operation_report"

FEATURE_CATALOG = [
    "intraday_correction.business_type_transition_prior",
    "intraday_correction.business_type_transition",
    "intraday_correction.positive_residual_mitigation",
    "intraday_correction.negative_residual_recovery_damping",
    "intraday_correction.day_boundary_carryover",
    "intraday_correction.day_level_scale",
]

MESSAGES = {
    "ko": {
        "headline_model_better": "모델이 TEPCO보다 일일 오차를 낮췄습니다.",
        "headline_tepco_better": "TEPCO가 일일 정확도에서 우세했습니다.",
        "headline_close": "모델과 TEPCO의 일일 성능이 비슷했습니다.",
        "headline_mixed": "평균 오차와 대형 오차 리스크가 엇갈렸습니다.",
        "headline_insufficient": "비교 가능한 시간이 부족합니다.",
        "summary_template": (
            "비교 가능 시간은 {hours}시간이며, 모델 MAE는 {model_mae}, "
            "TEPCO MAE는 {tepco_mae}입니다. WAPE는 모델 {model_wape}, "
            "TEPCO {tepco_wape}로 집계되었습니다."
        ),
        "fallback_note": "이 리포트는 OpenAI 호출 없이 deterministic JSON만으로 생성한 fallback 해설입니다.",
        "no_calibration": "해당 날짜의 operational-calibration JSON이 없어 보정 레이어 가동 여부는 직접 확인하지 못했습니다.",
        "timeline_limit": "현재 공개 JSON은 최종 실행분 중심이라 중간 intraday 실행 타임라인은 완전히 복원할 수 없습니다.",
        "snapshot_limit": "intraday 중간 실행은 operational-calibration snapshot 기준으로 제한적으로 복원합니다.",
        "no_major_hypothesis": "정량 지표에서 특정 원인을 강하게 지목할 만한 패턴은 아직 제한적입니다.",
        "wape_missing_summary_template": (
            "비교 가능 시간은 {hours}시간이며, 모델 MAE는 {model_mae}, "
            "TEPCO MAE는 {tepco_mae}입니다. 이 날짜의 deterministic 일일 리포트에는 "
            "WAPE가 아직 기록되지 않았습니다."
        ),
        "operation_missing_summary": "아직 일일 운영 리포트가 없어 AI 리포트를 생성할 수 없습니다.",
        "operation_missing_limitation": "operationReport가 아직 생성되지 않았습니다.",
        "diagnostics_missing": "해당 날짜의 daily-diagnostics JSON이 없어 내부 피처 근거는 제한적입니다.",
        "no_major_explanation": "지표상 특정 시간대 또는 피처 그룹으로 원인을 좁히기 어렵습니다. 추가 운영 데이터가 쌓인 뒤 재평가합니다.",
        "recommendation_suggestion_template": "{title} 가설을 기준으로 {target}의 영향도를 재검토합니다.",
        "recommendation_expected": "반복되는 시간대/영업형태 조건에서 MAE, WAPE, RMSE가 함께 개선되는지 확인합니다.",
        "recommendation_risk": "단일 날짜의 패턴을 과하게 반영하면 다른 계절/요일에서 과보정될 수 있습니다.",
        "recommendation_validation": "최근 2~4주 replay와 백테스트에서 TEPCO 대비 WAPE, RMSE, 최대 오차를 함께 비교합니다.",
        "operator_autoapply": "featureRecommendations는 검토 후보이며 자동 적용되지 않습니다.",
        "feature_catalog_note_template": "운영 보정 신호 카탈로그: {catalog}",
        "cool_lag_title": "전날 lag 과열과 기온 하락이 동시에 관측되었습니다.",
        "cool_lag_explanation": "최근 같은 영업형태 평균 대비 lag_24h가 높고, 전날 대비 기온이 내려간 regime입니다. lag 관성이 수요 스케일을 높게 유지했을 가능성이 있습니다.",
        "weather_delta_title_template": "{label} 구간의 기상 변화와 모델 bias가 맞물렸습니다.",
        "weather_delta_explanation": "기온/냉방 부하 변화 방향과 모델 bias가 같은 구간에서 관측되었습니다. 해당 구간은 기상 민감도 피처 검토 후보입니다.",
        "calibration_prior_title": "평일/비영업일 전환 prior 보정이 가동되었습니다.",
        "calibration_prior_explanation": "operational-calibration에 businessTypeTransitionPriorApplied 플래그가 기록되어 있습니다. 이는 실측 부족 구간에서 lag 과열을 보수적으로 낮추는 레이어입니다.",
        "calibration_transition_title": "실측 기반 영업형태 전환 보정이 가동되었습니다.",
        "calibration_transition_explanation": "operational-calibration에 businessTypeTransitionApplied 플래그가 기록되어 있습니다. 이는 당일 실측이 쌓인 뒤 영업형태 전환을 반영하는 레이어입니다.",
        "calibration_positive_title": "양수 잔차 전파 제한이 가동되었습니다.",
        "calibration_positive_explanation": "operational-calibration에 positiveResidualMitigationApplied 플래그가 기록되어 있습니다. 이는 새벽 양수 잔차가 ramp 구간을 과도하게 밀어 올리는 현상을 제한합니다.",
        "calibration_recovery_title": "음수 잔차 회복 댐핑이 가동되었습니다.",
        "calibration_recovery_explanation": "operational-calibration에 negResidualRecoveryDampingApplied 플래그가 기록되어 있습니다. 이는 회복 국면에서 과거 음수 잔차가 미래 예측을 과도하게 낮추는 것을 완화합니다.",
        "calibration_counter": "최종 실행분 JSON만으로는 하루 중간 실행 시점의 성공/실패를 단정할 수 없습니다.",
        "snapshot_history_title": "intraday 보정 실행 이력이 스냅샷으로 보존되었습니다.",
        "snapshot_history_explanation": "operational-calibration snapshot index에 중간 실행 이력이 남아 있어 최종 덮어쓰기 JSON만 볼 때보다 보정 레이어 흐름을 더 잘 추적할 수 있습니다.",
        "snapshot_counter_template": "스냅샷은 보존된 {count}회 실행만 설명하며, 삭제된 이전 실행은 복원하지 않습니다.",
        "snapshot_applied_counter_template": "보정이 실제로 적용된 스냅샷 수는 {count}회입니다.",
        "openai_failed_template": "OpenAI 리포트 생성에 실패해 fallback 해설로 대체했습니다: {error}",
    },
    "en": {
        "headline_model_better": "The model reduced daily error versus TEPCO.",
        "headline_tepco_better": "TEPCO was more accurate for the day.",
        "headline_close": "The model and TEPCO performed similarly.",
        "headline_mixed": "Average error and large-error risk were mixed.",
        "headline_insufficient": "There are not enough comparable hours.",
        "summary_template": (
            "{hours} comparable hours were available. Model MAE was {model_mae}, "
            "TEPCO MAE was {tepco_mae}. WAPE was {model_wape} for the model "
            "and {tepco_wape} for TEPCO."
        ),
        "fallback_note": "This report was generated from deterministic JSON without calling OpenAI.",
        "no_calibration": "No operational-calibration JSON was available for this date, so calibration-layer activity could not be directly verified.",
        "timeline_limit": "The public JSON mainly preserves the final run, so intermediate intraday execution history cannot be fully reconstructed.",
        "snapshot_limit": "Intermediate intraday runs are reconstructed only from retained operational-calibration snapshots.",
        "no_major_hypothesis": "The metrics do not yet isolate a strong single root cause.",
        "wape_missing_summary_template": (
            "{hours} comparable hours were available. Model MAE was {model_mae}, "
            "TEPCO MAE was {tepco_mae}. This deterministic daily report does not yet include WAPE."
        ),
        "operation_missing_summary": "The daily operation report is not available yet, so an AI report cannot be generated.",
        "operation_missing_limitation": "operationReport has not been generated yet.",
        "diagnostics_missing": "No daily-diagnostics JSON was available for this date, so internal feature evidence is limited.",
        "no_major_explanation": "The current metrics do not narrow the issue to a specific hour band or feature group. Re-evaluate after more operational data accumulates.",
        "recommendation_suggestion_template": "Review the impact of {target} based on the hypothesis: {title}",
        "recommendation_expected": "Check whether MAE, WAPE, and RMSE improve together under repeated hour-band and business-type conditions.",
        "recommendation_risk": "Overfitting a single-day pattern can cause over-correction in other seasons or day types.",
        "recommendation_validation": "Compare WAPE, RMSE, and max error against TEPCO using recent 2-4 week replay and backtests.",
        "operator_autoapply": "featureRecommendations are review candidates and are never applied automatically.",
        "feature_catalog_note_template": "Operational calibration signal catalog: {catalog}",
        "cool_lag_title": "Lag overheating and a temperature drop were observed together.",
        "cool_lag_explanation": "lag_24h was high versus recent same-business-type averages while temperature fell versus the previous day. Lag inertia may have kept the demand scale too high.",
        "weather_delta_title_template": "Weather change and model bias overlapped in the {label} band.",
        "weather_delta_explanation": "The direction of temperature/cooling-load change aligned with model bias in this band, making it a candidate for weather-sensitivity review.",
        "calibration_prior_title": "The business-type transition prior was applied.",
        "calibration_prior_explanation": "operational-calibration recorded businessTypeTransitionPriorApplied. This layer conservatively lowers overheated lag when same-day observations are still scarce.",
        "calibration_transition_title": "Observed business-type transition calibration was applied.",
        "calibration_transition_explanation": "operational-calibration recorded businessTypeTransitionApplied. This layer reflects business-type transition after same-day observations accumulate.",
        "calibration_positive_title": "Positive residual propagation mitigation was applied.",
        "calibration_positive_explanation": "operational-calibration recorded positiveResidualMitigationApplied. This limits small overnight positive residuals from over-lifting ramp hours.",
        "calibration_recovery_title": "Negative residual recovery damping was applied.",
        "calibration_recovery_explanation": "operational-calibration recorded negResidualRecoveryDampingApplied. This prevents earlier negative residuals from pulling future forecasts too low during recovery.",
        "calibration_counter": "The final-run JSON alone cannot prove whether intermediate intraday runs succeeded or failed.",
        "snapshot_history_title": "Intraday calibration execution history was preserved as snapshots.",
        "snapshot_history_explanation": "The operational-calibration snapshot index retains intermediate runs, so the calibration-layer timeline is easier to trace than with final-run JSON alone.",
        "snapshot_counter_template": "The snapshots explain only the {count} retained runs; deleted older runs cannot be reconstructed.",
        "snapshot_applied_counter_template": "Calibration was actually applied in {count} retained snapshots.",
        "openai_failed_template": "OpenAI report generation failed, so fallback analysis was used: {error}",
    },
    "ja": {
        "headline_model_better": "モデルの日次誤差はTEPCOより低くなりました。",
        "headline_tepco_better": "この日はTEPCOの精度が優勢でした。",
        "headline_close": "モデルとTEPCOの日次性能はほぼ同等でした。",
        "headline_mixed": "平均誤差と大外しリスクが分かれました。",
        "headline_insufficient": "比較可能な時間が不足しています。",
        "summary_template": (
            "比較可能時間は{hours}時間です。モデルMAEは{model_mae}、"
            "TEPCO MAEは{tepco_mae}でした。WAPEはモデル{model_wape}、"
            "TEPCO {tepco_wape}です。"
        ),
        "fallback_note": "このレポートはOpenAIを呼び出さず、deterministic JSONのみから生成したfallback解説です。",
        "no_calibration": "この日のoperational-calibration JSONがないため、補正レイヤーの動作は直接確認できませんでした。",
        "timeline_limit": "公開JSONは主に最終実行分を保持するため、中間intraday実行履歴を完全には復元できません。",
        "snapshot_limit": "中間intraday実行はoperational-calibration snapshotに基づいて限定的に復元します。",
        "no_major_hypothesis": "定量指標から強い単一原因を特定できるパターンはまだ限定的です。",
        "wape_missing_summary_template": (
            "比較可能時間は{hours}時間です。モデルMAEは{model_mae}、"
            "TEPCO MAEは{tepco_mae}でした。この日のdeterministic日次レポートにはWAPEがまだ記録されていません。"
        ),
        "operation_missing_summary": "日次運用レポートがまだないため、AIレポートを生成できません。",
        "operation_missing_limitation": "operationReportがまだ生成されていません。",
        "diagnostics_missing": "この日のdaily-diagnostics JSONがないため、内部特徴量の根拠は限定的です。",
        "no_major_explanation": "現時点の指標だけでは、特定の時間帯や特徴量グループに原因を絞り込めません。運用データがさらに蓄積された後に再評価します。",
        "recommendation_suggestion_template": "「{title}」仮説を基準に、{target}の影響を再確認します。",
        "recommendation_expected": "繰り返し発生する時間帯/営業形態条件でMAE、WAPE、RMSEが同時に改善するか確認します。",
        "recommendation_risk": "単一日のパターンを過度に反映すると、他の季節や曜日で過補正になる可能性があります。",
        "recommendation_validation": "直近2〜4週のreplayとバックテストで、TEPCO比のWAPE、RMSE、最大誤差を比較します。",
        "operator_autoapply": "featureRecommendationsはレビュー候補であり、自動適用されません。",
        "feature_catalog_note_template": "運用補正シグナルカタログ: {catalog}",
        "cool_lag_title": "前日lag過熱と気温低下が同時に観測されました。",
        "cool_lag_explanation": "最近の同一営業形態平均に比べてlag_24hが高く、前日比で気温が低下したregimeです。lagの慣性が需要スケールを高めに維持した可能性があります。",
        "weather_delta_title_template": "{label}帯で気象変化とモデルbiasが重なりました。",
        "weather_delta_explanation": "気温/冷房負荷の変化方向とモデルbiasが同じ時間帯で観測されました。この時間帯は気象感度特徴量の検討候補です。",
        "calibration_prior_title": "営業/非営業遷移prior補正が作動しました。",
        "calibration_prior_explanation": "operational-calibrationにbusinessTypeTransitionPriorAppliedフラグが記録されています。これは実測不足区間でlag過熱を保守的に下げるレイヤーです。",
        "calibration_transition_title": "実測ベースの営業形態遷移補正が作動しました。",
        "calibration_transition_explanation": "operational-calibrationにbusinessTypeTransitionAppliedフラグが記録されています。これは当日実測が蓄積された後に営業形態遷移を反映するレイヤーです。",
        "calibration_positive_title": "正の残差伝播制限が作動しました。",
        "calibration_positive_explanation": "operational-calibrationにpositiveResidualMitigationAppliedフラグが記録されています。これは夜間の小さな正の残差がramp時間帯を過度に押し上げる現象を制限します。",
        "calibration_recovery_title": "負の残差回復ダンピングが作動しました。",
        "calibration_recovery_explanation": "operational-calibrationにnegResidualRecoveryDampingAppliedフラグが記録されています。これは回復局面で過去の負の残差が将来予測を過度に下げることを緩和します。",
        "calibration_counter": "最終実行分JSONだけでは、中間intraday実行時点の成功/失敗を断定できません。",
        "snapshot_history_title": "intraday補正の実行履歴がスナップショットとして保存されました。",
        "snapshot_history_explanation": "operational-calibration snapshot indexに中間実行履歴が残っているため、最終上書きJSONだけを見る場合より補正レイヤーの流れを追跡しやすくなります。",
        "snapshot_counter_template": "スナップショットは保存された{count}回の実行のみを説明し、削除済みの過去実行は復元できません。",
        "snapshot_applied_counter_template": "補正が実際に適用されたスナップショット数は{count}回です。",
        "openai_failed_template": "OpenAIレポート生成に失敗したため、fallback解説を使用しました: {error}",
    },
}

INSIGHT_TEMPLATES = {
    "tepco_closer_overall": {
        "title": "TEPCO 대비 일일 오차가 컸습니다.",
        "explanation": "일일 MAE/WAPE 기준으로 TEPCO 예측이 더 가까웠습니다. 세부 시간대와 내부 피처를 함께 확인해야 합니다.",
        "related_features": ["lag_24h", "temp_c", "humidity_pct"],
    },
    "model_closer_overall": {
        "title": "모델이 일일 기준으로 TEPCO보다 가까웠습니다.",
        "explanation": "일일 MAE/WAPE 기준으로 모델 예측이 더 안정적이었습니다. 같은 조건의 반복 여부를 추적할 가치가 있습니다.",
        "related_features": ["lgbm_quantile_q50", "intraday_correction.day_level_scale"],
    },
    "morning_ramp_overestimated": {
        "title": "오전 ramp 구간에서 수요를 높게 봤을 가능성이 있습니다.",
        "explanation": "오전 ramp 구간의 평균 bias가 양수로 나타났습니다. 전날 lag 관성이나 평일/비영업일 전환 신호를 점검해야 합니다.",
        "related_features": [
            "lag_24h",
            "lag_24h_business_type_mismatch",
            "recent_same_business_type_mean",
            "intraday_correction.business_type_transition_prior",
            "intraday_correction.positive_residual_mitigation",
        ],
    },
    "morning_ramp_underestimated": {
        "title": "오전 ramp 구간의 상승을 낮게 봤을 가능성이 있습니다.",
        "explanation": "오전 ramp 구간의 평균 bias가 음수로 나타났습니다. 기상 상승, 습도, 출근 시간대 ramp 피처가 충분히 반영됐는지 확인해야 합니다.",
        "related_features": ["temp_delta_24h", "humidity_pct", "lag_24h_hourly_delta"],
    },
    "daytime_level_underestimated": {
        "title": "낮 시간대 수요 레벨을 낮게 봤을 가능성이 있습니다.",
        "explanation": "낮 시간대의 모델 bias가 음수로 집계되었습니다. 냉방도, 습도, 최근 같은 영업형태 평균과의 차이를 확인해야 합니다.",
        "related_features": ["cooling_degree", "apparent_temp_c", "recent_same_business_type_mean"],
    },
    "afternoon_plateau_underestimated": {
        "title": "늦은 오후 수요 유지력을 낮게 봤을 가능성이 있습니다.",
        "explanation": "늦은 오후 구간에서 수요가 예측보다 높게 유지되었습니다. 기온 하강/상승 방향성과 업무 후반 시간대 상호작용을 점검해야 합니다.",
        "related_features": [
            "temp_delta_1h",
            "apparent_temp_delta_1h",
            "business_late_afternoon_x_temp_delta_1h",
        ],
    },
    "large_single_hour_miss": {
        "title": "특정 시간대의 단일 대형 오차가 발생했습니다.",
        "explanation": "최대 오차 시간이 일일 지표를 크게 흔들었습니다. 해당 시각의 lag, 날씨, 보정 레이어 메타데이터를 우선 확인해야 합니다.",
        "related_features": ["lag_24h", "temp_c", "intraday_correction.day_boundary_carryover"],
    },
    "sharp_model_drop_mismatch": {
        "title": "모델 곡선이 실제 수요보다 급하게 내려갔을 수 있습니다.",
        "explanation": "시간 간 변화량 기준으로 모델 하락폭과 실제 하락폭의 차이가 컸습니다. 음수 잔차 이월과 shape guard 동작을 확인해야 합니다.",
        "related_features": [
            "intraday_correction.negative_residual_recovery_damping",
            "intraday_correction.day_boundary_carryover",
        ],
    },
    "sharp_model_rise_mismatch": {
        "title": "모델 곡선이 실제 수요보다 급하게 올라갔을 수 있습니다.",
        "explanation": "시간 간 변화량 기준으로 모델 상승폭이 실제보다 컸습니다. 양수 잔차 전파와 ramp guard의 영향 범위를 확인해야 합니다.",
        "related_features": [
            "intraday_correction.positive_residual_mitigation",
            "lag_24h_hourly_delta",
        ],
    },
    "peak_timing_miss": {
        "title": "피크 발생 시간 예측이 어긋났습니다.",
        "explanation": "모델 피크 시각과 실제 피크 시각 사이에 차이가 있었습니다. 피크 전후의 기상 변화량과 lag shape를 함께 봐야 합니다.",
        "related_features": ["temp_delta_1h", "lag_168h_hourly_delta"],
    },
    "peak_level_underestimated": {
        "title": "실제 피크 레벨을 낮게 봤습니다.",
        "explanation": "실제 피크 시각에서 모델 예측이 낮았습니다. 냉난방 부하와 최근 같은 영업형태 anchor를 확인해야 합니다.",
        "related_features": ["cooling_degree", "heating_degree", "recent_same_business_type_mean"],
    },
    "peak_level_overestimated": {
        "title": "실제 피크 레벨을 높게 봤습니다.",
        "explanation": "실제 피크 시각에서 모델 예측이 높았습니다. 전날 lag 과열과 일 단위 수요 스케일 보정 여부를 확인해야 합니다.",
        "related_features": ["lag_24h_to_same_business_type_gap", "intraday_correction.day_level_scale"],
    },
}

INSIGHT_TEMPLATES_BY_LANG = {
    "ko": INSIGHT_TEMPLATES,
    "en": {
        "tepco_closer_overall": {
            "title": "Daily error was higher than TEPCO.",
            "explanation": "TEPCO was closer by daily MAE/WAPE. Review the detailed hour bands and internal features together.",
            "related_features": ["lag_24h", "temp_c", "humidity_pct"],
        },
        "model_closer_overall": {
            "title": "The model was closer than TEPCO on the daily view.",
            "explanation": "The model was more stable by daily MAE/WAPE. Track whether the same condition repeats.",
            "related_features": ["lgbm_quantile_q50", "intraday_correction.day_level_scale"],
        },
        "morning_ramp_overestimated": {
            "title": "The morning ramp may have been overestimated.",
            "explanation": "The morning-ramp average bias was positive. Check previous-day lag inertia and business/non-business transition signals.",
            "related_features": [
                "lag_24h",
                "lag_24h_business_type_mismatch",
                "recent_same_business_type_mean",
                "intraday_correction.business_type_transition_prior",
                "intraday_correction.positive_residual_mitigation",
            ],
        },
        "morning_ramp_underestimated": {
            "title": "The morning ramp-up may have been underestimated.",
            "explanation": "The morning-ramp average bias was negative. Check whether weather lift, humidity, and commuting-hour ramp features were represented enough.",
            "related_features": ["temp_delta_24h", "humidity_pct", "lag_24h_hourly_delta"],
        },
        "daytime_level_underestimated": {
            "title": "Daytime demand level may have been underestimated.",
            "explanation": "The model bias was negative in daytime hours. Review cooling degree, humidity, and recent same-business-type anchors.",
            "related_features": ["cooling_degree", "apparent_temp_c", "recent_same_business_type_mean"],
        },
        "afternoon_plateau_underestimated": {
            "title": "Late-afternoon demand persistence may have been underestimated.",
            "explanation": "Demand stayed higher than forecast in late afternoon. Review temperature direction and late-business-hour interactions.",
            "related_features": [
                "temp_delta_1h",
                "apparent_temp_delta_1h",
                "business_late_afternoon_x_temp_delta_1h",
            ],
        },
        "large_single_hour_miss": {
            "title": "A large single-hour miss occurred.",
            "explanation": "The max-error hour had a large impact on daily metrics. Inspect lag, weather, and calibration metadata for that hour first.",
            "related_features": ["lag_24h", "temp_c", "intraday_correction.day_boundary_carryover"],
        },
        "sharp_model_drop_mismatch": {
            "title": "The model curve may have dropped faster than actual demand.",
            "explanation": "The hour-to-hour model drop differed substantially from actual movement. Check negative residual carry-over and shape guard behavior.",
            "related_features": [
                "intraday_correction.negative_residual_recovery_damping",
                "intraday_correction.day_boundary_carryover",
            ],
        },
        "sharp_model_rise_mismatch": {
            "title": "The model curve may have risen faster than actual demand.",
            "explanation": "The hour-to-hour model rise exceeded actual movement. Check positive residual propagation and ramp-guard scope.",
            "related_features": [
                "intraday_correction.positive_residual_mitigation",
                "lag_24h_hourly_delta",
            ],
        },
        "peak_timing_miss": {
            "title": "Peak timing was missed.",
            "explanation": "The model peak hour differed from the actual peak hour. Review weather deltas and lag shape around the peak.",
            "related_features": ["temp_delta_1h", "lag_168h_hourly_delta"],
        },
        "peak_level_underestimated": {
            "title": "Actual peak level was underestimated.",
            "explanation": "At the actual peak hour, the model forecast was low. Check cooling/heating load and same-business-type anchors.",
            "related_features": ["cooling_degree", "heating_degree", "recent_same_business_type_mean"],
        },
        "peak_level_overestimated": {
            "title": "Actual peak level was overestimated.",
            "explanation": "At the actual peak hour, the model forecast was high. Check previous-day lag overheating and day-level scale calibration.",
            "related_features": ["lag_24h_to_same_business_type_gap", "intraday_correction.day_level_scale"],
        },
    },
    "ja": {
        "tepco_closer_overall": {
            "title": "日次誤差はTEPCOより大きくなりました。",
            "explanation": "日次MAE/WAPEではTEPCO予測のほうが近い結果でした。詳細時間帯と内部特徴量を併せて確認する必要があります。",
            "related_features": ["lag_24h", "temp_c", "humidity_pct"],
        },
        "model_closer_overall": {
            "title": "日次ではモデルがTEPCOより近い結果でした。",
            "explanation": "日次MAE/WAPEではモデル予測がより安定していました。同じ条件が繰り返されるか追跡する価値があります。",
            "related_features": ["lgbm_quantile_q50", "intraday_correction.day_level_scale"],
        },
        "morning_ramp_overestimated": {
            "title": "朝ramp帯で需要を高く見た可能性があります。",
            "explanation": "朝ramp帯の平均biasが正の値でした。前日lagの慣性や営業/非営業遷移シグナルを確認する必要があります。",
            "related_features": [
                "lag_24h",
                "lag_24h_business_type_mismatch",
                "recent_same_business_type_mean",
                "intraday_correction.business_type_transition_prior",
                "intraday_correction.positive_residual_mitigation",
            ],
        },
        "morning_ramp_underestimated": {
            "title": "朝ramp帯の上昇を低く見た可能性があります。",
            "explanation": "朝ramp帯の平均biasが負の値でした。気象上昇、湿度、通勤時間帯ramp特徴量が十分に反映されたか確認する必要があります。",
            "related_features": ["temp_delta_24h", "humidity_pct", "lag_24h_hourly_delta"],
        },
        "daytime_level_underestimated": {
            "title": "昼間の需要レベルを低く見た可能性があります。",
            "explanation": "昼間帯のモデルbiasが負の値でした。冷房度、湿度、最近の同一営業形態平均との差を確認する必要があります。",
            "related_features": ["cooling_degree", "apparent_temp_c", "recent_same_business_type_mean"],
        },
        "afternoon_plateau_underestimated": {
            "title": "夕方前の需要維持力を低く見た可能性があります。",
            "explanation": "夕方前の時間帯で需要が予測より高く維持されました。気温の上昇/下降方向と業務後半時間帯の相互作用を確認する必要があります。",
            "related_features": [
                "temp_delta_1h",
                "apparent_temp_delta_1h",
                "business_late_afternoon_x_temp_delta_1h",
            ],
        },
        "large_single_hour_miss": {
            "title": "特定時間で大きな単発誤差が発生しました。",
            "explanation": "最大誤差時間が日次指標を大きく動かしました。その時刻のlag、天候、補正レイヤーメタデータを優先して確認する必要があります。",
            "related_features": ["lag_24h", "temp_c", "intraday_correction.day_boundary_carryover"],
        },
        "sharp_model_drop_mismatch": {
            "title": "モデル曲線が実需より急に下がった可能性があります。",
            "explanation": "時間差分ベースでモデルの低下幅と実需の低下幅に大きな差がありました。負の残差carry-overとshape guardの動作を確認する必要があります。",
            "related_features": [
                "intraday_correction.negative_residual_recovery_damping",
                "intraday_correction.day_boundary_carryover",
            ],
        },
        "sharp_model_rise_mismatch": {
            "title": "モデル曲線が実需より急に上がった可能性があります。",
            "explanation": "時間差分ベースでモデルの上昇幅が実需より大きくなりました。正の残差伝播とramp guardの影響範囲を確認する必要があります。",
            "related_features": [
                "intraday_correction.positive_residual_mitigation",
                "lag_24h_hourly_delta",
            ],
        },
        "peak_timing_miss": {
            "title": "ピーク発生時刻の予測がずれました。",
            "explanation": "モデルピーク時刻と実ピーク時刻に差がありました。ピーク前後の気象変化量とlag shapeを併せて見る必要があります。",
            "related_features": ["temp_delta_1h", "lag_168h_hourly_delta"],
        },
        "peak_level_underestimated": {
            "title": "実ピーク水準を低く見ました。",
            "explanation": "実ピーク時刻でモデル予測が低くなりました。冷暖房負荷と最近の同一営業形態anchorを確認する必要があります。",
            "related_features": ["cooling_degree", "heating_degree", "recent_same_business_type_mean"],
        },
        "peak_level_overestimated": {
            "title": "実ピーク水準を高く見ました。",
            "explanation": "実ピーク時刻でモデル予測が高くなりました。前日lag過熱と日単位需要スケール補正の有無を確認する必要があります。",
            "related_features": ["lag_24h_to_same_business_type_gap", "intraday_correction.day_level_scale"],
        },
    },
}


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_local_dotenv(public_dir: Path) -> None:
    """Load repo-local .env values for manual local runs.

    GitHub Actions passes secrets through real environment variables. This helper
    only fills missing values from a local .env file and never overrides values
    already present in the process.
    """
    candidates = [
        public_dir.parent.parent / ".env",
        Path.cwd() / ".env",
    ]
    for dotenv_path in candidates:
        if not dotenv_path.exists():
            continue
        for line in dotenv_path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        return


def _now_jst() -> str:
    return datetime.now(tz=JST).isoformat(timespec="seconds")


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return max(0, int(value))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_csv(name: str, default: str) -> set[str]:
    value = os.getenv(name) or default
    return {part.strip() for part in value.split(",") if part.strip()}


def _csv_values(value: str) -> set[str]:
    return {part.strip() for part in value.split(",") if part.strip()}


def _rel(public_dir: Path, path: Path) -> str | None:
    if not path.exists():
        return None
    return path.relative_to(public_dir).as_posix()


def _fmt_mw(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):,.1f} MW"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def _hour_label(hour: Any) -> str | None:
    if hour is None:
        return None
    try:
        return f"{int(hour):02d}:00"
    except (TypeError, ValueError):
        return None


def _severity_from_summary(summary: dict) -> str:
    max_error = summary.get("modelMaxErrorMw")
    wape_gap = summary.get("wapeGapPct")
    verdict = summary.get("verdict")
    if verdict == "tepco_better" and (
        (isinstance(max_error, (int, float)) and max_error >= 2000.0)
        or (isinstance(wape_gap, (int, float)) and wape_gap >= 1.0)
    ):
        return "warning"
    if verdict in {"tepco_better", "mixed"}:
        return "warning"
    return "info"


def _confidence(operation: dict, diagnostics: dict | None) -> str:
    hours = operation.get("summary", {}).get("comparableHours") or 0
    if hours >= 24 and diagnostics is not None:
        return "high"
    if hours >= 20:
        return "medium"
    return "low"


def _headline(summary: dict, messages: dict[str, str]) -> str:
    verdict = summary.get("verdict") or "insufficient"
    if verdict == "model_better":
        return messages["headline_model_better"]
    if verdict == "tepco_better":
        return messages["headline_tepco_better"]
    if verdict == "close":
        return messages["headline_close"]
    if verdict == "mixed":
        return messages["headline_mixed"]
    return messages["headline_insufficient"]


def _summary_text(summary: dict, messages: dict[str, str]) -> str:
    values = {
        "hours": summary.get("comparableHours", 0),
        "model_mae": _fmt_mw(summary.get("modelMaeMw")),
        "tepco_mae": _fmt_mw(summary.get("tepcoMaeMw")),
        "model_wape": _fmt_pct(summary.get("modelWapePct")),
        "tepco_wape": _fmt_pct(summary.get("tepcoWapePct")),
    }
    base = messages["summary_template"].format(**values)
    if summary.get("modelWapePct") is None or summary.get("tepcoWapePct") is None:
        return messages["wape_missing_summary_template"].format(**values)
    return base


def _input_refs(public_dir: Path, date_iso: str) -> dict:
    paths = {
        "operationReport": public_dir / "reports" / "daily" / f"{date_iso}.json",
        "internalDiagnostics": public_dir / "reports" / "internal" / "daily-diagnostics" / f"{date_iso}.json",
        "operationalCalibration": public_dir / "reports" / "internal" / "operational-calibration" / f"{date_iso}.json",
        "operationalCalibrationHistory": (
            public_dir
            / "reports"
            / "internal"
            / "operational-calibration"
            / "snapshots"
            / date_iso
            / "index.json"
        ),
        "alerts": public_dir / "alerts" / f"{date_iso}.json",
        "forecast": public_dir / "forecast" / f"{date_iso}.json",
        "actual": public_dir / "actual" / f"{date_iso}.json",
        "metrics": public_dir / "metrics" / "forecast_accuracy.json",
    }
    return {
        key: _rel(public_dir, path)
        for key, path in paths.items()
    }


def _fingerprint_json_values(values: dict) -> str:
    encoded = json.dumps(
        values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _input_snapshot(public_dir: Path, input_refs: dict, created_at: str | None = None) -> dict:
    sources = {}
    fingerprint_payload = {}
    for key, ref in input_refs.items():
        if not ref:
            sources[key] = {
                "path": None,
                "exists": False,
                "date": None,
                "generatedAt": None,
                "fingerprint": None,
            }
            continue
        path = public_dir / ref
        payload = _load_json(path)
        if payload is None:
            sources[key] = {
                "path": ref,
                "exists": False,
                "date": None,
                "generatedAt": None,
                "fingerprint": None,
            }
            continue
        source_fingerprint = _fingerprint_json_values(payload)
        sources[key] = {
            "path": ref,
            "exists": True,
            "date": payload.get("date"),
            "generatedAt": payload.get("generatedAt"),
            "fingerprint": source_fingerprint,
        }
        fingerprint_payload[key] = {
            "path": ref,
            "date": payload.get("date"),
            "generatedAt": payload.get("generatedAt"),
            "fingerprint": source_fingerprint,
        }

    return {
        "schemaVersion": SCHEMA_VERSION,
        "createdAt": created_at or _now_jst(),
        "fingerprint": _fingerprint_json_values(fingerprint_payload),
        "sources": sources,
    }


def _data_quality(
    actual: dict | None,
    operation: dict,
    limitations: list[str],
    calibration_history: dict | None = None,
) -> dict:
    series = actual.get("series", []) if actual else []
    observed_hours = sum(
        1
        for point in series
        if point.get("actualMw") is not None
        and point.get("actualSource") != "tepco_forecast_fallback"
    )
    fallback_hours = sum(
        1
        for point in series
        if point.get("actualMw") is not None
        and point.get("actualSource") == "tepco_forecast_fallback"
    )
    snapshots = calibration_history.get("snapshots", []) if calibration_history else []
    return {
        "comparableHours": operation.get("summary", {}).get("comparableHours", 0),
        "observedHours": observed_hours,
        "fallbackActualHours": fallback_hours,
        "calibrationSnapshotCount": len(snapshots),
        "limitations": limitations,
    }


def _evidence_from_insight(insight: dict, operation: dict) -> list[dict]:
    evidence = []
    raw = insight.get("evidence") or {}
    time_band = raw.get("band") or raw.get("timeBand")
    hour = raw.get("hour")
    for metric, value in raw.items():
        if metric in {"band", "timeBand", "hour", "fromHour", "toHour"}:
            continue
        evidence.append({
            "source": "reports/daily",
            "metric": str(metric),
            "value": value,
            "unit": "MW" if str(metric).endswith("Mw") else None,
            "hour": hour,
            "timeBand": time_band,
        })
    if evidence:
        return evidence

    top_miss = (operation.get("topMisses") or [None])[0]
    if top_miss:
        return [{
            "source": "reports/daily",
            "metric": "modelAbsErrorMw",
            "value": top_miss.get("modelAbsErrorMw"),
            "unit": "MW",
            "hour": top_miss.get("hour"),
            "timeBand": None,
        }]
    return []


def _related_hours_from_insight(insight: dict, operation: dict) -> list[int]:
    evidence = insight.get("evidence") or {}
    hour = evidence.get("hour")
    if isinstance(hour, int):
        return [hour]
    from_hour = evidence.get("fromHour")
    to_hour = evidence.get("toHour")
    if isinstance(from_hour, int) and isinstance(to_hour, int):
        return [from_hour, to_hour]
    if insight.get("code") != "large_single_hour_miss":
        return []
    top_miss = (operation.get("topMisses") or [None])[0]
    if top_miss and isinstance(top_miss.get("hour"), int):
        return [top_miss["hour"]]
    return []


def _operation_hypotheses(operation: dict, language: str) -> list[dict]:
    hypotheses: list[dict] = []
    templates = INSIGHT_TEMPLATES_BY_LANG.get(language, INSIGHT_TEMPLATES)
    for index, insight in enumerate(operation.get("insights", []), start=1):
        code = insight.get("code")
        template = templates.get(code)
        if not template:
            continue
        hypotheses.append({
            "id": f"h{index}",
            "severity": insight.get("severity", "info"),
            "confidence": "medium",
            "evidenceStatus": "partial",
            "title": template["title"],
            "explanation": template["explanation"],
            "evidence": _evidence_from_insight(insight, operation),
            "relatedHours": _related_hours_from_insight(insight, operation),
            "relatedTimeBands": [
                value
                for value in [
                    (insight.get("evidence") or {}).get("band"),
                    (insight.get("evidence") or {}).get("timeBand"),
                ]
                if value
            ],
            "relatedFeatures": template["related_features"],
            "counterEvidence": [],
        })
    return hypotheses


def _diagnostic_hypotheses(
    diagnostics: dict | None,
    start_index: int,
    messages: dict[str, str],
) -> list[dict]:
    if not diagnostics:
        return []

    result: list[dict] = []
    summary = diagnostics.get("diagnosticSummary") or {}
    regime = summary.get("dayLevelRegime") or {}
    flags = set(regime.get("flags") or [])
    if "cool_lag_overheat_regime" in flags:
        result.append({
            "id": f"h{start_index + len(result)}",
            "severity": "warning",
            "confidence": "medium",
            "evidenceStatus": "partial",
            "title": messages["cool_lag_title"],
            "explanation": messages["cool_lag_explanation"],
            "evidence": [
                {
                    "source": "reports/internal/daily-diagnostics",
                    "metric": "lag24OverheatMeanMw",
                    "value": regime.get("lag24OverheatMeanMw"),
                    "unit": "MW",
                },
                {
                    "source": "reports/internal/daily-diagnostics",
                    "metric": "tempDelta24hMeanC",
                    "value": regime.get("tempDelta24hMeanC"),
                    "unit": "C",
                },
            ],
            "relatedHours": [],
            "relatedTimeBands": [],
            "relatedFeatures": [
                "lag_24h_to_same_business_type_gap",
                "temp_delta_24h",
                "intraday_correction.day_level_scale",
            ],
            "counterEvidence": [],
        })

    for band in summary.get("weatherDeltaRiskByBand", []):
        assessment = band.get("assessment")
        if not assessment or assessment == "neutral":
            continue
        result.append({
            "id": f"h{start_index + len(result)}",
            "severity": "warning",
            "confidence": "medium",
            "evidenceStatus": "partial",
            "title": messages["weather_delta_title_template"].format(
                label=band.get("label") or band.get("code") or "",
            ),
            "explanation": messages["weather_delta_explanation"],
            "evidence": [
                {
                    "source": "reports/internal/daily-diagnostics",
                    "metric": "coolingDelta24hMean",
                    "value": band.get("coolingDelta24hMean"),
                    "unit": "C",
                    "timeBand": band.get("code"),
                },
                {
                    "source": "reports/internal/daily-diagnostics",
                    "metric": "modelBiasMw",
                    "value": band.get("modelBiasMw"),
                    "unit": "MW",
                    "timeBand": band.get("code"),
                },
            ],
            "relatedHours": [],
            "relatedTimeBands": [band.get("code")],
            "relatedFeatures": ["cooling_delta_24h", "temp_delta_24h", "weather_source"],
            "counterEvidence": [],
        })
        if len(result) >= 2:
            break

    return result


def _calibration_hypotheses(
    calibration: dict | None,
    start_index: int,
    messages: dict[str, str],
) -> list[dict]:
    if not calibration:
        return []

    correction = calibration.get("correction") or {}
    checks = [
        (
            "businessTypeTransitionPriorApplied",
            "businessTypeTransitionPriorBiasMw",
            messages["calibration_prior_title"],
            messages["calibration_prior_explanation"],
            "intraday_correction.business_type_transition_prior",
        ),
        (
            "businessTypeTransitionApplied",
            "businessTypeTransitionBiasMw",
            messages["calibration_transition_title"],
            messages["calibration_transition_explanation"],
            "intraday_correction.business_type_transition",
        ),
        (
            "positiveResidualMitigationApplied",
            "positiveResidualMitigationMaxMw",
            messages["calibration_positive_title"],
            messages["calibration_positive_explanation"],
            "intraday_correction.positive_residual_mitigation",
        ),
        (
            "negResidualRecoveryDampingApplied",
            "negResidualRecoveryDampingFactor",
            messages["calibration_recovery_title"],
            messages["calibration_recovery_explanation"],
            "intraday_correction.negative_residual_recovery_damping",
        ),
    ]

    result = []
    for flag, value_key, title, explanation, feature in checks:
        if not correction.get(flag):
            continue
        result.append({
            "id": f"h{start_index + len(result)}",
            "severity": "info",
            "confidence": "high",
            "evidenceStatus": "confirmed",
            "title": title,
            "explanation": explanation,
            "evidence": [
                {
                    "source": "reports/internal/operational-calibration",
                    "metric": flag,
                    "value": True,
                },
                {
                    "source": "reports/internal/operational-calibration",
                    "metric": value_key,
                    "value": correction.get(value_key),
                    "unit": "MW" if value_key.endswith("Mw") else None,
                },
            ],
            "relatedHours": [],
            "relatedTimeBands": [],
            "relatedFeatures": [feature],
            "counterEvidence": [messages["calibration_counter"]],
        })
    return result


def _calibration_history_hypotheses(
    history: dict | None,
    start_index: int,
    messages: dict[str, str],
) -> list[dict]:
    if not history:
        return []

    snapshots = history.get("snapshots") or []
    if len(snapshots) < 2:
        return []

    reason_counts: dict[str, int] = {}
    applied_snapshots = 0
    for snapshot in snapshots:
        reasons = snapshot.get("appliedRegimeReason") or []
        if snapshot.get("applied") or reasons:
            applied_snapshots += 1
        for reason in reasons:
            reason_counts[str(reason)] = reason_counts.get(str(reason), 0) + 1

    if not reason_counts:
        return []

    dominant_reason, dominant_count = sorted(
        reason_counts.items(),
        key=lambda item: (-item[1], item[0]),
    )[0]
    latest = snapshots[-1]
    return [{
        "id": f"h{start_index}",
        "severity": "info",
        "confidence": "high",
        "evidenceStatus": "confirmed",
        "title": messages["snapshot_history_title"],
        "explanation": messages["snapshot_history_explanation"],
        "evidence": [
            {
                "source": "reports/internal/operational-calibration/snapshots",
                "metric": "snapshotCount",
                "value": len(snapshots),
            },
            {
                "source": "reports/internal/operational-calibration/snapshots",
                "metric": "dominantAppliedRegimeReason",
                "value": dominant_reason,
            },
            {
                "source": "reports/internal/operational-calibration/snapshots",
                "metric": "dominantReasonCount",
                "value": dominant_count,
            },
            {
                "source": "reports/internal/operational-calibration/snapshots",
                "metric": "latestGeneratedAt",
                "value": latest.get("generatedAt"),
            },
        ],
        "relatedHours": [],
        "relatedTimeBands": [],
        "relatedFeatures": [
            "intraday_correction.day_boundary_carryover",
            "intraday_correction.business_type_transition_prior",
            "intraday_correction.negative_residual_recovery_damping",
        ],
        "counterEvidence": [
            messages["snapshot_counter_template"].format(count=len(snapshots)),
            messages["snapshot_applied_counter_template"].format(count=applied_snapshots),
        ],
    }]


def _dedupe_hypotheses(hypotheses: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result = []
    for hypothesis in hypotheses:
        key = hypothesis["title"]
        if key in seen:
            continue
        seen.add(key)
        if hypothesis["evidenceStatus"] == "not_observed":
            hypothesis["confidence"] = "low"
        result.append(hypothesis)
    return result[:5]


def _recommendations(hypotheses: list[dict], messages: dict[str, str]) -> list[dict]:
    recommendations = []
    for hypothesis in hypotheses:
        features = hypothesis.get("relatedFeatures") or []
        if not features:
            continue
        target = features[0]
        recommendations.append({
            "id": f"r{len(recommendations) + 1}",
            "priority": "medium" if hypothesis.get("severity") == "warning" else "low",
            "type": "calibration" if target.startswith("intraday_correction.") else "feature_engineering",
            "target": target,
            "suggestion": messages["recommendation_suggestion_template"].format(
                title=hypothesis["title"],
                target=target,
            ),
            "expectedEffect": messages["recommendation_expected"],
            "risk": messages["recommendation_risk"],
            "validationPlan": messages["recommendation_validation"],
            "linkedHypotheses": [hypothesis["id"]],
            "autoApply": False,
        })
        if len(recommendations) >= 3:
            break
    return recommendations


def _build_limitations(
    messages: dict[str, str],
    diagnostics: dict | None,
    calibration: dict | None,
    calibration_history: dict | None,
) -> list[str]:
    limitations = [messages["fallback_note"]]
    if calibration_history and calibration_history.get("snapshots"):
        limitations.append(messages["snapshot_limit"])
    else:
        limitations.append(messages["timeline_limit"])
    if diagnostics is None:
        limitations.append(messages["diagnostics_missing"])
    if calibration is None:
        limitations.append(messages["no_calibration"])
    return limitations


def _build_fallback_ai_daily_report(
    public_dir: Path,
    date_iso: str,
    generated_at: str,
    language: str = "ko",
) -> dict:
    if language not in MESSAGES:
        raise ValueError(f"Unsupported AI daily report language: {language}")

    messages = MESSAGES[language]
    operation_path = public_dir / "reports" / "daily" / f"{date_iso}.json"
    operation = _load_json(operation_path)
    if not operation:
        input_refs = _input_refs(public_dir, date_iso)
        return {
            "schemaVersion": SCHEMA_VERSION,
            "reportType": REPORT_TYPE,
            "timezone": TIMEZONE,
            "date": date_iso,
            "generatedAt": generated_at,
            "availability": "not_yet_available",
            "language": language,
            "generator": {
                "provider": "fallback",
                "model": None,
                "promptVersion": PROMPT_VERSION,
                "schemaVersion": SCHEMA_VERSION,
            },
            "inputRefs": input_refs,
            "inputSnapshot": _input_snapshot(public_dir, input_refs, generated_at),
            "dataQuality": {
                "comparableHours": 0,
                "observedHours": 0,
                "fallbackActualHours": 0,
                "limitations": ["operationReport가 아직 생성되지 않았습니다."],
            },
            "executiveSummary": {
                "severity": "info",
                "headline": messages["headline_insufficient"],
                "summary": messages["operation_missing_summary"],
                "modelVerdict": "insufficient",
                "confidence": "low",
            },
            "performance": {"comparableHours": 0},
            "rootCauseHypotheses": [],
            "featureRecommendations": [],
            "operatorNotes": [],
            "limitations": [messages["operation_missing_limitation"]],
        }

    diagnostics = _load_json(
        public_dir / "reports" / "internal" / "daily-diagnostics" / f"{date_iso}.json"
    )
    calibration = _load_json(
        public_dir / "reports" / "internal" / "operational-calibration" / f"{date_iso}.json"
    )
    calibration_history = _load_json(
        public_dir
        / "reports"
        / "internal"
        / "operational-calibration"
        / "snapshots"
        / date_iso
        / "index.json"
    )
    actual = _load_json(public_dir / "actual" / f"{date_iso}.json")

    summary = operation.get("summary") or {}
    limitations = _build_limitations(messages, diagnostics, calibration, calibration_history)
    hypotheses = _dedupe_hypotheses(
        _operation_hypotheses(operation, language)
        + _diagnostic_hypotheses(diagnostics, start_index=20, messages=messages)
        + _calibration_hypotheses(calibration, start_index=40, messages=messages)
        + _calibration_history_hypotheses(calibration_history, start_index=60, messages=messages)
    )
    if not hypotheses:
        hypotheses = [{
            "id": "h1",
            "severity": "info",
            "confidence": "low",
            "evidenceStatus": "not_observed",
            "title": messages["no_major_hypothesis"],
            "explanation": messages["no_major_explanation"],
            "evidence": [],
            "relatedHours": [],
            "relatedTimeBands": [],
            "relatedFeatures": [],
            "counterEvidence": [],
        }]

    input_refs = _input_refs(public_dir, date_iso)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "reportType": REPORT_TYPE,
        "timezone": TIMEZONE,
        "date": date_iso,
        "generatedAt": generated_at,
        "availability": "ok" if operation.get("availability") == "ok" else operation.get("availability", "insufficient"),
        "language": language,
        "contentLanguage": language,
        "generator": {
            "provider": "fallback",
            "model": None,
            "promptVersion": PROMPT_VERSION,
            "schemaVersion": SCHEMA_VERSION,
        },
        "inputRefs": input_refs,
        "inputSnapshot": _input_snapshot(public_dir, input_refs, generated_at),
        "dataQuality": _data_quality(actual, operation, limitations, calibration_history),
        "executiveSummary": {
            "severity": _severity_from_summary(summary),
            "headline": _headline(summary, messages),
            "summary": _summary_text(summary, messages),
            "modelVerdict": summary.get("verdict", "insufficient"),
            "confidence": _confidence(operation, diagnostics),
        },
        "performance": summary,
        "rootCauseHypotheses": hypotheses,
        "featureRecommendations": _recommendations(hypotheses, messages),
        "operatorNotes": [
            messages["operator_autoapply"],
            messages["feature_catalog_note_template"].format(catalog=", ".join(FEATURE_CATALOG)),
        ],
        "limitations": limitations,
    }


def _load_ref_json(public_dir: Path, fallback_report: dict, key: str) -> dict | None:
    ref = (fallback_report.get("inputRefs") or {}).get(key)
    if not ref:
        return None
    return _load_json(public_dir / ref)


def _compact_narrative(report: dict) -> dict:
    return {
        "executiveSummary": report.get("executiveSummary"),
        "rootCauseHypotheses": [
            {
                "severity": item.get("severity"),
                "confidence": item.get("confidence"),
                "evidenceStatus": item.get("evidenceStatus"),
                "title": item.get("title"),
                "explanation": item.get("explanation"),
                "relatedHours": item.get("relatedHours"),
                "relatedTimeBands": item.get("relatedTimeBands"),
                "relatedFeatures": item.get("relatedFeatures"),
            }
            for item in (report.get("rootCauseHypotheses") or [])[:3]
        ],
        "featureRecommendations": [
            {
                "priority": item.get("priority"),
                "type": item.get("type"),
                "target": item.get("target"),
                "suggestion": item.get("suggestion"),
                "risk": item.get("risk"),
            }
            for item in (report.get("featureRecommendations") or [])[:3]
        ],
        "limitations": report.get("limitations") or [],
    }


def _compact_input_snapshot_for_prompt(snapshot: dict | None) -> dict | None:
    if not isinstance(snapshot, dict):
        return None
    compact_sources = {}
    for key, source in (snapshot.get("sources") or {}).items():
        if not isinstance(source, dict):
            continue
        compact_sources[key] = {
            "exists": source.get("exists"),
            "date": source.get("date"),
            "generatedAt": source.get("generatedAt"),
        }
    return {
        "schemaVersion": snapshot.get("schemaVersion"),
        "createdAt": snapshot.get("createdAt"),
        "sources": compact_sources,
    }


def _sanitize_openai_context(context: dict) -> dict:
    sanitized = json.loads(json.dumps(context, ensure_ascii=False))
    sanitized.pop("fallbackReport", None)
    sanitized.pop("fallbackReports", None)

    fact_packet = sanitized.get("factPacket")
    if not isinstance(fact_packet, dict):
        return sanitized

    fact_packet.pop("fallbackNarrativeByLanguage", None)
    fact_packet.pop("fingerprint", None)
    fact_packet["inputSnapshot"] = _compact_input_snapshot_for_prompt(
        fact_packet.get("inputSnapshot")
    )

    operation_facts = fact_packet.get("operationFacts")
    if isinstance(operation_facts, dict):
        operation_facts.pop("summary", None)
        operation_facts.pop("insights", None)
        operation_facts["topMisses"] = (operation_facts.get("topMisses") or [])[:3]

    return sanitized


def _compact_calibration(calibration: dict | None) -> dict | None:
    if not calibration:
        return None
    correction = calibration.get("correction") or {}
    return {
        "date": calibration.get("date"),
        "generatedAt": calibration.get("generatedAt"),
        "sourceConfidence": correction.get("sourceConfidence") or calibration.get("source_confidence"),
        "appliedRegimeReason": correction.get("appliedRegimeReason") or calibration.get("applied_regime_reason"),
        "applied": correction.get("applied"),
        "observedHours": correction.get("observedHours"),
        "lastObservedHour": correction.get("lastObservedHour"),
        "baseAdjustmentMw": correction.get("baseAdjustmentMw"),
        "carryoverAdjustmentMw": correction.get("carryoverAdjustmentMw"),
        "appliedDayBiasMw": correction.get("appliedDayBiasMw") or calibration.get("applied_day_bias"),
        "businessTypeTransitionPriorApplied": correction.get("businessTypeTransitionPriorApplied"),
        "businessTypeTransitionPriorBiasMw": correction.get("businessTypeTransitionPriorBiasMw"),
        "businessTypeTransitionApplied": correction.get("businessTypeTransitionApplied"),
        "businessTypeTransitionBiasMw": correction.get("businessTypeTransitionBiasMw"),
        "positiveResidualMitigationApplied": correction.get("positiveResidualMitigationApplied"),
        "positiveResidualMitigationMaxMw": correction.get("positiveResidualMitigationMaxMw"),
        "negResidualRecoveryDampingApplied": correction.get("negResidualRecoveryDampingApplied"),
        "negResidualRecoveryDampingFactor": correction.get("negResidualRecoveryDampingFactor"),
    }


def _compact_calibration_history(calibration_history: dict | None) -> dict | None:
    if not calibration_history:
        return None
    snapshots = calibration_history.get("snapshots") or []
    latest = snapshots[-1] if snapshots else None
    applied_count = sum(1 for item in snapshots if item.get("applied"))
    return {
        "date": calibration_history.get("date"),
        "generatedAt": calibration_history.get("generatedAt"),
        "snapshotCount": len(snapshots),
        "appliedSnapshotCount": applied_count,
        "latest": latest,
    }


def _build_openai_fact_packet(
    public_dir: Path,
    fallback_reports: dict[str, dict],
) -> dict:
    primary = fallback_reports.get("ko") or next(iter(fallback_reports.values()))
    operation = _load_ref_json(public_dir, primary, "operationReport")
    diagnostics = _load_ref_json(public_dir, primary, "internalDiagnostics")
    calibration = _load_ref_json(public_dir, primary, "operationalCalibration")
    calibration_history = _load_ref_json(public_dir, primary, "operationalCalibrationHistory")

    operation_facts = {}
    if operation:
        operation_facts = {
            "model": operation.get("model"),
            "peak": operation.get("peak"),
            "timeBands": operation.get("timeBands"),
            "shape": operation.get("shape"),
            "topMisses": (operation.get("topMisses") or [])[:3],
        }

    diagnostic_facts = None
    if diagnostics:
        diagnostic_facts = {
            "date": diagnostics.get("date"),
            "generatedAt": diagnostics.get("generatedAt"),
            "featureBuildError": diagnostics.get("featureBuildError"),
            "diagnosticSummary": diagnostics.get("diagnosticSummary"),
        }

    fact_packet = {
        "date": primary.get("date"),
        "timezone": TIMEZONE,
        "inputSnapshot": primary.get("inputSnapshot"),
        "performance": primary.get("performance"),
        "dataQuality": primary.get("dataQuality"),
        "operationFacts": operation_facts,
        "diagnosticFacts": diagnostic_facts,
        "calibrationFacts": _compact_calibration(calibration),
        "calibrationHistoryFacts": _compact_calibration_history(calibration_history),
    }
    fact_packet["fingerprint"] = _fingerprint_json_values(fact_packet)
    return fact_packet


def _openai_analysis_schema() -> dict:
    """Schema for the OpenAI-authored narrative layer.

    Deterministic fields such as performance, inputRefs, dataQuality, date, and
    availability are merged from the fallback report after the model response.
    """
    evidence_schema = {
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "metric": {"type": "string"},
            "value": {"type": ["string", "number", "null"]},
            "unit": {"type": ["string", "null"]},
            "hour": {"type": ["integer", "null"]},
            "timeBand": {"type": ["string", "null"]},
        },
        "required": ["source", "metric", "value", "unit", "hour", "timeBand"],
        "additionalProperties": False,
    }
    hypothesis_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "evidenceStatus": {
                "type": "string",
                "enum": ["confirmed", "partial", "not_observed"],
            },
            "title": {"type": "string"},
            "explanation": {"type": "string"},
            "evidence": {
                "type": "array",
                "items": evidence_schema,
                "maxItems": 2,
            },
            "relatedHours": {
                "type": "array",
                "items": {"type": "integer"},
                "maxItems": 5,
            },
            "relatedTimeBands": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
            },
            "relatedFeatures": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
            },
            "counterEvidence": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 2,
            },
        },
        "required": [
            "id",
            "severity",
            "confidence",
            "evidenceStatus",
            "title",
            "explanation",
            "evidence",
            "relatedHours",
            "relatedTimeBands",
            "relatedFeatures",
            "counterEvidence",
        ],
        "additionalProperties": False,
    }
    recommendation_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "priority": {"type": "string", "enum": ["low", "medium", "high"]},
            "type": {
                "type": "string",
                "enum": ["feature_engineering", "calibration", "data_quality", "evaluation"],
            },
            "target": {"type": "string"},
            "suggestion": {"type": "string"},
            "expectedEffect": {"type": "string"},
            "risk": {"type": "string"},
            "validationPlan": {"type": "string"},
            "linkedHypotheses": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
            },
            "autoApply": {"type": "boolean"},
        },
        "required": [
            "id",
            "priority",
            "type",
            "target",
            "suggestion",
            "expectedEffect",
            "risk",
            "validationPlan",
            "linkedHypotheses",
            "autoApply",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "executiveSummary": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
                    "headline": {"type": "string"},
                    "summary": {"type": "string"},
                    "modelVerdict": {
                        "type": "string",
                        "enum": [
                            "model_better",
                            "tepco_better",
                            "close",
                            "mixed",
                            "insufficient",
                        ],
                    },
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["severity", "headline", "summary", "modelVerdict", "confidence"],
                "additionalProperties": False,
            },
            "rootCauseHypotheses": {
                "type": "array",
                "items": hypothesis_schema,
                "minItems": 1,
                "maxItems": 3,
            },
            "featureRecommendations": {
                "type": "array",
                "items": recommendation_schema,
                "minItems": 1,
                "maxItems": 2,
            },
            "operatorNotes": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
            },
            "limitations": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
            },
        },
        "required": [
            "executiveSummary",
            "rootCauseHypotheses",
            "featureRecommendations",
            "operatorNotes",
            "limitations",
        ],
        "additionalProperties": False,
    }


def _openai_domain_guidelines() -> str:
    return (
        "Reason like a power-demand operations analyst, not a text summarizer. "
        "Use only numeric facts, weather diagnostics, topMisses, timeBands, "
        "and calibration flags from factPacket. If morning_ramp hours 06-10 "
        "show large positive model bias and the data indicates a business-day "
        "to non-business-day transition, independently consider a lag_24h "
        "inertia or ramp contamination hypothesis. If observed demand slope "
        "recovers while residual trend remains worse or calibration facts show "
        "weak negative-residual damping, consider whether "
        "intraday_correction.negative_residual_recovery_damping thresholds or "
        "handoff timing need tuning; if direct evidence is absent, mark it "
        "not_observed with low confidence. Feature recommendations must name "
        "a concrete target from featureCatalog when possible and must propose "
        "a specific trigger, threshold, decay, shrinkage, or validation replay; "
        "avoid generic wording such as merely reviewing a feature. Never return "
        "empty titles, explanations, suggestions, expected effects, risks, or "
        "validation plans. Keep each title under 90 characters, each explanation "
        "under two short sentences, and each recommendation under one concrete "
        "engineering action."
    )


def _load_openai_context(public_dir: Path, fallback_report: dict) -> dict:
    return {
        "language": fallback_report.get("language", "ko"),
        "date": fallback_report.get("date"),
        "featureCatalog": FEATURE_CATALOG,
        "factPacket": _build_openai_fact_packet(
            public_dir,
            {fallback_report.get("language", "ko"): fallback_report},
        ),
    }


def _openai_instructions(language: str) -> str:
    language_name = {
        "ko": "Korean",
        "en": "English",
        "ja": "Japanese",
    }.get(language, "Korean")
    return (
        "You are an operations analyst for Tokyo-area electricity demand "
        f"forecasting. Produce a concise daily operations report in {language_name}. "
        "Use only the JSON data provided by the user. Do not invent metrics, "
        "hours, feature names, or calibration events. Keep deterministic "
        "metrics consistent with factPacket.performance. "
        "Use factPacket as the source of facts; raw 24-hour series rows are "
        "intentionally excluded for cost and stability. "
        f"{_openai_domain_guidelines()} "
        "If operationalCalibration or snapshot data directly contains a flag "
        "or numeric control value, evidenceStatus may be confirmed. If the "
        "pattern is inferred only from daily diagnostics or metrics, use "
        "partial. If the overwritten intraday timeline makes a claim "
        "unverifiable, use not_observed and confidence low. "
        "Every featureRecommendations item must set autoApply to false. "
        "The output language field in the final report is managed by code; "
        f"write narrative text for language={language}."
    )


def _openai_multilingual_analysis_schema(languages: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "reports": {
                "type": "object",
                "properties": {
                    language: _openai_analysis_schema()
                    for language in languages
                },
                "required": languages,
                "additionalProperties": False,
            }
        },
        "required": ["reports"],
        "additionalProperties": False,
    }


def _openai_multilingual_instructions(languages: list[str]) -> str:
    language_names = {
        "ko": "Korean",
        "en": "English",
        "ja": "Japanese",
    }
    readable = ", ".join(
        f"{language}={language_names.get(language, language)}"
        for language in languages
    )
    return (
        "You are an operations analyst for Tokyo-area electricity demand "
        "forecasting. Produce concise daily operations report narratives for "
        f"all requested languages in one JSON response: {readable}. "
        "Return reports keyed by locale. Use only the provided factPacket; "
        "do not invent metrics, hours, feature names, or "
        "calibration events. Raw 24-hour time-series rows are intentionally "
        "excluded, so do not claim evidence that is not present in the packet. "
        f"{_openai_domain_guidelines()} "
        "Keep deterministic metrics consistent with factPacket.performance. If "
        "calibration facts or snapshot facts directly contain a flag or numeric "
        "control value, evidenceStatus may be confirmed. If the pattern is "
        "inferred only from daily diagnostics or metrics, use partial. If the "
        "overwritten intraday timeline makes a claim unverifiable, use "
        "not_observed and confidence low. Return at most three hypotheses and "
        "two recommendations per locale. Every featureRecommendations item "
        "must set autoApply to false. Output only the narrative layer for each "
        "locale; date, language, performance, inputRefs, dataQuality, and "
        "inputSnapshot are managed by code."
    )


def _extract_response_text(data: dict) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                return text
    raise ValueError("OpenAI response did not contain output text")


def _call_openai_analysis(context: dict, api_key: str, model: str) -> dict:
    context = _sanitize_openai_context(context)
    payload = {
        "model": model,
        "instructions": _openai_instructions(context.get("language", "ko")),
        "input": json.dumps(context, ensure_ascii=False),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "daily_ops_report_analysis",
                "schema": _openai_analysis_schema(),
                "strict": True,
            }
        },
        "max_output_tokens": 4000,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    timeout_seconds = _env_int(
        "OPENAI_DAILY_REPORT_TIMEOUT_SECONDS",
        OPENAI_DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        data = json.loads(response.read().decode("utf-8"))
    return json.loads(_extract_response_text(data))


def _call_openai_multilingual_analysis(
    context: dict,
    api_key: str,
    model: str,
    languages: list[str],
) -> dict:
    context = _sanitize_openai_context(context)
    payload = {
        "model": model,
        "instructions": _openai_multilingual_instructions(languages),
        "input": json.dumps(context, ensure_ascii=False),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "daily_ops_report_multilingual_analysis",
                "schema": _openai_multilingual_analysis_schema(languages),
                "strict": True,
            }
        },
        "max_output_tokens": 9000,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    timeout_seconds = _env_int(
        "OPENAI_DAILY_REPORT_LOCALIZATION_TIMEOUT_SECONDS",
        OPENAI_DEFAULT_LOCALIZATION_TIMEOUT_SECONDS,
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        data = json.loads(response.read().decode("utf-8"))
    return json.loads(_extract_response_text(data))


def _openai_localization_instructions(languages: list[str]) -> str:
    language_names = {
        "ko": "Korean",
        "en": "English",
        "ja": "Japanese",
    }
    readable = ", ".join(
        f"{language}={language_names.get(language, language)}"
        for language in languages
    )
    return (
        "You localize an English master operations report for Tokyo-area "
        "electricity demand forecasting. Produce reports for these target "
        f"locales: {readable}. Do not perform new analysis and do not introduce "
        "new metrics, hours, feature names, severities, confidence levels, "
        "evidenceStatus values, recommendation targets, or calibration events. "
        "Preserve the English master's logical structure, IDs, numeric evidence, "
        "related hours, related time bands, related features, recommendation "
        "priority/type/target/linkedHypotheses, and autoApply=false. Translate "
        "and localize only natural-language fields: headline, summary, title, "
        "explanation, counterEvidence, suggestion, expectedEffect, risk, "
        "validationPlan, operatorNotes, and limitations. If a claim cannot be "
        "translated cleanly, keep the original numeric fact and translate the "
        "surrounding explanation conservatively. For ko, write natural Korean "
        "using Hangul-based sentences; do not emit mojibake, pseudo-CJK, or "
        "Chinese-only text. For ja, write natural modern Japanese; do not emit "
        "mojibake or pseudo-CJK text."
    )


def _call_openai_localization_analysis(
    context: dict,
    api_key: str,
    model: str,
    languages: list[str],
) -> dict:
    context = _sanitize_openai_context(context)
    payload = {
        "model": model,
        "instructions": _openai_localization_instructions(languages),
        "input": json.dumps(context, ensure_ascii=False),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "daily_ops_report_localization_analysis",
                "schema": _openai_multilingual_analysis_schema(languages),
                "strict": True,
            }
        },
        "max_output_tokens": 6000,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    timeout_seconds = _env_int(
        "OPENAI_DAILY_REPORT_LOCALIZATION_TIMEOUT_SECONDS",
        OPENAI_DEFAULT_LOCALIZATION_TIMEOUT_SECONDS,
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        data = json.loads(response.read().decode("utf-8"))
    return json.loads(_extract_response_text(data))


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _normalize_evidence(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        metric = item.get("metric")
        if not source or not metric:
            continue
        result.append({
            "source": str(source),
            "metric": str(metric),
            "value": item.get("value"),
            "unit": item.get("unit"),
            "hour": item.get("hour"),
            "timeBand": item.get("timeBand"),
        })
    return result


def _meaningful_text(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower() in {"", "none", "null", "n/a", "-"}:
        return ""
    return text


def _is_placeholder_title(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in {
        "원인 가설",
        "root-cause hypothesis",
        "root cause hypothesis",
        "hypothesis",
        "原因仮説",
        "原因の仮説",
    }


def _normalize_hypotheses(value: Any, fallback: list[dict]) -> list[dict]:
    if not isinstance(value, list):
        return fallback

    result = []
    for index, item in enumerate(value[:5], start=1):
        if not isinstance(item, dict):
            continue
        evidence_status = item.get("evidenceStatus")
        if evidence_status not in {"confirmed", "partial", "not_observed"}:
            evidence_status = "partial"
        confidence = item.get("confidence")
        if confidence not in {"low", "medium", "high"}:
            confidence = "medium"
        if evidence_status == "not_observed":
            confidence = "low"
        severity = item.get("severity")
        if severity not in {"info", "warning", "critical"}:
            severity = "info"
        title = _meaningful_text(item.get("title"))
        explanation = _meaningful_text(item.get("explanation"))
        if not title or _is_placeholder_title(title) or not explanation:
            continue
        result.append({
            "id": str(item.get("id") or f"h{index}"),
            "severity": severity,
            "confidence": confidence,
            "evidenceStatus": evidence_status,
            "title": title,
            "explanation": explanation,
            "evidence": _normalize_evidence(item.get("evidence")),
            "relatedHours": [
                int(hour) for hour in (item.get("relatedHours") or [])
                if isinstance(hour, int)
            ],
            "relatedTimeBands": _as_string_list(item.get("relatedTimeBands")),
            "relatedFeatures": _as_string_list(item.get("relatedFeatures")),
            "counterEvidence": _as_string_list(item.get("counterEvidence")),
        })
    return result or fallback


def _normalize_recommendations(value: Any, fallback: list[dict]) -> list[dict]:
    if not isinstance(value, list):
        return fallback

    result = []
    for index, item in enumerate(value[:3], start=1):
        if not isinstance(item, dict):
            continue
        priority = item.get("priority")
        if priority not in {"low", "medium", "high"}:
            priority = "medium"
        rec_type = item.get("type")
        if rec_type not in {"feature_engineering", "calibration", "data_quality", "evaluation"}:
            rec_type = "feature_engineering"
        target = _meaningful_text(item.get("target"))
        suggestion = _meaningful_text(item.get("suggestion"))
        expected_effect = _meaningful_text(item.get("expectedEffect"))
        risk = _meaningful_text(item.get("risk"))
        validation_plan = _meaningful_text(item.get("validationPlan"))
        if (
            not target
            or target == "review_candidate"
            or not suggestion
            or not expected_effect
            or not risk
            or not validation_plan
        ):
            continue
        result.append({
            "id": str(item.get("id") or f"r{index}"),
            "priority": priority,
            "type": rec_type,
            "target": target,
            "suggestion": suggestion,
            "expectedEffect": expected_effect,
            "risk": risk,
            "validationPlan": validation_plan,
            "linkedHypotheses": _as_string_list(item.get("linkedHypotheses")),
            "autoApply": False,
        })
    return result or fallback


def _merge_openai_analysis(fallback_report: dict, analysis: dict, model: str) -> dict:
    report = json.loads(json.dumps(fallback_report, ensure_ascii=False))
    summary = analysis.get("executiveSummary") if isinstance(analysis, dict) else {}
    if not isinstance(summary, dict):
        summary = {}

    severity = summary.get("severity")
    if severity not in {"info", "warning", "critical"}:
        severity = report["executiveSummary"]["severity"]
    confidence = summary.get("confidence")
    if confidence not in {"low", "medium", "high"}:
        confidence = report["executiveSummary"]["confidence"]
    model_verdict = summary.get("modelVerdict")
    if model_verdict not in {
        "model_better",
        "tepco_better",
        "close",
        "mixed",
        "insufficient",
    }:
        model_verdict = report["executiveSummary"]["modelVerdict"]

    report["generator"] = {
        "provider": "openai",
        "model": model,
        "promptVersion": OPENAI_PROMPT_VERSION,
        "schemaVersion": SCHEMA_VERSION,
    }
    report["contentLanguage"] = report.get("language", "ko")
    report["executiveSummary"] = {
        "severity": severity,
        "headline": str(summary.get("headline") or report["executiveSummary"]["headline"]),
        "summary": str(summary.get("summary") or report["executiveSummary"]["summary"]),
        "modelVerdict": model_verdict,
        "confidence": confidence,
    }
    report["rootCauseHypotheses"] = _normalize_hypotheses(
        analysis.get("rootCauseHypotheses"),
        report["rootCauseHypotheses"],
    )
    report["featureRecommendations"] = _normalize_recommendations(
        analysis.get("featureRecommendations"),
        report["featureRecommendations"],
    )
    operator_notes = _as_string_list(analysis.get("operatorNotes"))
    limitations = _as_string_list(analysis.get("limitations"))
    if operator_notes:
        report["operatorNotes"] = operator_notes
    else:
        messages = MESSAGES.get(report.get("language"), MESSAGES["ko"])
        fallback_note = messages["fallback_note"]
        report["operatorNotes"] = [
            note for note in report.get("operatorNotes", [])
            if note != fallback_note
        ]
    messages = MESSAGES.get(report.get("language"), MESSAGES["ko"])
    fallback_note = messages["fallback_note"]
    if limitations:
        report["limitations"] = [
            item for item in limitations
            if item != fallback_note
        ]
    else:
        report["limitations"] = [
            item for item in report.get("limitations", [])
            if item != fallback_note
        ]
    report["dataQuality"]["limitations"] = report["limitations"]
    return report


def _merge_openai_multilingual_analysis(
    fallback_reports: dict[str, dict],
    analysis: dict,
    model: str,
    languages: list[str],
) -> dict[str, dict]:
    reports_payload = analysis.get("reports") if isinstance(analysis, dict) else {}
    if not isinstance(reports_payload, dict):
        reports_payload = {}

    merged = {}
    for language, fallback_report in fallback_reports.items():
        language_payload = reports_payload.get(language)
        if language in languages and isinstance(language_payload, dict):
            merged[language] = _merge_openai_analysis(
                fallback_report,
                language_payload,
                model,
            )
        else:
            merged[language] = fallback_report
    return merged


def _analysis_layer_from_report(report: dict) -> dict:
    return {
        "executiveSummary": json.loads(json.dumps(
            report.get("executiveSummary") or {},
            ensure_ascii=False,
        )),
        "rootCauseHypotheses": json.loads(json.dumps(
            (report.get("rootCauseHypotheses") or [])[:3],
            ensure_ascii=False,
        )),
        "featureRecommendations": json.loads(json.dumps(
            (report.get("featureRecommendations") or [])[:2],
            ensure_ascii=False,
        )),
        "operatorNotes": _as_string_list(report.get("operatorNotes"))[:3],
        "limitations": _as_string_list(report.get("limitations"))[:3],
    }


def _localized_text(source: dict, field: str, fallback: Any) -> Any:
    value = source.get(field) if isinstance(source, dict) else None
    if isinstance(fallback, list):
        localized = _as_string_list(value)
        return localized if localized else fallback
    text = _meaningful_text(value)
    return text or fallback


def _items_by_id(items: Any) -> dict[str, dict]:
    if not isinstance(items, list):
        return {}
    return {
        str(item.get("id")): item
        for item in items
        if isinstance(item, dict) and item.get("id")
    }


def _align_localized_analysis(master: dict, localized: dict) -> dict:
    """Keep OpenAI's English analysis as the source of structure and facts.

    The second OpenAI call is allowed to translate prose, but it should not
    silently alter the engineering conclusion.  This alignment step enforces
    that contract before the localized payload is merged into deterministic
    report shells.
    """
    if not isinstance(localized, dict):
        localized = {}

    master_summary = master.get("executiveSummary") or {}
    localized_summary = localized.get("executiveSummary") or {}
    summary = json.loads(json.dumps(master_summary, ensure_ascii=False))
    summary["headline"] = _localized_text(
        localized_summary,
        "headline",
        summary.get("headline", ""),
    )
    summary["summary"] = _localized_text(
        localized_summary,
        "summary",
        summary.get("summary", ""),
    )

    localized_hypotheses = _items_by_id(localized.get("rootCauseHypotheses"))
    aligned_hypotheses = []
    for index, hypothesis in enumerate(master.get("rootCauseHypotheses") or []):
        if not isinstance(hypothesis, dict):
            continue
        aligned = json.loads(json.dumps(hypothesis, ensure_ascii=False))
        candidate = localized_hypotheses.get(str(aligned.get("id")))
        if candidate is None:
            localized_list = localized.get("rootCauseHypotheses") or []
            if index < len(localized_list) and isinstance(localized_list[index], dict):
                candidate = localized_list[index]
        if isinstance(candidate, dict):
            aligned["title"] = _localized_text(
                candidate,
                "title",
                aligned.get("title", ""),
            )
            aligned["explanation"] = _localized_text(
                candidate,
                "explanation",
                aligned.get("explanation", ""),
            )
            aligned["counterEvidence"] = _localized_text(
                candidate,
                "counterEvidence",
                aligned.get("counterEvidence", []),
            )
        aligned_hypotheses.append(aligned)

    localized_recommendations = _items_by_id(localized.get("featureRecommendations"))
    aligned_recommendations = []
    for index, recommendation in enumerate(master.get("featureRecommendations") or []):
        if not isinstance(recommendation, dict):
            continue
        aligned = json.loads(json.dumps(recommendation, ensure_ascii=False))
        candidate = localized_recommendations.get(str(aligned.get("id")))
        if candidate is None:
            localized_list = localized.get("featureRecommendations") or []
            if index < len(localized_list) and isinstance(localized_list[index], dict):
                candidate = localized_list[index]
        if isinstance(candidate, dict):
            for field in ("suggestion", "expectedEffect", "risk", "validationPlan"):
                aligned[field] = _localized_text(candidate, field, aligned.get(field, ""))
        aligned["autoApply"] = False
        aligned_recommendations.append(aligned)

    return {
        "executiveSummary": summary,
        "rootCauseHypotheses": aligned_hypotheses,
        "featureRecommendations": aligned_recommendations,
        "operatorNotes": _localized_text(
            localized,
            "operatorNotes",
            master.get("operatorNotes") or [],
        ),
        "limitations": _localized_text(
            localized,
            "limitations",
            master.get("limitations") or [],
        ),
    }


def _analysis_text_blob(analysis: dict) -> str:
    parts: list[str] = []
    summary = analysis.get("executiveSummary") or {}
    if isinstance(summary, dict):
        parts.extend([
            str(summary.get("headline") or ""),
            str(summary.get("summary") or ""),
        ])
    for hypothesis in analysis.get("rootCauseHypotheses") or []:
        if isinstance(hypothesis, dict):
            parts.extend([
                str(hypothesis.get("title") or ""),
                str(hypothesis.get("explanation") or ""),
            ])
    for recommendation in analysis.get("featureRecommendations") or []:
        if isinstance(recommendation, dict):
            parts.extend([
                str(recommendation.get("suggestion") or ""),
                str(recommendation.get("expectedEffect") or ""),
                str(recommendation.get("risk") or ""),
                str(recommendation.get("validationPlan") or ""),
            ])
    parts.extend(_as_string_list(analysis.get("operatorNotes")))
    parts.extend(_as_string_list(analysis.get("limitations")))
    return "\n".join(parts)


def _validate_localized_analysis(language: str, analysis: dict) -> None:
    text = _analysis_text_blob(analysis)
    if language == "ko" and not re.search(r"[\uac00-\ud7a3]", text):
        raise ValueError("Korean localization did not contain Hangul text")
    if language == "ja" and not re.search(r"[\u3040-\u30ff]", text):
        raise ValueError("Japanese localization did not contain kana text")


def _english_master_localization_fallback_report(
    fallback_report: dict,
    master_report: dict,
    analysis_model: str,
    localization_model: str,
    error: Exception | str,
) -> dict:
    report = _merge_openai_analysis(
        fallback_report,
        _analysis_layer_from_report(master_report),
        analysis_model,
    )
    report["contentLanguage"] = "en"
    report["generator"]["localizationModel"] = localization_model
    report["generator"]["localizationStatus"] = "fallback_en"
    report["generator"]["localizationFallback"] = "en"
    note = f"Localization failed; displaying the English master report. ({error})"
    report["operatorNotes"] = [
        note,
        *[
            item for item in report.get("operatorNotes", [])
            if item != note
        ],
    ]
    return report


def _consume_openai_budget(budget: dict[str, int]) -> bool:
    if budget.get("remaining", 0) <= 0:
        return False
    budget["remaining"] = max(0, budget.get("remaining", 0) - 1)
    budget["used"] = budget.get("used", 0) + 1
    return True


def _run_openai_master_localization_chain(
    public_dir: Path,
    date_iso: str,
    generated_at: str,
    fallback_reports: dict[str, dict],
    target_languages: list[str],
    api_key: str,
    analysis_model: str,
    localization_model: str,
    budget: dict[str, int],
) -> dict[str, dict]:
    merged_reports = {
        language: fallback_reports[language]
        for language in target_languages
        if language in fallback_reports
    }
    if not merged_reports:
        return merged_reports

    english_fallback = fallback_reports.get("en")
    if english_fallback is None:
        english_fallback = build_ai_daily_report(
            public_dir,
            date_iso,
            generated_at,
            language="en",
            use_openai=False,
        )
    if english_fallback.get("availability") != "ok":
        return merged_reports

    localization_targets = [
        language for language in target_languages
        if language != "en" and language in merged_reports
    ]
    if "en" not in merged_reports and localization_targets and budget.get("remaining", 0) < 2:
        return merged_reports

    if not _consume_openai_budget(budget):
        return merged_reports

    master_context = _sanitize_openai_context(
        _load_openai_context(public_dir, english_fallback)
    )
    master_analysis = _call_openai_analysis(master_context, api_key, analysis_model)
    master_report = _merge_openai_analysis(
        english_fallback,
        master_analysis,
        analysis_model,
    )
    master_report["contentLanguage"] = "en"
    master_report["generator"]["localizationStatus"] = "not_requested"
    if "en" in merged_reports:
        merged_reports["en"] = master_report

    if not localization_targets:
        return merged_reports
    if not _consume_openai_budget(budget):
        return merged_reports

    master_layer = _analysis_layer_from_report(master_report)
    localization_context = {
        "sourceLanguage": "en",
        "targetLanguages": localization_targets,
        "featureCatalog": FEATURE_CATALOG,
        "masterReport": master_layer,
    }
    try:
        localized_payload = _call_openai_localization_analysis(
            localization_context,
            api_key,
            localization_model,
            localization_targets,
        )
        localized_reports = localized_payload.get("reports")
        if not isinstance(localized_reports, dict):
            localized_reports = {}
        for language in localization_targets:
            aligned_analysis = _align_localized_analysis(
                master_layer,
                localized_reports.get(language) or {},
            )
            _validate_localized_analysis(language, aligned_analysis)
            merged_reports[language] = _merge_openai_analysis(
                fallback_reports[language],
                aligned_analysis,
                analysis_model,
            )
            merged_reports[language]["contentLanguage"] = language
            merged_reports[language]["generator"]["localizationModel"] = localization_model
            merged_reports[language]["generator"]["localizationStatus"] = "ok"
    except (
        OSError,
        urllib.error.URLError,
        TimeoutError,
        ValueError,
        json.JSONDecodeError,
    ) as e:
        for language in localization_targets:
            merged_reports[language] = _english_master_localization_fallback_report(
                fallback_reports[language],
                master_report,
                analysis_model,
                localization_model,
                e,
            )
    return merged_reports


def _openai_failure_reports(
    fallback_reports: dict[str, dict],
    error: Exception,
    languages: list[str],
) -> dict[str, dict]:
    reports = {}
    for language, fallback_report in fallback_reports.items():
        report = json.loads(json.dumps(fallback_report, ensure_ascii=False))
        if language in languages:
            messages = MESSAGES.get(language, MESSAGES["ko"])
            report["operatorNotes"] = [
                messages["openai_failed_template"].format(error=error),
                *report.get("operatorNotes", []),
            ]
        reports[language] = report
    return reports


def build_ai_daily_report(
    public_dir: Path,
    date_iso: str,
    generated_at: str,
    language: str = "ko",
    use_openai: bool | None = None,
) -> dict:
    _load_local_dotenv(public_dir)
    fallback_report = _build_fallback_ai_daily_report(
        public_dir,
        date_iso,
        generated_at,
        language=language,
    )
    if fallback_report.get("availability") != "ok":
        return fallback_report

    api_key = os.getenv("OPENAI_API_KEY")
    should_use_openai = bool(api_key) if use_openai is None else use_openai
    if not should_use_openai or not api_key:
        return fallback_report

    model = os.getenv("OPENAI_DAILY_REPORT_MODEL") or OPENAI_DEFAULT_MODEL
    try:
        context = _sanitize_openai_context(
            _load_openai_context(public_dir, fallback_report)
        )
        analysis = _call_openai_analysis(context, api_key, model)
        return _merge_openai_analysis(fallback_report, analysis, model)
    except (OSError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as e:
        messages = MESSAGES.get(fallback_report.get("language"), MESSAGES["ko"])
        fallback_report["operatorNotes"] = [
            messages["openai_failed_template"].format(error=e),
            *fallback_report.get("operatorNotes", []),
        ]
        return fallback_report


def _load_existing_report(path: Path, language: str) -> dict | None:
    payload = _load_json(path)
    if not payload:
        return None
    if payload.get("availability") != "ok":
        return None
    if payload.get("reportType") != REPORT_TYPE:
        return None
    if payload.get("language") != language:
        return None
    return payload


def _index_summary(report: dict) -> dict:
    summary = report.get("performance") or {}
    executive = report.get("executiveSummary") or {}
    return {
        "date": report["date"],
        "availability": report.get("availability", "not_yet_available"),
        "severity": executive.get("severity"),
        "headline": executive.get("headline"),
        "modelVerdict": executive.get("modelVerdict"),
        "modelMaeMw": summary.get("modelMaeMw"),
        "tepcoMaeMw": summary.get("tepcoMaeMw"),
    }


def build_ai_daily_reports(
    public_dir: Path,
    generated_at: str,
    max_days: int = 14,
    language: str = "ko",
    use_openai: bool | None = None,
    existing_report_dir: Path | None = None,
    skip_existing: bool = False,
    openai_budget: dict[str, int] | None = None,
    openai_locales: set[str] | None = None,
    openai_latest_only: bool = True,
) -> tuple[dict, list[dict]]:
    _load_local_dotenv(public_dir)
    daily_index = _load_json(public_dir / "reports" / "daily" / "index.json")
    if not daily_index:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "timezone": TIMEZONE,
            "generatedAt": generated_at,
            "availability": "not_yet_available",
            "latest": None,
            "reports": [],
        }, []

    dates = [
        row["date"]
        for row in daily_index.get("reports", [])
        if row.get("availability") == "ok"
    ][-max_days:]
    latest_date = dates[-1] if dates else None
    budget = openai_budget
    if budget is None:
        budget = {
            "remaining": _env_int(
                "OPENAI_DAILY_REPORT_MAX_CALLS_PER_RUN",
                OPENAI_DEFAULT_MAX_CALLS_PER_RUN,
            ),
            "used": 0,
        }
    allowed_locales = (
        openai_locales
        if openai_locales is not None
        else _env_csv("OPENAI_DAILY_REPORT_LOCALES", OPENAI_DEFAULT_LOCALES)
    )
    latest_only = _env_bool("OPENAI_DAILY_REPORT_LATEST_ONLY", openai_latest_only)
    api_key_available = bool(os.getenv("OPENAI_API_KEY"))
    reports = []
    for date_iso in dates:
        existing_report = None
        if skip_existing and existing_report_dir is not None:
            existing_report = _load_existing_report(
                existing_report_dir / f"{date_iso}.json",
                language,
            )
        if existing_report:
            reports.append(existing_report)
            continue

        should_attempt_openai = (
            api_key_available
            and (bool(api_key_available) if use_openai is None else use_openai)
            and language in allowed_locales
            and budget.get("remaining", 0) > 0
            and (not latest_only or date_iso == latest_date)
        )
        if should_attempt_openai:
            budget["remaining"] = max(0, budget.get("remaining", 0) - 1)
            budget["used"] = budget.get("used", 0) + 1

        reports.append(
            build_ai_daily_report(
                public_dir,
                date_iso,
                generated_at,
                language=language,
                use_openai=should_attempt_openai,
            )
        )
    reports = [
        report for report in reports
        if report.get("availability") == "ok"
    ]

    return {
        "schemaVersion": SCHEMA_VERSION,
        "timezone": TIMEZONE,
        "generatedAt": generated_at,
        "availability": "ok" if reports else "not_yet_available",
        "latest": _index_summary(reports[-1]) if reports else None,
        "reports": [_index_summary(report) for report in reports],
    }, reports


def build_ai_daily_reports_multilingual(
    public_dir: Path,
    generated_at: str,
    max_days: int = 14,
    languages: list[str] | tuple[str, ...] = ("ko", "en", "ja"),
    use_openai: bool | None = None,
    existing_report_root: Path | None = None,
    skip_existing: bool = False,
    openai_budget: dict[str, int] | None = None,
    openai_locales: set[str] | None = None,
    openai_latest_only: bool = True,
) -> tuple[dict[str, dict], dict[str, list[dict]], dict[str, int]]:
    _load_local_dotenv(public_dir)
    daily_index = _load_json(public_dir / "reports" / "daily" / "index.json")
    if not daily_index:
        empty_index = {
            "schemaVersion": SCHEMA_VERSION,
            "timezone": TIMEZONE,
            "generatedAt": generated_at,
            "availability": "not_yet_available",
            "latest": None,
            "reports": [],
        }
        return {
            language: empty_index
            for language in languages
        }, {language: [] for language in languages}, {"remaining": 0, "used": 0}

    dates = [
        row["date"]
        for row in daily_index.get("reports", [])
        if row.get("availability") == "ok"
    ][-max_days:]
    latest_date = dates[-1] if dates else None
    budget = openai_budget
    if budget is None:
        budget = {
            "remaining": _env_int(
                "OPENAI_DAILY_REPORT_MAX_CALLS_PER_RUN",
                OPENAI_DEFAULT_MAX_CALLS_PER_RUN,
            ),
            "used": 0,
        }
    allowed_locales = (
        openai_locales
        if openai_locales is not None
        else _env_csv("OPENAI_DAILY_REPORT_LOCALES", OPENAI_DEFAULT_LOCALES)
    )
    latest_only = _env_bool("OPENAI_DAILY_REPORT_LATEST_ONLY", openai_latest_only)
    api_key = os.getenv("OPENAI_API_KEY")
    should_use_openai = bool(api_key) if use_openai is None else use_openai
    model = os.getenv("OPENAI_DAILY_REPORT_MODEL") or OPENAI_DEFAULT_MODEL
    localization_model = (
        os.getenv("OPENAI_DAILY_REPORT_LOCALIZATION_MODEL")
        or OPENAI_DEFAULT_LOCALIZATION_MODEL
    )

    reports_by_language: dict[str, list[dict]] = {
        language: []
        for language in languages
    }
    for date_iso in dates:
        date_reports: dict[str, dict] = {}
        missing_reports: dict[str, dict] = {}

        for language in languages:
            existing_report = None
            if skip_existing and existing_report_root is not None:
                existing_report = _load_existing_report(
                    existing_report_root / language / f"{date_iso}.json",
                    language,
                )
            if existing_report:
                date_reports[language] = existing_report
                continue

            fallback_report = build_ai_daily_report(
                public_dir,
                date_iso,
                generated_at,
                language=language,
                use_openai=False,
            )
            date_reports[language] = fallback_report
            if fallback_report.get("availability") == "ok":
                missing_reports[language] = fallback_report

        target_languages = [
            language for language in languages
            if language in allowed_locales
            and language in missing_reports
        ]
        should_attempt_openai = (
            bool(api_key)
            and bool(should_use_openai)
            and bool(target_languages)
            and budget.get("remaining", 0) > 0
            and (not latest_only or date_iso == latest_date)
        )
        if should_attempt_openai:
            try:
                merged_reports = _run_openai_master_localization_chain(
                    public_dir,
                    date_iso,
                    generated_at,
                    {
                        language: missing_reports[language]
                        for language in target_languages
                    },
                    target_languages,
                    str(api_key),
                    model,
                    localization_model,
                    budget,
                )
            except (
                OSError,
                urllib.error.URLError,
                TimeoutError,
                ValueError,
                json.JSONDecodeError,
            ) as e:
                merged_reports = _openai_failure_reports(
                    {
                        language: missing_reports[language]
                        for language in target_languages
                    },
                    e,
                    target_languages,
                )
            for language, report in merged_reports.items():
                date_reports[language] = report

        for language in languages:
            report = date_reports.get(language)
            if report and report.get("availability") == "ok":
                reports_by_language[language].append(report)

    indexes = {
        language: {
            "schemaVersion": SCHEMA_VERSION,
            "timezone": TIMEZONE,
            "generatedAt": generated_at,
            "availability": "ok" if reports else "not_yet_available",
            "latest": _index_summary(reports[-1]) if reports else None,
            "reports": [_index_summary(report) for report in reports],
        }
        for language, reports in reports_by_language.items()
    }
    return indexes, reports_by_language, budget


def main() -> None:
    parser = argparse.ArgumentParser(description="Build AI daily operation reports")
    parser.add_argument("--public-dir", default="web/public")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--max-days", type=int, default=14)
    parser.add_argument("--language", default="ko")
    parser.add_argument("--languages", default="ko,en,ja")
    parser.add_argument("--use-openai", action="store_true")
    parser.add_argument("--no-openai", action="store_true")
    parser.add_argument(
        "--openai-max-calls",
        type=int,
        default=None,
        help="Maximum OpenAI report attempts in this run. Defaults to OPENAI_DAILY_REPORT_MAX_CALLS_PER_RUN or 2.",
    )
    parser.add_argument(
        "--openai-languages",
        default=None,
        help="Comma-separated locales allowed to use OpenAI. Defaults to OPENAI_DAILY_REPORT_LOCALES or ko.",
    )
    parser.add_argument(
        "--openai-all-dates",
        action="store_true",
        help="Allow OpenAI for more than the latest daily report date, still capped by --openai-max-calls.",
    )
    parser.add_argument(
        "--overwrite-existing",
        action="store_true",
        help="Regenerate date report JSON even if it already exists.",
    )
    args = parser.parse_args()

    public_dir = Path(args.public_dir)
    out_dir = Path(args.out_dir) if args.out_dir else public_dir / "reports" / "ai" / "daily"
    generated_at = args.generated_at or _now_jst()

    use_openai = None
    if args.use_openai:
        use_openai = True
    if args.no_openai:
        use_openai = False

    languages = [
        language.strip()
        for language in (args.languages or args.language).split(",")
        if language.strip()
    ]
    latest = {}
    total_reports = 0
    openai_budget = {
        "remaining": (
            max(0, args.openai_max_calls)
            if args.openai_max_calls is not None
            else _env_int(
                "OPENAI_DAILY_REPORT_MAX_CALLS_PER_RUN",
                OPENAI_DEFAULT_MAX_CALLS_PER_RUN,
            )
        ),
        "used": 0,
    }
    openai_locales = (
        _csv_values(args.openai_languages)
        if args.openai_languages is not None
        else _env_csv("OPENAI_DAILY_REPORT_LOCALES", OPENAI_DEFAULT_LOCALES)
    )
    indexes, reports_by_language, openai_budget = build_ai_daily_reports_multilingual(
        public_dir,
        generated_at=generated_at,
        max_days=args.max_days,
        languages=languages,
        use_openai=use_openai,
        existing_report_root=out_dir,
        skip_existing=not args.overwrite_existing,
        openai_budget=openai_budget,
        openai_locales=openai_locales,
        openai_latest_only=not args.openai_all_dates,
    )
    for language in languages:
        language_dir = out_dir / language
        index = indexes[language]
        reports = reports_by_language[language]
        _write_json(language_dir / "index.json", index)
        for report in reports:
            report_path = language_dir / f"{report['date']}.json"
            if args.overwrite_existing or not report_path.exists():
                _write_json(report_path, report)
        if language == args.language:
            _write_json(out_dir / "index.json", index)
            for report in reports:
                report_path = out_dir / f"{report['date']}.json"
                if args.overwrite_existing or not report_path.exists():
                    _write_json(report_path, report)
            latest = index.get("latest") or {}
        total_reports += len(reports)
    print(
        "[AI-REPORT] daily reports updated "
        f"({total_reports} localized reports, latest={latest.get('date')}, "
        f"openai_attempts={openai_budget.get('used', 0)})"
    )


if __name__ == "__main__":
    main()
