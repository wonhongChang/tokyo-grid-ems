"""Build daily operation analysis reports.

The generator always produces a deterministic fallback report from the public
JSON artifacts.  When the project-scoped OpenAI key environment variable is
available it can ask OpenAI for the narrative analysis layer, while keeping
deterministic metrics and input references owned by this script.
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
OPENAI_PROMPT_VERSION = "openai_ops_report_v4"
PROJECT_OPENAI_API_KEY_ENV = "TOKYO_GRID_EMS_OPENAI_API_KEY"
OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
OPENAI_DEFAULT_LOCALIZATION_MODEL = "gpt-4o-mini"
OPENAI_DEFAULT_LOCALES = "ko,en,ja"
OPENAI_DEFAULT_MAX_CALLS_PER_RUN = 2
OPENAI_DEFAULT_ANALYSIS_TIMEOUT_SECONDS = 90
OPENAI_DEFAULT_LOCALIZATION_TIMEOUT_SECONDS = 180
REPORT_TYPE = "ai_daily_operation_report"
FOCUSED_ROW_RADIUS_HOURS = 2
MAX_FOCUSED_ROWS = 12
FREEZE_GAP_THRESHOLD_MW = 500.0
LARGE_CONTROL_DELTA_MW = 500.0
DEFAULT_INTRADAY_MAX_ABS_ADJUSTMENT_MW = 1200.0
LARGE_RESIDUAL_MW = 1000.0
SLOPE_MISMATCH_THRESHOLD_MW = 500.0
ROLLING_PATTERN_LOOKBACK_DAYS = 7
ROLLING_PATTERN_MIN_DIRECTION_DAYS = 2
ROLLING_PATTERN_MIN_MEAN_BIAS_MW = 300.0
PRIORITY_EVENT_LARGE_ERROR_MW = 1000.0
PRIORITY_EVENT_LARGE_SHAPE_ERROR_MW = 1000.0
PRIORITY_EVENT_BAND_GAP_MW = 300.0
PRIORITY_EVENT_MAX_ITEMS = 6

TIME_BAND_HOUR_RANGES = {
    "overnight": range(0, 6),
    "morning_ramp": range(6, 11),
    "daytime": range(11, 16),
    "late_afternoon": range(16, 19),
    "evening": range(19, 24),
}

FEATURE_CATALOG = [
    "intraday_correction.business_type_transition_prior",
    "intraday_correction.business_type_transition",
    "intraday_correction.positive_residual_mitigation",
    "intraday_correction.positive_residual_slope_damping",
    "intraday_correction.negative_residual_recovery_damping",
    "intraday_correction.negative_residual_continuity_floor",
    "intraday_correction.negative_residual_near_term_floor",
    "intraday_correction.evening_decline_continuity_guard",
    "intraday_correction.day_boundary_carryover",
    "intraday_correction.day_level_scale",
    "serving.published_forecast_freeze",
]
FEATURE_NAME_ALIASES = {
    "published_forecast_freeze": "serving.published_forecast_freeze",
    "forecast_freeze": "serving.published_forecast_freeze",
    "positive_residual_mitigation": "intraday_correction.positive_residual_mitigation",
    "positive_residual_slope_damping": "intraday_correction.positive_residual_slope_damping",
    "negative_residual_recovery_damping": "intraday_correction.negative_residual_recovery_damping",
    "negative_residual_continuity_floor": "intraday_correction.negative_residual_continuity_floor",
    "negative_residual_near_term_floor": "intraday_correction.negative_residual_near_term_floor",
    "evening_decline_continuity_guard": "intraday_correction.evening_decline_continuity_guard",
}
ALLOWED_RECOMMENDATION_TARGETS = set(FEATURE_CATALOG) | {
    "lag_24h",
    "lag_168h",
    "temp_c",
    "humidity_pct",
    "apparent_temp_c",
    "temp_delta_1h",
    "temp_delta_2h",
    "apparent_temp_delta_1h",
    "business_late_afternoon_x_temp_delta_1h",
    "cooling_load_3d_mean",
    "weather_source",
}

METRIC_TERM_REPLACEMENTS = (
    ("Mean Absolute Percentage Error", "Weighted Absolute Percentage Error"),
    ("mean absolute percentage error", "weighted absolute percentage error"),
    ("平均絶対パーセント誤差", "加重絶対パーセント誤差"),
    ("평균 절대 백분율 오차", "가중 절대 백분율 오차"),
    ("MAPE", "WAPE"),
    ("mape", "WAPE"),
)

GENERAL_TEXT_REPLACEMENTS = (
    ("TEPCO's model", "TEPCO forecast"),
    ("TEPCO model", "TEPCO forecast"),
    ("TEPCO의 모델", "TEPCO 예측"),
    ("TEPCOのモデル", "TEPCO予測"),
    ("significant operational risk", "meaningful forecast performance gap"),
    ("重大な運用リスク", "予測性能上の有意な差"),
    ("유의미한 운영 위험", "예측 성능상의 유의미한 차이"),
)

LOCALIZED_TEXT_REPLACEMENTS = {
    "ko": [
        ("중간의 행복한 실행", "중간에 덮어쓴 intraday 실행 내역"),
        ("중간의 인트라데이 실행", "중간에 덮어쓴 intraday 실행 내역"),
        ("중간 intraday 실행은", "중간에 덮어쓴 intraday 실행 내역은"),
        ("인트라데이 실행", "intraday 실행"),
        ("인트라데이", "intraday"),
        ("イントラデイ", "intraday"),
        ("요약된 운영적 증거", "요약 운영 지표"),
        ("보존된 캘리브레이션 스냅샷", "보존된 보정 스냅샷"),
        ("캘리브레이션 스냅샷", "보정 스냅샷"),
        ("스냅샷으로 재구성되었으므로, 덮어쓴 타임라인 세부정보는 직접 관찰되지 않음", "스냅샷으로만 재구성되므로, 전체 실행 타임라인은 직접 관찰되지 않음"),
        ("잔여 감쇠", "잔차 감쇠"),
        ("잔여 damping", "잔차 감쇠"),
        ("잔여", "잔차"),
        ("비즈니스 유형", "영업일 구분"),
        ("비즈니스 타입", "영업일 구분"),
        ("비즈니스 일", "영업일"),
        ("램프 창", "램프업 구간"),
        ("오전 램프와 늦은 오후 회복의 한 곳에 집중됨", "오전 램프업 구간과 늦은 오후 회복 구간에 집중됨"),
        ("오전 램프 구간", "오전 램프업 구간"),
        ("사전 적용", "prior 보정"),
        ("델타 오류", "변화량 오차"),
        ("긍정적인 불일치", "양수 오차"),
        ("긍정적일 경우", "양수일 경우"),
        ("긍정적이면", "양수이면"),
        ("긍정적", "양수"),
        ("notable한", "유의미한"),
        ("notable", "유의미한"),
        ("TEPCO 모델", "TEPCO 예측"),
        ("일일 오류", "일일 오차"),
        ("평균 절대 오류", "평균 절대 오차"),
        ("피크 수요 시간", "피크 수요 시간대"),
        ("2시간 감소", "2시간 감쇠"),
        ("램프업업", "램프업"),
    ],
    "ja": [
        ("インターデイ", "イントラデイ"),
        ("イントラデイラン", "イントラデイ実行"),
        ("ビジネスタイプ", "営業日/非営業日区分"),
        ("ビジネス日", "営業日"),
        ("ランプウィンドウ", "ランプアップ区間"),
        ("朝のランプ区間", "朝のランプアップ区間"),
        ("朝のランプと", "朝のランプアップと"),
        ("ランプアップアップ", "ランプアップ"),
        ("事前を有効", "prior補正を有効"),
        ("要約された運用証拠", "要約された運用指標"),
        ("保存されたキャリブレーションスナップショット", "保存された補正スナップショット"),
        ("キャリブレーションスナップショット", "補正スナップショット"),
        ("中間のイントラデイ実行はスナップショットから再構成されているため、上書きされたタイムラインの詳細は直接観察されない", "中間で上書きされたイントラデイ実行履歴はスナップショットからの再構成に限られるため、実行タイムライン全体は直接観測されない"),
        ("実際vsモデルデルタ誤差", "実績とモデルの変化量誤差"),
        ("残余ダンピング", "残差ダンピング"),
        ("残余", "残差"),
        ("正の不一致", "正方向の誤差"),
    ],
}

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


def _clean_env_value(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        return ""
    cleaned = value.strip().strip('"').strip("'")
    if cleaned != value:
        os.environ[name] = cleaned
    return cleaned


def _redact_error(error: Exception | str) -> str:
    text = str(error)
    text = re.sub(r"sk-[A-Za-z0-9_\-]+", "sk-***", text)
    text = re.sub(r"Bearer\s+[A-Za-z0-9_\-\.]+", "Bearer ***", text)
    return text


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
    forecast = _load_json(public_dir / "forecast" / f"{date_iso}.json")

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
    data_quality = _data_quality(actual, operation, limitations, calibration_history)
    diagnostic_context = _build_report_diagnostic_context(
        public_dir,
        date_iso,
        data_quality,
        calibration,
        calibration_history,
        actual,
        forecast,
    )

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
        "dataQuality": data_quality,
        "diagnosticContext": diagnostic_context,
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


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _round_number(value: Any, digits: int = 1) -> float | None:
    number = _as_float(value)
    if number is None:
        return None
    return round(number, digits)


def _signed_error_direction(value: Any) -> str | None:
    number = _as_float(value)
    if number is None:
        return None
    if number > 0:
        return "overprediction"
    if number < 0:
        return "underprediction"
    return "neutral"


def _band_bias_direction(bias_mw: Any, mae_mw: Any) -> str | None:
    bias = _as_float(bias_mw)
    if bias is None:
        return None
    mae = _as_float(mae_mw)
    if mae is not None and abs(bias) < max(100.0, mae * 0.35):
        return "mixed"
    return _signed_error_direction(bias)


def _annotate_error_direction(payload: dict, metric_key: str, direction_key: str) -> None:
    direction = _signed_error_direction(payload.get(metric_key))
    if direction is not None:
        payload[direction_key] = direction


def _annotate_time_bands(time_bands: list[dict] | None) -> list[dict]:
    annotated = []
    for band in time_bands or []:
        if not isinstance(band, dict):
            continue
        item = dict(band)
        direction = _band_bias_direction(
            item.get("modelBiasMw"),
            item.get("modelMaeMw"),
        )
        if direction is not None:
            item["modelBiasDirection"] = direction
            if direction == "mixed":
                item["directionNote"] = (
                    "mean bias is small relative to MAE; avoid broad "
                    "overprediction/underprediction wording for this band"
                )
        annotated.append(item)
    return annotated


def _annotate_top_misses(top_misses: list[dict] | None) -> list[dict]:
    annotated = []
    for miss in top_misses or []:
        if not isinstance(miss, dict):
            continue
        item = dict(miss)
        _annotate_error_direction(item, "modelErrorMw", "modelErrorDirection")
        _annotate_error_direction(item, "tepcoErrorMw", "tepcoErrorDirection")
        annotated.append(item)
    return annotated


def _hour_from_point(point: dict | None) -> int | None:
    if not isinstance(point, dict):
        return None
    hour = point.get("hour")
    if hour is not None:
        try:
            hour_int = int(hour)
        except (TypeError, ValueError):
            hour_int = -1
        if 0 <= hour_int <= 23:
            return hour_int

    ts = point.get("ts")
    if isinstance(ts, str):
        match = re.search(r"T(\d{2}):", ts)
        if match:
            hour_int = int(match.group(1))
            if 0 <= hour_int <= 23:
                return hour_int
    return None


def _series_by_hour(payload: dict | None) -> dict[int, dict]:
    if not isinstance(payload, dict):
        return {}
    by_hour: dict[int, dict] = {}
    for point in payload.get("series") or []:
        hour = _hour_from_point(point)
        if hour is not None:
            by_hour[hour] = point
    return by_hour


def _calibration_rows_by_hour(calibration: dict | None) -> dict[int, dict]:
    if not isinstance(calibration, dict):
        return {}
    by_hour: dict[int, dict] = {}
    for row in calibration.get("hourlyDiagnostics") or []:
        hour = _hour_from_point(row)
        if hour is not None:
            by_hour[hour] = row
    return by_hour


def _compact_residual_carryover_item(item: dict | None) -> dict | None:
    if not isinstance(item, dict):
        return None
    compact = {
        "hour": item.get("hour"),
        "leadHours": item.get("leadHours"),
        "prePositiveDampingAdjustmentMw": _round_number(
            item.get("prePositiveDampingAdjustmentMw")
        ),
        "positiveResidualSlopeDampingFactor": _round_number(
            item.get("positiveResidualSlopeDampingFactor"),
            digits=3,
        ),
        "negativeResidualContinuityFloorMw": _round_number(
            item.get("negativeResidualContinuityFloorMw")
        ),
        "negativeResidualContinuityRestoreMw": _round_number(
            item.get("negativeResidualContinuityRestoreMw")
        ),
        "negativeResidualNearTermFloorMw": _round_number(
            item.get("negativeResidualNearTermFloorMw")
        ),
        "negativeResidualNearTermRestoreMw": _round_number(
            item.get("negativeResidualNearTermRestoreMw")
        ),
        "eveningDeclineContinuityMode": item.get("eveningDeclineContinuityMode"),
        "eveningDeclineContinuityReductionMw": _round_number(
            item.get("eveningDeclineContinuityReductionMw")
        ),
        "eveningDeclineContinuityCapMw": _round_number(
            item.get("eveningDeclineContinuityCapMw")
        ),
        "finalAdjustmentMw": _round_number(item.get("finalAdjustmentMw")),
    }
    return {key: value for key, value in compact.items() if value is not None}


def _selected_residual_carryover_items(items: list[dict], max_items: int = 8) -> list[dict]:
    compact_items = [
        compact
        for compact in (_compact_residual_carryover_item(item) for item in items)
        if compact
    ]
    if len(compact_items) <= max_items:
        return compact_items

    def priority(item: dict) -> tuple[int, float]:
        factor = _as_float(item.get("positiveResidualSlopeDampingFactor"))
        final_adjustment = abs(_as_float(item.get("finalAdjustmentMw")) or 0.0)
        damped = factor is not None and factor < 0.999
        continuity_floor = (
            (_as_float(item.get("negativeResidualContinuityRestoreMw")) or 0.0)
            > 0.0
        )
        near_term_floor = (
            (_as_float(item.get("negativeResidualNearTermRestoreMw")) or 0.0)
            > 0.0
        )
        evening_guard = (
            (_as_float(item.get("eveningDeclineContinuityReductionMw")) or 0.0)
            > 0.0
        )
        large = final_adjustment >= LARGE_CONTROL_DELTA_MW
        return (
            1 if damped or continuity_floor or near_term_floor or evening_guard or large else 0,
            final_adjustment,
        )

    selected = sorted(compact_items, key=priority, reverse=True)[:max_items]
    return sorted(selected, key=lambda item: int(item.get("hour", 99)))


def _drop_none_values(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if value is not None}


def _compact_calibration(calibration: dict | None) -> dict | None:
    if not calibration:
        return None
    correction = calibration.get("correction") or {}
    residual_carryover = _selected_residual_carryover_items(
        correction.get("residualCarryoverByHour") or []
    )
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
        "positiveResidualSlopeDampingApplied": correction.get("positiveResidualSlopeDampingApplied"),
        "positiveResidualSlopeDampingFactor": correction.get("positiveResidualSlopeDampingFactor"),
        "positiveResidualSlopeDampingMaxMw": correction.get("positiveResidualSlopeDampingMaxMw"),
        "negativeResidualContinuityFloorApplied": correction.get("negativeResidualContinuityFloorApplied"),
        "negativeResidualContinuityFloorMaxRestoreMw": correction.get("negativeResidualContinuityFloorMaxRestoreMw"),
        "negativeResidualNearTermFloorApplied": correction.get("negativeResidualNearTermFloorApplied"),
        "negativeResidualNearTermFloorMaxRestoreMw": correction.get("negativeResidualNearTermFloorMaxRestoreMw"),
        "negResidualRecoveryDampingApplied": correction.get("negResidualRecoveryDampingApplied"),
        "negResidualRecoveryDampingFactor": correction.get("negResidualRecoveryDampingFactor"),
        "residualCarryoverByHour": residual_carryover,
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


def _compact_morning_transition_diagnostics(diagnostics: dict | None) -> dict | None:
    if not diagnostics:
        return None
    morning = diagnostics.get("morningTransitionDiagnostics") or {}
    if not isinstance(morning, dict):
        return None
    rows = morning.get("rows") or []
    compact_rows = []
    for row in rows:
        compact = _drop_none_values({
            "hour": row.get("hour"),
            "actualMw": _round_number(row.get("actualMw")),
            "servedForecastMw": _round_number(row.get("servedForecastMw")),
            "modelErrorMw": _round_number(row.get("modelErrorMw")),
            "rawForecastMw": _round_number(row.get("rawForecastMw")),
            "preCalibrationForecastMw": _round_number(row.get("preCalibrationForecastMw")),
            "postCalibrationForecastMw": _round_number(row.get("postCalibrationForecastMw")),
            "publishedVsRecalculatedGapMw": _round_number(
                row.get("publishedVsRecalculatedGapMw")
            ),
            "morningLagDeltaExcessMw": _round_number(row.get("morningLagDeltaExcessMw")),
            "coolingDelta24hC": _round_number(row.get("coolingDelta24hC")),
            "humidityPct": _round_number(row.get("humidityPct")),
            "discomfortIndex": _round_number(row.get("discomfortIndex")),
            "weatherSourceConfidence": row.get("weatherSourceConfidence"),
            "residualAdjustmentMw": _round_number(row.get("residualAdjustmentMw")),
            "causeTags": row.get("causeTags") or [],
        })
        if compact:
            compact_rows.append(compact)

    def priority(row: dict) -> tuple[int, float]:
        tagged = 1 if row.get("causeTags") else 0
        abs_error = abs(_as_float(row.get("modelErrorMw")) or 0.0)
        freeze_gap = abs(_as_float(row.get("publishedVsRecalculatedGapMw")) or 0.0)
        return (tagged, max(abs_error, freeze_gap))

    selected_rows = sorted(compact_rows, key=priority, reverse=True)[:6]
    selected_rows = sorted(selected_rows, key=lambda row: int(row.get("hour", 99)))
    return {
        "summary": morning.get("summary"),
        "tagDefinitions": morning.get("tagDefinitions"),
        "selectedRows": selected_rows,
    }


def _build_coverage_context(
    data_quality: dict | None,
    calibration_facts: dict | None,
) -> dict:
    """Separate final daily coverage from intraday calibration coverage.

    Daily AI reports evaluate the completed previous day from finalized actual
    JSON. Operational-calibration JSON may be the last retained intraday
    snapshot before the final CSV arrived, so its observed/missing-hour counts
    must not be interpreted as daily performance coverage.
    """
    data_quality = data_quality if isinstance(data_quality, dict) else {}
    final_coverage = _drop_none_values({
        "scope": "final_daily_actuals_for_performance",
        "comparableHours": data_quality.get("comparableHours"),
        "observedHours": data_quality.get("observedHours"),
        "fallbackActualHours": data_quality.get("fallbackActualHours"),
    })
    context = {"finalActualCoverage": final_coverage}

    if isinstance(calibration_facts, dict):
        source_confidence = calibration_facts.get("sourceConfidence") or {}
        if not isinstance(source_confidence, dict):
            source_confidence = {}
        intraday_observed = (
            calibration_facts.get("observedHours")
            if calibration_facts.get("observedHours") is not None
            else source_confidence.get("usableObservedHours")
        )
        missing_hours = source_confidence.get("missingHours")
        if missing_hours is None and intraday_observed is not None:
            try:
                missing_hours = max(0, 24 - int(intraday_observed))
            except (TypeError, ValueError):
                missing_hours = None
        context["intradayCalibrationCoverage"] = _drop_none_values({
            "scope": "retained_intraday_calibration_snapshot_not_final_actual_csv",
            "observedHours": intraday_observed,
            "missingHours": missing_hours,
            "lastObservedHour": calibration_facts.get("lastObservedHour"),
            "sourceConfidence": source_confidence.get("level"),
        })

    return context


def _window_hours(center: int | None, radius: int = FOCUSED_ROW_RADIUS_HOURS) -> set[int]:
    if center is None:
        return set()
    return {
        hour
        for hour in range(center - radius, center + radius + 1)
        if 0 <= hour <= 23
    }


def _focused_hours_from_operation(operation: dict | None) -> set[int]:
    if not isinstance(operation, dict):
        return set()
    hours: set[int] = set()
    for miss in (operation.get("topMisses") or [])[:3]:
        hours.update(_window_hours(_hour_from_point(miss)))

    shape = operation.get("shape") or {}
    largest_delta = shape.get("largestDeltaMiss") or {}
    for key in ("fromHour", "toHour"):
        hour = largest_delta.get(key)
        if hour is not None:
            try:
                hours.update(_window_hours(int(hour), radius=1))
            except (TypeError, ValueError):
                pass
    for item in (shape.get("largeShapeBreaks") or [])[:3]:
        for key in ("fromHour", "toHour", "hour"):
            hour = item.get(key)
            if hour is not None:
                try:
                    hours.update(_window_hours(int(hour), radius=1))
                except (TypeError, ValueError):
                    pass
    return hours


def _focused_hours_from_calibration(calibration: dict | None) -> set[int]:
    if not isinstance(calibration, dict):
        return set()
    hours: set[int] = set()
    correction = calibration.get("correction") or {}
    for item in correction.get("residualCarryoverByHour") or []:
        hour = _hour_from_point(item)
        factor = _as_float(item.get("positiveResidualSlopeDampingFactor"))
        final_adjustment = abs(_as_float(item.get("finalAdjustmentMw")) or 0.0)
        pre_adjustment = abs(_as_float(item.get("prePositiveDampingAdjustmentMw")) or 0.0)
        if (
            factor is not None
            and factor < 0.999
            or final_adjustment >= LARGE_CONTROL_DELTA_MW
            or pre_adjustment >= LARGE_CONTROL_DELTA_MW
        ):
            hours.update(_window_hours(hour, radius=1))

    for row in calibration.get("hourlyDiagnostics") or []:
        hour = _hour_from_point(row)
        calibration_delta = abs(_as_float(row.get("calibrationDeltaMw")) or 0.0)
        post_residual = abs(_as_float(row.get("actualVsPostCalibrationResidualMw")) or 0.0)
        if calibration_delta >= LARGE_CONTROL_DELTA_MW or post_residual >= 1000.0:
            hours.update(_window_hours(hour, radius=1))
    return hours


def _forecast_freeze_gaps(
    forecast: dict | None,
    calibration: dict | None,
) -> list[dict]:
    forecast_by_hour = _series_by_hour(forecast)
    calibration_by_hour = _calibration_rows_by_hour(calibration)
    gaps = []
    for hour, row in calibration_by_hour.items():
        published = _round_number((forecast_by_hour.get(hour) or {}).get("forecastMw"))
        recalculated = _round_number(row.get("postCalibrationForecastMw"))
        pre_calibration = _round_number(row.get("preCalibrationForecastMw"))
        if recalculated is None:
            recalculated = pre_calibration
        if published is None or recalculated is None:
            continue
        gap = round(published - recalculated, 1)
        if abs(gap) < FREEZE_GAP_THRESHOLD_MW:
            continue
        gaps.append({
            "hour": hour,
            "publishedForecastMw": published,
            "latestRecalculatedForecastMw": recalculated,
            "freezeGapMw": gap,
        })
    return sorted(gaps, key=lambda item: abs(float(item["freezeGapMw"])), reverse=True)


def _build_freeze_context(
    forecast: dict | None,
    calibration: dict | None,
) -> dict | None:
    gaps = _forecast_freeze_gaps(forecast, calibration)
    if not gaps:
        return None
    return {
        "thresholdMw": FREEZE_GAP_THRESHOLD_MW,
        "largestGaps": gaps[:3],
        "interpretation": (
            "positive freezeGapMw means the published forecast is above the "
            "latest recalculated post-calibration line"
        ),
    }


def _time_band_code_for_hour(hour: int | None) -> str | None:
    if hour is None:
        return None
    for code, hours in TIME_BAND_HOUR_RANGES.items():
        if hour in hours:
            return code
    return None


def _time_band_label(operation: dict | None, code: str | None) -> str | None:
    if not code or not isinstance(operation, dict):
        return code
    for band in operation.get("timeBands") or []:
        if not isinstance(band, dict):
            continue
        if band.get("code") == code:
            return band.get("label") or code
    return code


def _feature_candidates_for_hour(hour: int | None) -> list[str]:
    candidates = ["lag_24h", "recent_same_business_type_mean"]
    if hour is None:
        return candidates
    if 6 <= hour <= 10:
        candidates.extend([
            "lag_24h_business_type_mismatch",
            "intraday_correction.business_type_transition",
            "intraday_correction.positive_residual_mitigation",
        ])
    elif 11 <= hour <= 15:
        candidates.extend([
            "business_midday_x_lag_24h_delta",
            "business_midday_x_recent_delta_mean",
            "intraday_correction.positive_residual_slope_damping",
        ])
    elif 16 <= hour <= 19:
        candidates.extend([
            "temp_delta_1h",
            "apparent_temp_delta_1h",
            "intraday_correction.evening_decline_continuity_guard",
        ])
    elif hour >= 20:
        candidates.extend([
            "lag_168h",
            "intraday_correction.day_boundary_carryover",
        ])
    return list(dict.fromkeys(candidates))


def _priority_event_severity(score: float | None) -> str:
    if score is not None and score >= 1500.0:
        return "warning"
    return "info"


def _build_analysis_priorities(
    operation: dict | None,
    diagnostic_context: dict | None,
) -> dict | None:
    if not isinstance(operation, dict):
        return None

    events: list[dict] = []
    summary = operation.get("summary") or {}
    top_misses = _annotate_top_misses((operation.get("topMisses") or [])[:3])
    for rank, miss in enumerate(top_misses, start=1):
        hour = _hour_from_point(miss)
        abs_error = _as_float(miss.get("modelAbsErrorMw"))
        if abs_error is None or abs_error < PRIORITY_EVENT_LARGE_ERROR_MW:
            continue
        tepco_abs = _as_float(miss.get("tepcoAbsErrorMw"))
        score = abs_error
        time_band = _time_band_code_for_hour(hour)
        events.append(_drop_none_values({
            "id": f"top_miss_h{hour}",
            "eventType": "large_absolute_error",
            "rank": rank,
            "priorityScoreMw": _round_number(score),
            "severity": _priority_event_severity(score),
            "hour": hour,
            "timeBand": time_band,
            "timeBandLabel": _time_band_label(operation, time_band),
            "modelErrorMw": _round_number(miss.get("modelErrorMw")),
            "modelAbsErrorMw": _round_number(abs_error),
            "tepcoAbsErrorMw": _round_number(tepco_abs),
            "modelErrorDirection": miss.get("modelErrorDirection"),
            "comparisonToTepcoAbsGapMw": (
                _round_number(abs_error - tepco_abs)
                if tepco_abs is not None
                else None
            ),
            "relatedFeatureCandidates": _feature_candidates_for_hour(hour),
            "analysisRole": (
                "forecast_accuracy_root_cause_candidate; cite this before "
                "generic lag or weather explanations"
            ),
        }))

    shape = operation.get("shape") or {}
    for rank, item in enumerate(shape.get("largeShapeBreaks") or [], start=1):
        if not isinstance(item, dict):
            continue
        delta_error = _as_float(item.get("modelDeltaErrorMw"))
        abs_delta_error = _as_float(item.get("modelAbsDeltaErrorMw"))
        score = abs_delta_error if abs_delta_error is not None else (
            abs(delta_error) if delta_error is not None else None
        )
        if score is None or score < PRIORITY_EVENT_LARGE_SHAPE_ERROR_MW:
            continue
        from_hour = _hour_from_point({"hour": item.get("fromHour")})
        to_hour = _hour_from_point({"hour": item.get("toHour")})
        anchor_hour = to_hour if to_hour is not None else from_hour
        time_band = _time_band_code_for_hour(anchor_hour)
        direction = None
        if delta_error is not None:
            direction = "model_rise_too_fast" if delta_error > 0 else "model_drop_too_fast"
        feature_candidates = _feature_candidates_for_hour(anchor_hour)
        if direction == "model_drop_too_fast":
            feature_candidates.extend([
                "intraday_correction.negative_residual_continuity_floor",
                "serving.published_forecast_freeze",
            ])
        elif direction == "model_rise_too_fast":
            feature_candidates.extend([
                "intraday_correction.positive_residual_slope_damping",
                "intraday_correction.evening_decline_continuity_guard",
            ])
        events.append(_drop_none_values({
            "id": f"shape_break_{from_hour}_{to_hour}",
            "eventType": "shape_break",
            "rank": rank,
            "priorityScoreMw": _round_number(score),
            "severity": _priority_event_severity(score),
            "fromHour": from_hour,
            "toHour": to_hour,
            "timeBand": time_band,
            "timeBandLabel": _time_band_label(operation, time_band),
            "actualDeltaMw": _round_number(item.get("actualDeltaMw")),
            "modelDeltaMw": _round_number(item.get("modelDeltaMw")),
            "tepcoDeltaMw": _round_number(item.get("tepcoDeltaMw")),
            "modelDeltaErrorMw": _round_number(delta_error),
            "modelAbsDeltaErrorMw": _round_number(score),
            "shapeDirection": direction,
            "relatedFeatureCandidates": list(dict.fromkeys(feature_candidates)),
            "analysisRole": (
                "shape_risk_root_cause_candidate; explain curve dynamics, "
                "not only point MAE"
            ),
        }))

    for rank, band in enumerate(_annotate_time_bands(operation.get("timeBands")), start=1):
        if not isinstance(band, dict):
            continue
        model_mae = _as_float(band.get("modelMaeMw"))
        tepco_mae = _as_float(band.get("tepcoMaeMw"))
        if model_mae is None or tepco_mae is None:
            continue
        gap = model_mae - tepco_mae
        if gap < PRIORITY_EVENT_BAND_GAP_MW:
            continue
        events.append(_drop_none_values({
            "id": f"band_gap_{band.get('code') or rank}",
            "eventType": "time_band_underperformance",
            "rank": rank,
            "priorityScoreMw": _round_number(gap),
            "severity": _priority_event_severity(gap),
            "timeBand": band.get("code"),
            "timeBandLabel": band.get("label"),
            "modelMaeMw": _round_number(model_mae),
            "tepcoMaeMw": _round_number(tepco_mae),
            "maeGapMw": _round_number(gap),
            "modelBiasMw": _round_number(band.get("modelBiasMw")),
            "modelBiasDirection": band.get("modelBiasDirection"),
            "relatedFeatureCandidates": [
                "lag_24h",
                "recent_same_business_type_mean",
                "temp_delta_1h",
                "intraday_correction.positive_residual_slope_damping",
            ],
            "analysisRole": (
                "band_level_context; combine with topMisses or shapeBreaks "
                "before making a root-cause claim"
            ),
        }))

    freeze_impact = (diagnostic_context or {}).get("freezeImpact") or {}
    for rank, gap in enumerate(freeze_impact.get("largestGaps") or [], start=1):
        freeze_gap = _as_float(gap.get("freezeGapMw"))
        if freeze_gap is None:
            continue
        score = abs(freeze_gap)
        if score < FREEZE_GAP_THRESHOLD_MW:
            continue
        hour = _hour_from_point(gap)
        events.append(_drop_none_values({
            "id": f"freeze_gap_h{hour}",
            "eventType": "published_recalculated_gap",
            "rank": rank,
            "priorityScoreMw": _round_number(score),
            "severity": _priority_event_severity(score),
            "hour": hour,
            "timeBand": _time_band_code_for_hour(hour),
            "publishedForecastMw": _round_number(gap.get("publishedForecastMw")),
            "latestRecalculatedForecastMw": _round_number(
                gap.get("latestRecalculatedForecastMw")
            ),
            "freezeGapMw": _round_number(freeze_gap),
            "relatedFeatureCandidates": ["serving.published_forecast_freeze"],
            "analysisRole": (
                "serving_shape_risk_candidate; distinguish UI serving line "
                "from raw model accuracy"
            ),
        }))

    if not events:
        return None

    events = sorted(
        events,
        key=lambda item: (
            float(item.get("priorityScoreMw") or 0.0),
            1 if item.get("eventType") == "large_absolute_error" else 0,
        ),
        reverse=True,
    )[:PRIORITY_EVENT_MAX_ITEMS]
    return {
        "selectionRule": (
            "Generic, data-derived ranking of large point errors, shape breaks, "
            "time-band underperformance, and published-vs-recalculated gaps. "
            "These are evidence priorities, not prewritten conclusions."
        ),
        "mustDiscussEventIds": [event.get("id") for event in events[:3] if event.get("id")],
        "events": events,
        "recommendationRule": (
            "Recommendations should target one relatedFeatureCandidates value "
            "from a discussed event and describe a replay/backtest experiment."
        ),
        "dailyVerdict": _drop_none_values({
            "verdict": summary.get("verdict"),
            "modelMaeMw": _round_number(summary.get("modelMaeMw")),
            "tepcoMaeMw": _round_number(summary.get("tepcoMaeMw")),
            "modelWapePct": _round_number(summary.get("modelWapePct"), digits=3),
            "tepcoWapePct": _round_number(summary.get("tepcoWapePct"), digits=3),
            "modelAdvantageHours": summary.get("modelAdvantageHours"),
            "tepcoAdvantageHours": summary.get("tepcoAdvantageHours"),
        }),
    }


STAGE_ORDER = [
    "raw_lgbm",
    "analog_adjusted",
    "post_holiday_guarded",
    "midday_guarded",
    "pre_calibration",
    "post_calibration",
    "published",
]


def _stage_label(stage: str) -> str:
    return stage.replace("_", " ")


def _stage_value_from_row(
    stage: str,
    row: dict,
    published_forecast_mw: float | None,
) -> float | None:
    stage_values = row.get("forecastMwByStage") or {}
    if stage in stage_values:
        return _round_number(stage_values.get(stage))
    if stage == "pre_calibration":
        return _round_number(row.get("preCalibrationForecastMw"))
    if stage == "post_calibration":
        return _round_number(row.get("postCalibrationForecastMw"))
    if stage == "published":
        return published_forecast_mw
    return None


def _stage_impact_summary(
    row: dict,
    published_forecast_mw: float | None,
) -> list[dict]:
    summary = []
    previous_stage = None
    previous_value = None
    for stage in STAGE_ORDER:
        value = _stage_value_from_row(stage, row, published_forecast_mw)
        if value is None:
            continue
        delta = 0.0 if previous_value is None else round(value - previous_value, 1)
        summary.append(_drop_none_values({
            "stage": stage,
            "label": _stage_label(stage),
            "value_mw": value,
            "delta_mw": delta,
            "delta_from": previous_stage,
        }))
        previous_stage = stage
        previous_value = value
    return summary


def _largest_stage_delta(stage_summary: list[dict]) -> dict | None:
    candidates = [
        item
        for item in stage_summary
        if item.get("delta_from") is not None and item.get("delta_mw") is not None
    ]
    if not candidates:
        return None
    item = max(candidates, key=lambda value: abs(float(value.get("delta_mw") or 0.0)))
    return {
        "stage": item.get("stage"),
        "delta_mw": item.get("delta_mw"),
        "delta_from": item.get("delta_from"),
    }


def _build_stage_attribution(
    forecast: dict | None,
    calibration: dict | None,
) -> dict | None:
    if not isinstance(calibration, dict):
        return None
    forecast_by_hour = _series_by_hour(forecast)
    rows = []
    for row in calibration.get("hourlyDiagnostics") or []:
        hour = _hour_from_point(row)
        if hour is None:
            continue
        published = _round_number((forecast_by_hour.get(hour) or {}).get("forecastMw"))
        stage_summary = _stage_impact_summary(row, published)
        if len(stage_summary) < 2:
            continue
        first_value = _as_float(stage_summary[0].get("value_mw"))
        final_value = _as_float(stage_summary[-1].get("value_mw"))
        post_calibration = _round_number(row.get("postCalibrationForecastMw"))
        latest_recalculated = post_calibration
        if latest_recalculated is None:
            latest_recalculated = _round_number(row.get("preCalibrationForecastMw"))
        freeze_gap = (
            round(published - latest_recalculated, 1)
            if published is not None and latest_recalculated is not None
            else None
        )
        largest_delta = _largest_stage_delta(stage_summary)
        rows.append(_drop_none_values({
            "hour": hour,
            "ts": row.get("ts") or (forecast_by_hour.get(hour) or {}).get("ts"),
            "actualMw": _round_number(row.get("actualMw")),
            "actualSource": row.get("actualSource"),
            "tepcoForecastMw": _round_number(row.get("tepcoForecastMw")),
            "stageImpactSummary": stage_summary,
            "netStageShiftMw": (
                round(final_value - first_value, 1)
                if first_value is not None and final_value is not None
                else None
            ),
            "largestStageDelta": largest_delta,
            "publishedVsLatestRecalculatedGapMw": freeze_gap,
        }))

    if not rows:
        return None

    def priority(item: dict) -> tuple[float, float]:
        net_shift = abs(float(item.get("netStageShiftMw") or 0.0))
        freeze_gap = abs(float(item.get("publishedVsLatestRecalculatedGapMw") or 0.0))
        largest = item.get("largestStageDelta") or {}
        stage_delta = abs(float(largest.get("delta_mw") or 0.0))
        return (max(net_shift, stage_delta, freeze_gap), freeze_gap)

    selected = sorted(rows, key=priority, reverse=True)[:5]
    selected = sorted(selected, key=lambda item: int(item.get("hour", 99)))
    top_stage_counts: dict[str, int] = {}
    for item in rows:
        largest = item.get("largestStageDelta") or {}
        stage = largest.get("stage")
        if isinstance(stage, str):
            top_stage_counts[stage] = top_stage_counts.get(stage, 0) + 1
    top_driver = None
    if top_stage_counts:
        top_driver = max(top_stage_counts.items(), key=lambda pair: pair[1])[0]
    return _drop_none_values({
        "source": "operationalCalibration.hourlyDiagnostics.forecastMwByStage",
        "stageOrder": STAGE_ORDER,
        "largestStageShifts": selected,
        "topDriver": top_driver,
    })


def _latest_observed_calibration_row(calibration: dict | None) -> dict | None:
    if not isinstance(calibration, dict):
        return None
    rows = [
        row
        for row in calibration.get("hourlyDiagnostics") or []
        if _hour_from_point(row) is not None
        and row.get("actualMw") is not None
    ]
    if not rows:
        return None
    return max(rows, key=lambda row: int(_hour_from_point(row) or -1))


def _recent_residuals(calibration: dict | None, max_items: int = 6) -> list[float]:
    if not isinstance(calibration, dict):
        return []
    rows = sorted(
        [
            row
            for row in calibration.get("hourlyDiagnostics") or []
            if _hour_from_point(row) is not None
        ],
        key=lambda row: int(_hour_from_point(row) or -1),
    )
    residuals = []
    for row in rows:
        residual = _as_float(row.get("actualVsPreCalibrationResidualMw"))
        if residual is None:
            residual = _as_float(row.get("actualVsPostCalibrationResidualMw"))
        if residual is not None:
            residuals.append(residual)
    return residuals[-max_items:]


def _same_direction_tail_count(values: list[float]) -> int:
    if not values:
        return 0
    latest = values[-1]
    if latest == 0:
        return 0
    direction = 1 if latest > 0 else -1
    count = 0
    for value in reversed(values):
        if value == 0 or (1 if value > 0 else -1) != direction:
            break
        count += 1
    return count


def _build_controller_diagnosis(
    calibration: dict | None,
    freeze_impact: dict | None,
) -> dict | None:
    if not isinstance(calibration, dict):
        return None
    correction = calibration.get("correction") or {}
    if not correction:
        return None
    base_adjustment = _round_number(correction.get("baseAdjustmentMw"))
    carryover_adjustment = _round_number(correction.get("carryoverAdjustmentMw"))
    cap_hit = (
        abs(float(base_adjustment)) >= DEFAULT_INTRADAY_MAX_ABS_ADJUSTMENT_MW - 0.5
        if base_adjustment is not None
        else False
    )
    latest_row = _latest_observed_calibration_row(calibration)
    latest_actual_slope = _round_number(
        (latest_row or {}).get("sameDayActualSlopeMw")
    )
    latest_model_slope = _round_number(
        (latest_row or {}).get("postCalibrationForecastDeltaMw")
        if (latest_row or {}).get("postCalibrationForecastDeltaMw") is not None
        else (latest_row or {}).get("forecastDeltaMw")
    )
    latest_post_residual = _round_number(
        (latest_row or {}).get("actualVsPostCalibrationResidualMw")
    )
    recent_residuals = _recent_residuals(calibration)
    recent_mean = (
        round(sum(recent_residuals) / len(recent_residuals), 1)
        if recent_residuals
        else None
    )
    mismatched_gradient = False
    if base_adjustment is not None and latest_actual_slope is not None:
        mismatched_gradient = (
            base_adjustment > 0 and latest_actual_slope < -SLOPE_MISMATCH_THRESHOLD_MW
        ) or (
            base_adjustment < 0 and latest_actual_slope > SLOPE_MISMATCH_THRESHOLD_MW
        )
    residual_direction = None
    if base_adjustment is not None:
        residual_direction = (
            "upward" if base_adjustment > 0 else "downward" if base_adjustment < 0 else "neutral"
        )
    flags = []
    if cap_hit:
        flags.append("capHit")
    if mismatched_gradient:
        flags.append("mismatchedGradient")
    if latest_post_residual is not None and latest_post_residual <= -LARGE_RESIDUAL_MW:
        flags.append("modelStillAboveActualTrend")
    if latest_post_residual is not None and latest_post_residual >= LARGE_RESIDUAL_MW:
        flags.append("modelStillBelowActualTrend")
    if freeze_impact:
        flags.append("freezeLikelyVisibleInUi")
    if correction.get("positiveResidualSlopeDampingApplied"):
        flags.append("positiveResidualSlopeDampingApplied")
    if correction.get("eveningDeclineContinuityGuardApplied"):
        flags.append("eveningDeclineContinuityGuardApplied")
    if correction.get("morningRampContinuityGuardApplied"):
        flags.append("morningRampContinuityGuardApplied")
    if correction.get("negativeResidualContinuityFloorApplied"):
        flags.append("negativeResidualContinuityFloorApplied")
    if correction.get("negativeResidualNearTermFloorApplied"):
        flags.append("negativeResidualNearTermFloorApplied")

    return _drop_none_values({
        "source": "operationalCalibration.correction",
        "applied": correction.get("applied"),
        "baseAdjustmentMw": base_adjustment,
        "carryoverAdjustmentMw": carryover_adjustment,
        "maxAbsAdjustmentMw": DEFAULT_INTRADAY_MAX_ABS_ADJUSTMENT_MW,
        "capHitLikely": cap_hit,
        "direction": residual_direction,
        "lastObservedHour": correction.get("lastObservedHour"),
        "residualTrend": _drop_none_values({
            "latestResidualMw": latest_post_residual,
            "recentMeanResidualMw": recent_mean,
            "sameDirectionHours": _same_direction_tail_count(recent_residuals),
        }),
        "slopeContext": _drop_none_values({
            "latestActualSlopeMw": latest_actual_slope,
            "latestModelSlopeMw": latest_model_slope,
            "mismatchedGradient": mismatched_gradient,
        }),
        "guardSummary": _drop_none_values({
            "positiveResidualSlopeDampingApplied": correction.get("positiveResidualSlopeDampingApplied"),
            "positiveResidualSlopeDampingFactor": _round_number(
                correction.get("positiveResidualSlopeDampingFactor"),
                digits=3,
            ),
            "positiveResidualSlopeDampingMaxMw": _round_number(
                correction.get("positiveResidualSlopeDampingMaxMw")
            ),
            "morningRampContinuityGuardApplied": correction.get("morningRampContinuityGuardApplied"),
            "morningRampContinuityMaxRestoreMw": _round_number(
                correction.get("morningRampContinuityMaxRestoreMw")
            ),
            "negativeResidualContinuityFloorApplied": correction.get(
                "negativeResidualContinuityFloorApplied"
            ),
            "negativeResidualContinuityFloorMaxRestoreMw": _round_number(
                correction.get("negativeResidualContinuityFloorMaxRestoreMw")
            ),
            "negativeResidualNearTermFloorApplied": correction.get(
                "negativeResidualNearTermFloorApplied"
            ),
            "negativeResidualNearTermFloorMaxRestoreMw": _round_number(
                correction.get("negativeResidualNearTermFloorMaxRestoreMw")
            ),
            "eveningDeclineContinuityGuardApplied": correction.get("eveningDeclineContinuityGuardApplied"),
            "eveningDeclineContinuityMaxReductionMw": _round_number(
                correction.get("eveningDeclineContinuityMaxReductionMw")
            ),
        }),
        "flags": flags,
    })


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    middle = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[middle]
    return (sorted_values[middle - 1] + sorted_values[middle]) / 2.0


def _build_band_quality(actual: dict | None, forecast: dict | None) -> dict | None:
    actual_by_hour = _series_by_hour(actual)
    forecast_by_hour = _series_by_hour(forecast)
    rows = []
    p95_half_widths = []
    p99_half_widths = []
    outside_p95 = []
    outside_p99 = []
    q50_large_miss_covered = []
    for hour in sorted(set(actual_by_hour) & set(forecast_by_hour)):
        actual_mw = _as_float(actual_by_hour[hour].get("actualMw"))
        forecast_mw = _as_float(forecast_by_hour[hour].get("forecastMw"))
        if actual_mw is None or forecast_mw is None:
            continue
        p95_lower = _as_float(forecast_by_hour[hour].get("p95LowerMw"))
        p95_upper = _as_float(forecast_by_hour[hour].get("p95UpperMw"))
        p99_lower = _as_float(forecast_by_hour[hour].get("p99LowerMw"))
        p99_upper = _as_float(forecast_by_hour[hour].get("p99UpperMw"))
        abs_error = abs(forecast_mw - actual_mw)
        p95_covered = None
        p99_covered = None
        if p95_lower is not None and p95_upper is not None:
            p95_covered = p95_lower <= actual_mw <= p95_upper
            p95_half_widths.append((p95_upper - p95_lower) / 2.0)
            if not p95_covered:
                outside_p95.append(hour)
        if p99_lower is not None and p99_upper is not None:
            p99_covered = p99_lower <= actual_mw <= p99_upper
            p99_half_widths.append((p99_upper - p99_lower) / 2.0)
            if not p99_covered:
                outside_p99.append(hour)
        if (
            abs_error >= LARGE_CONTROL_DELTA_MW
            and p95_covered is True
        ):
            q50_large_miss_covered.append(hour)
        rows.append(hour)

    if not rows:
        return None
    return _drop_none_values({
        "comparableHours": len(rows),
        "p95CoverageHours": len(rows) - len(outside_p95) if p95_half_widths else None,
        "p95CoverageRate": (
            round((len(rows) - len(outside_p95)) / len(rows), 3)
            if p95_half_widths
            else None
        ),
        "p99CoverageHours": len(rows) - len(outside_p99) if p99_half_widths else None,
        "p99CoverageRate": (
            round((len(rows) - len(outside_p99)) / len(rows), 3)
            if p99_half_widths
            else None
        ),
        "outsideP95Hours": outside_p95,
        "outsideP99Hours": outside_p99,
        "medianP95HalfWidthMw": _round_number(_median(p95_half_widths)),
        "medianP99HalfWidthMw": _round_number(_median(p99_half_widths)),
        "q50LargeMissCoveredByP95Hours": q50_large_miss_covered,
    })


def _load_recent_operation_reports(
    public_dir: Path,
    date_iso: str | None,
    lookback_days: int = ROLLING_PATTERN_LOOKBACK_DAYS,
) -> list[dict]:
    index = _load_json(public_dir / "reports" / "daily" / "index.json")
    if not isinstance(index, dict):
        return []
    refs = []
    for item in index.get("reports") or []:
        report_date = item.get("date")
        if not isinstance(report_date, str):
            continue
        if date_iso and report_date > date_iso:
            continue
        refs.append(report_date)
    refs = sorted(set(refs))[-lookback_days:]
    reports = []
    for report_date in refs:
        payload = _load_json(public_dir / "reports" / "daily" / f"{report_date}.json")
        if isinstance(payload, dict):
            reports.append(payload)
    return reports


def _band_direction(bias_mw: float | None) -> str | None:
    if bias_mw is None:
        return None
    if bias_mw >= ROLLING_PATTERN_MIN_MEAN_BIAS_MW:
        return "overprediction"
    if bias_mw <= -ROLLING_PATTERN_MIN_MEAN_BIAS_MW:
        return "underprediction"
    return "neutral"


def _build_rolling_pattern_context(
    public_dir: Path,
    date_iso: str | None,
) -> dict | None:
    reports = _load_recent_operation_reports(public_dir, date_iso)
    if not reports:
        return None

    band_stats: dict[str, dict] = {}
    for report in reports:
        report_date = report.get("date")
        for band in report.get("timeBands") or []:
            code = band.get("code") or band.get("label")
            if not isinstance(code, str):
                continue
            bias = _as_float(band.get("modelBiasMw"))
            mae = _as_float(band.get("modelMaeMw"))
            verdict = band.get("verdict")
            stats = band_stats.setdefault(code, {
                "band": code,
                "label": band.get("label"),
                "days": 0,
                "biases": [],
                "maes": [],
                "verdicts": {},
                "directionCounts": {
                    "overprediction": 0,
                    "underprediction": 0,
                    "neutral": 0,
                },
                "sampleDates": [],
            })
            stats["days"] += 1
            if isinstance(report_date, str):
                stats["sampleDates"].append(report_date)
            if bias is not None:
                stats["biases"].append(bias)
                direction = _band_direction(bias)
                if direction:
                    stats["directionCounts"][direction] += 1
            if mae is not None:
                stats["maes"].append(mae)
            if isinstance(verdict, str):
                stats["verdicts"][verdict] = stats["verdicts"].get(verdict, 0) + 1

    repeated = []
    summaries = []
    for stats in band_stats.values():
        biases = stats["biases"]
        maes = stats["maes"]
        mean_bias = round(sum(biases) / len(biases), 1) if biases else None
        mean_mae = round(sum(maes) / len(maes), 1) if maes else None
        dominant_direction = None
        direction_count = 0
        for direction, count in stats["directionCounts"].items():
            if direction == "neutral":
                continue
            if count > direction_count:
                dominant_direction = direction
                direction_count = count
        summary = _drop_none_values({
            "band": stats["band"],
            "label": stats.get("label"),
            "days": stats["days"],
            "meanModelBiasMw": mean_bias,
            "meanModelMaeMw": mean_mae,
            "dominantDirection": dominant_direction,
            "sameDirectionMissDays": direction_count,
            "verdictCounts": stats["verdicts"],
            "sampleDates": stats["sampleDates"][-3:],
        })
        summaries.append(summary)
        if (
            dominant_direction
            and direction_count >= ROLLING_PATTERN_MIN_DIRECTION_DAYS
            and mean_bias is not None
            and abs(mean_bias) >= ROLLING_PATTERN_MIN_MEAN_BIAS_MW
        ):
            repeated.append(summary)

    repeated = sorted(
        repeated,
        key=lambda item: (
            int(item.get("sameDirectionMissDays") or 0),
            abs(float(item.get("meanModelBiasMw") or 0.0)),
        ),
        reverse=True,
    )[:5]
    verdict = "no_repeated_band_bias"
    if repeated:
        first = repeated[0]
        verdict = f"{first.get('band')}_{first.get('dominantDirection')}_repeated"

    return _drop_none_values({
        "lookbackDays": len(reports),
        "targetDate": date_iso,
        "dateRange": _drop_none_values({
            "from": reports[0].get("date") if reports else None,
            "to": reports[-1].get("date") if reports else None,
        }),
        "bandSummaries": sorted(summaries, key=lambda item: str(item.get("band"))),
        "sameBandRepeatedMisses": repeated,
        "recentTrendVerdict": verdict,
    })


def _build_report_diagnostic_context(
    public_dir: Path,
    date_iso: str | None,
    data_quality: dict | None,
    calibration: dict | None,
    calibration_history: dict | None,
    actual: dict | None,
    forecast: dict | None,
) -> dict:
    calibration_facts = _compact_calibration(calibration)
    freeze_impact = _build_freeze_context(forecast, calibration)
    context = {
        "coverageContext": _build_coverage_context(data_quality, calibration_facts),
        "controllerDiagnosis": _build_controller_diagnosis(calibration, freeze_impact),
        "stageAttribution": _build_stage_attribution(forecast, calibration),
        "bandQuality": _build_band_quality(actual, forecast),
        "rollingPatternContext": _build_rolling_pattern_context(public_dir, date_iso),
        "freezeImpact": freeze_impact,
    }
    return {
        key: value
        for key, value in context.items()
        if value is not None and value != {} and value != []
    }


def _build_control_context(
    calibration: dict | None,
    calibration_history: dict | None,
) -> dict | None:
    if not isinstance(calibration, dict):
        return None
    correction = calibration.get("correction") or {}
    residual_items = _selected_residual_carryover_items(
        correction.get("residualCarryoverByHour") or [],
        max_items=6,
    )
    damped_items = [
        item
        for item in residual_items
        if (_as_float(item.get("positiveResidualSlopeDampingFactor")) or 1.0) < 0.999
    ]
    snapshots = (calibration_history or {}).get("snapshots") or []
    context = {
        "sourceConfidence": correction.get("sourceConfidence")
        or calibration.get("source_confidence"),
        "observedHours": correction.get("observedHours"),
        "lastObservedHour": correction.get("lastObservedHour"),
        "appliedRegimeReason": correction.get("appliedRegimeReason")
        or calibration.get("applied_regime_reason"),
        "residualCarryover": _drop_none_values({
            "baseAdjustmentMw": _round_number(correction.get("baseAdjustmentMw")),
            "carryoverAdjustmentMw": _round_number(correction.get("carryoverAdjustmentMw")),
            "affectedHours": [item.get("hour") for item in residual_items],
            "sample": residual_items,
        }),
        "positiveResidualSlopeDamping": _drop_none_values({
            "applied": correction.get("positiveResidualSlopeDampingApplied"),
            "factor": _round_number(
                correction.get("positiveResidualSlopeDampingFactor"),
                digits=3,
            ),
            "maxReducedMw": _round_number(
                correction.get("positiveResidualSlopeDampingMaxMw")
            ),
            "affectedHours": [item.get("hour") for item in damped_items],
            "sample": damped_items,
        }),
        "positiveResidualMitigation": _drop_none_values({
            "applied": correction.get("positiveResidualMitigationApplied"),
            "maxReducedMw": _round_number(
                correction.get("positiveResidualMitigationMaxMw")
            ),
        }),
        "negativeResidualRecoveryDamping": _drop_none_values({
            "applied": correction.get("negResidualRecoveryDampingApplied"),
            "factor": _round_number(
                correction.get("negResidualRecoveryDampingFactor"),
                digits=3,
            ),
        }),
        "negativeResidualContinuityFloor": _drop_none_values({
            "applied": correction.get("negativeResidualContinuityFloorApplied"),
            "maxRestoredMw": _round_number(
                correction.get("negativeResidualContinuityFloorMaxRestoreMw")
            ),
        }),
        "eveningDeclineContinuityGuard": _drop_none_values({
            "applied": correction.get("eveningDeclineContinuityGuardApplied"),
            "maxReducedMw": _round_number(
                correction.get("eveningDeclineContinuityMaxReductionMw")
            ),
        }),
        "businessTypeTransition": _drop_none_values({
            "priorApplied": correction.get("businessTypeTransitionPriorApplied"),
            "priorBiasMw": _round_number(
                correction.get("businessTypeTransitionPriorBiasMw")
            ),
            "observedApplied": correction.get("businessTypeTransitionApplied"),
            "observedBiasMw": _round_number(correction.get("businessTypeTransitionBiasMw")),
        }),
        "snapshotHistory": _drop_none_values({
            "snapshotCount": len(snapshots),
            "latestGeneratedAt": (snapshots[-1] or {}).get("generatedAt")
            if snapshots
            else None,
        }),
    }
    return {
        key: value
        for key, value in context.items()
        if value is not None and value != {} and value != []
    }


def _build_focused_rows(
    operation: dict | None,
    actual: dict | None,
    forecast: dict | None,
    calibration: dict | None,
) -> list[dict]:
    actual_by_hour = _series_by_hour(actual)
    forecast_by_hour = _series_by_hour(forecast)
    calibration_by_hour = _calibration_rows_by_hour(calibration)
    freeze_hours = {
        int(item["hour"])
        for item in _forecast_freeze_gaps(forecast, calibration)
        if item.get("hour") is not None
    }
    operation_hours = _focused_hours_from_operation(operation)
    calibration_hours = _focused_hours_from_calibration(calibration)
    freeze_window_hours = {
        neighbor
        for hour in freeze_hours
        for neighbor in _window_hours(hour, radius=1)
    }
    hours = operation_hours | calibration_hours | freeze_window_hours
    if not hours:
        return []

    def hour_priority(hour: int) -> tuple[int, int]:
        score = 0
        if hour in freeze_window_hours:
            score += 4
        if hour in calibration_hours:
            score += 3
        if hour in operation_hours:
            score += 2
        return (-score, hour)

    selected_hours = sorted(sorted(hours, key=hour_priority)[:MAX_FOCUSED_ROWS])

    miss_by_hour = {
        _hour_from_point(miss): miss
        for miss in ((operation or {}).get("topMisses") or [])
        if _hour_from_point(miss) is not None
    }
    rows = []
    for hour in selected_hours:
        actual_point = actual_by_hour.get(hour) or {}
        forecast_point = forecast_by_hour.get(hour) or {}
        calibration_row = calibration_by_hour.get(hour) or {}
        miss = miss_by_hour.get(hour) or {}
        actual_mw = _round_number(
            actual_point.get("actualMw")
            if actual_point.get("actualMw") is not None
            else calibration_row.get("actualMw")
            if calibration_row.get("actualMw") is not None
            else miss.get("actualMw")
        )
        published_forecast_mw = _round_number(
            forecast_point.get("forecastMw")
            if forecast_point
            else miss.get("modelForecastMw")
        )
        pre_calibration_mw = _round_number(
            calibration_row.get("preCalibrationForecastMw")
        )
        post_calibration_mw = _round_number(
            calibration_row.get("postCalibrationForecastMw")
        )
        tepco_forecast_mw = _round_number(
            actual_point.get("tepcoForecastMw")
            if actual_point.get("tepcoForecastMw") is not None
            else calibration_row.get("tepcoForecastMw")
            if calibration_row.get("tepcoForecastMw") is not None
            else miss.get("tepcoForecastMw")
        )
        row = _drop_none_values({
            "hour": hour,
            "ts": forecast_point.get("ts")
            or actual_point.get("ts")
            or calibration_row.get("ts"),
            "actualMw": actual_mw,
            "actualSource": actual_point.get("actualSource")
            or calibration_row.get("actualSource"),
            "publishedForecastMw": published_forecast_mw,
            "preCalibrationForecastMw": pre_calibration_mw,
            "postCalibrationForecastMw": post_calibration_mw,
            "calibrationDeltaMw": _round_number(calibration_row.get("calibrationDeltaMw")),
            "publishedVsLatestRecalculatedGapMw": (
                round(published_forecast_mw - post_calibration_mw, 1)
                if published_forecast_mw is not None and post_calibration_mw is not None
                else None
            ),
            "modelErrorMw": (
                round(published_forecast_mw - actual_mw, 1)
                if published_forecast_mw is not None and actual_mw is not None
                else _round_number(miss.get("modelErrorMw"))
            ),
            "modelAbsErrorMw": _round_number(miss.get("modelAbsErrorMw")),
            "tepcoForecastMw": tepco_forecast_mw,
            "tepcoErrorMw": (
                round(tepco_forecast_mw - actual_mw, 1)
                if tepco_forecast_mw is not None and actual_mw is not None
                else _round_number(miss.get("tepcoErrorMw"))
            ),
            "residualCarryover": _compact_residual_carryover_item(
                calibration_row.get("residualCarryover")
            ),
        })
        _annotate_error_direction(row, "modelErrorMw", "modelErrorDirection")
        _annotate_error_direction(row, "tepcoErrorMw", "tepcoErrorDirection")
        rows.append(row)
    return rows


def _build_openai_fact_packet(
    public_dir: Path,
    fallback_reports: dict[str, dict],
) -> dict:
    primary = fallback_reports.get("ko") or next(iter(fallback_reports.values()))
    operation = _load_ref_json(public_dir, primary, "operationReport")
    diagnostics = _load_ref_json(public_dir, primary, "internalDiagnostics")
    calibration = _load_ref_json(public_dir, primary, "operationalCalibration")
    calibration_history = _load_ref_json(public_dir, primary, "operationalCalibrationHistory")
    actual = _load_ref_json(public_dir, primary, "actual")
    forecast = _load_ref_json(public_dir, primary, "forecast")

    operation_facts = {}
    if operation:
        operation_facts = {
            "model": operation.get("model"),
            "peak": operation.get("peak"),
            "timeBands": _annotate_time_bands(operation.get("timeBands")),
            "shape": operation.get("shape"),
            "topMisses": _annotate_top_misses((operation.get("topMisses") or [])[:3]),
        }

    diagnostic_facts = None
    if diagnostics:
        diagnostic_facts = {
            "date": diagnostics.get("date"),
            "generatedAt": diagnostics.get("generatedAt"),
            "featureBuildError": diagnostics.get("featureBuildError"),
            "diagnosticSummary": diagnostics.get("diagnosticSummary"),
        }

    calibration_facts = _compact_calibration(calibration)
    diagnostic_context = primary.get("diagnosticContext")
    if not isinstance(diagnostic_context, dict):
        diagnostic_context = _build_report_diagnostic_context(
            public_dir,
            primary.get("date"),
            primary.get("dataQuality"),
            calibration,
            calibration_history,
            actual,
            forecast,
        )
    freeze_impact = diagnostic_context.get("freezeImpact")
    fact_packet = {
        "date": primary.get("date"),
        "timezone": TIMEZONE,
        "errorSignConvention": {
            "modelErrorMw": "modelForecastMw - actualMw",
            "tepcoErrorMw": "tepcoForecastMw - actualMw",
            "modelBiasMw": "mean(modelForecastMw - actualMw)",
            "positive": "overprediction_forecast_above_actual",
            "negative": "underprediction_forecast_below_actual",
            "zero": "no_directional_bias",
        },
        "inputSnapshot": primary.get("inputSnapshot"),
        "performance": primary.get("performance"),
        "dataQuality": primary.get("dataQuality"),
        "coverageContext": diagnostic_context.get("coverageContext"),
        "analysisPriorities": _build_analysis_priorities(
            operation,
            diagnostic_context,
        ),
        "operationFacts": operation_facts,
        "diagnosticFacts": diagnostic_facts,
        "morningTransitionDiagnostics": _compact_morning_transition_diagnostics(
            diagnostics
        ),
        "calibrationFacts": calibration_facts,
        "calibrationHistoryFacts": _compact_calibration_history(calibration_history),
        "focusedRows": _build_focused_rows(operation, actual, forecast, calibration),
        "controlContext": _build_control_context(calibration, calibration_history),
        "controllerDiagnosis": diagnostic_context.get("controllerDiagnosis"),
        "stageAttribution": diagnostic_context.get("stageAttribution"),
        "bandQuality": diagnostic_context.get("bandQuality"),
        "rollingPatternContext": diagnostic_context.get("rollingPatternContext"),
        "freezeImpact": freeze_impact,
        "freezeContext": freeze_impact,
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
            "proposedReplayCommand": {"type": ["string", "null"]},
            "commandStatus": {
                "type": ["string", "null"],
                "enum": [
                    "implemented",
                    "proposed_not_implemented",
                    "manual_validation",
                    None,
                ],
            },
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
            "proposedReplayCommand",
            "commandStatus",
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
        "Use only numeric facts, analysisPriorities, weather diagnostics, "
        "topMisses, timeBands, focusedRows, morningTransitionDiagnostics, "
        "controlContext, controllerDiagnosis, stageAttribution, "
        "bandQuality, freezeContext, rollingPatternContext, and calibration flags "
        "from factPacket. Treat focusedRows as the detailed window around "
        "large misses or calibration-shape risk, not as a full-day table. "
        "analysisPriorities is a generic evidence ranking produced by Python; "
        "it is not a prewritten conclusion. Unless contradicted by stronger "
        "evidence, address the top mustDiscussEventIds before generic lag or "
        "weather commentary, and cite the concrete hours and metrics from the "
        "matching event. "
        "Strict sign convention: modelErrorMw and modelBiasMw are forecast "
        "minus actual. Positive values mean overprediction or forecast above "
        "actual; negative values mean underprediction or forecast below actual. "
        "Never describe a positive modelErrorMw/modelBiasMw as underprediction, "
        "and never describe a negative value as overprediction. "
        "The percent error metric is WAPE, not MAPE. Never write MAPE or "
        "Mean Absolute Percentage Error; use WAPE or Weighted Absolute "
        "Percentage Error. "
        "If a timeBands item has modelBiasDirection=mixed, do not describe the "
        "entire band as underprediction or overprediction; describe it as a "
        "mixed-sign shape risk and cite the specific topMiss hours. "
        "When citing hour bands, always use unambiguous clock labels such as "
        "'hours 11:00-15:00 JST' or '11:00-15:00'. Do not write bare ranges "
        "like '11-15' or date-like phrases such as 'on 11-15'. "
        "The headline must state the operational result or risk, such as which "
        "model had lower daily error and the main affected hour band; never use "
        "generic headlines such as observations, status, or daily report. "
        "TEPCO is an external forecast/reference series, not this project's model; "
        "write TEPCO forecast, not TEPCO model. Avoid alarmist phrases such as "
        "significant operational risk unless reserve risk or alerts justify them; "
        "prefer forecast performance gap. "
        "When controllerDiagnosis, stageAttribution, or freezeImpact is present, "
        "at least one hypothesis or recommendation should use one of those fields "
        "unless the field is explicitly irrelevant. "
        "If freezeImpact.largestGaps or stageAttribution.largestStageShifts show "
        "a published-versus-recalculated gap above the threshold, include a "
        "serving.published_forecast_freeze hypothesis or counter-evidence item. "
        "If controllerDiagnosis.flags contains mismatchedGradient, explain the "
        "residual direction versus latest actual slope conflict instead of giving "
        "only a generic time-band bias. "
        "When analysisPriorities contains large_absolute_error and shape_break "
        "events, return at least one hypothesis that connects point accuracy "
        "and curve dynamics instead of discussing only a broad time band. "
        "When morningTransitionDiagnostics has causeTags, use those tags to "
        "separate raw morning transition risk, intraday carryover, humidity "
        "ramp, business-return, and freeze hypotheses instead of collapsing "
        "all 06-11 errors into a generic morning-ramp issue. "
        "When both topMisses and stage/freeze diagnostics exist, return at least "
        "two hypotheses: one for forecast accuracy and one for serving/calibration "
        "shape risk. "
        "Root-cause evidence should include concrete hours, topMisses, timeBands, "
        "controlContext, stageAttribution, or freezeImpact. Do not use daily MAE "
        "alone as root-cause evidence. "
        "Use freezeContext only when it records a published-versus-recalculated "
        "forecast gap; otherwise do not infer freeze effects. A negative "
        "freeze gap means the published line is below the latest recalculated "
        "line; do not describe that sign as actual-demand underprediction by "
        "itself. If morning_ramp hours 06-10 "
        "show large positive model bias and the data indicates a business-day "
        "to non-business-day transition, independently consider a lag_24h "
        "inertia or ramp contamination hypothesis. If observed demand slope "
        "recovers while residual trend remains worse or calibration facts show "
        "weak negative-residual damping, consider whether "
        "intraday_correction.negative_residual_recovery_damping thresholds or "
        "handoff timing need tuning; if direct evidence is absent, mark it "
        "not_observed with low confidence. Feature recommendations must name "
        "a concrete target from featureCatalog or "
        "analysisPriorities.relatedFeatureCandidates when possible and must propose "
        "a specific trigger, threshold, decay, shrinkage, or validation replay; "
        "Feature recommendations must link only to hypothesis IDs that are "
        "present in the output, and the recommendation target should match one "
        "of the linked hypothesis relatedFeatures when possible. "
        "write recommendations as experiment candidates, not production commands. "
        "Use wording like consider testing, backtest, evaluate, or make this a "
        "candidate; do not say to add, freeze, disable, or change production "
        "behavior directly unless the input includes explicit implemented evidence. "
        "include proposedReplayCommand only when it is clearly a real or proposed "
        "replay command. If there is no concrete command, set proposedReplayCommand "
        "and commandStatus to null. If a command is proposed but not implemented, "
        "set commandStatus to proposed_not_implemented rather than presenting it as real. "
        "Use rollingPatternContext to decide whether a miss pattern is repeated "
        "or a single-day anomaly; if it is not repeated, recommend further "
        "observation before changing guards. "
        "Use the unit spelling MW, not Mw. Avoid generic wording such as merely "
        "reviewing a feature. Never return "
        "sports-style wording such as win, lose, victory, defeat, or beat; use "
        "operations wording such as lower error, model advantage hours, TEPCO "
        "advantage hours, comparable performance, or underperformed. "
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
        "Use factPacket as the source of facts; it already contains summary "
        "metrics, key miss windows, focused rows around abnormal windows, "
        "analysisPriorities, morningTransitionDiagnostics, time-band statistics, "
        "calibration flags, control context, freeze-gap "
        "context, stage attribution, controller diagnosis, band-quality "
        "coverage, rolling pattern context, and snapshot summaries. "
        "Start from factPacket.analysisPriorities when selecting the two or "
        "three root-cause hypotheses; it ranks the day's large point errors, "
        "shape breaks, time-band gaps, and serving freeze gaps without writing "
        "the conclusion for you. "
        "Do not recompute deltas yourself: use stageAttribution stage "
        "value_mw/delta_mw pairs, controllerDiagnosis flags, and bandQuality "
        "coverage fields exactly as provided. "
        "Do not describe this as missing raw time-series data; instead, if a "
        "limitation is needed, say the analysis is based on summarized "
        "operational evidence and retained calibration snapshots. "
        "Strictly separate final daily actual coverage from intraday "
        "calibration coverage: factPacket.dataQuality and "
        "factPacket.coverageContext.finalActualCoverage describe the finalized "
        "daily CSV used for performance metrics, while calibrationFacts "
        "observedHours/missingHours describe only the retained intraday "
        "calibration snapshot before finalization. If finalActualCoverage has "
        "24 observed hours and 0 fallback actual hours, say final daily "
        "coverage is complete; never describe calibration missing hours as "
        "missing actual/performance coverage. "
        f"{_openai_domain_guidelines()} "
        "Use evidenceStatus conservatively: confirmed is only for direct input "
        "records such as a true calibration-layer Applied flag, retained "
        "snapshot-count/data-quality facts, or another explicitly observed "
        "machine-readable event. Numeric errors, biases, top misses, diagnostic "
        "patterns, or the absence of a calibration flag support only partial "
        "root-cause evidence. If the overwritten intraday timeline makes a "
        "claim unverifiable, use not_observed and confidence low. "
        "Use rollingPatternContext to distinguish repeated operating patterns "
        "from single-day anomalies. "
        "Every featureRecommendations item must set autoApply to false. "
        "FeatureRecommendations are experiment tickets, not direct production "
        "instructions. The suggestion should describe what to test or review, "
        "the expectedEffect should describe the desired metric movement, risk "
        "should describe the failure mode, and validationPlan should describe "
        "the replay or monitoring check. Avoid imperative wording that sounds "
        "like immediate deployment. "
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
        "do not invent metrics, hours, feature names, or calibration events. "
        "The factPacket contains summary metrics, key miss windows, focused "
        "rows around abnormal windows, analysisPriorities, morningTransitionDiagnostics, "
        "time-band statistics, calibration flags, "
        "control context, freeze-gap context, stage attribution, controller "
        "diagnosis, band-quality coverage, rolling pattern context, and snapshot summaries. Do not recompute "
        "deltas yourself: use stageAttribution stage value_mw/delta_mw pairs, "
        "controllerDiagnosis flags, and bandQuality coverage fields exactly as "
        "provided. Start from factPacket.analysisPriorities when selecting the "
        "two or three root-cause hypotheses; it ranks the day's large point "
        "errors, shape breaks, time-band gaps, and serving freeze gaps without "
        "writing the conclusion for you. When morningTransitionDiagnostics has "
        "causeTags, use those tags to separate raw morning transition risk, "
        "intraday carryover, humidity ramp, business-return, and freeze "
        "hypotheses. Do not describe "
        "this as missing raw time-series data; if a limitation is needed, say "
        "the analysis is based on summarized operational evidence and retained "
        "calibration snapshots. "
        "Strictly separate final daily actual coverage from intraday "
        "calibration coverage: factPacket.dataQuality and "
        "factPacket.coverageContext.finalActualCoverage describe the finalized "
        "daily CSV used for performance metrics, while calibrationFacts "
        "observedHours/missingHours describe only the retained intraday "
        "calibration snapshot before finalization. If finalActualCoverage has "
        "24 observed hours and 0 fallback actual hours, say final daily "
        "coverage is complete; never describe calibration missing hours as "
        "missing actual/performance coverage. "
        f"{_openai_domain_guidelines()} "
        "Keep deterministic metrics consistent with factPacket.performance. "
        "Use evidenceStatus conservatively: confirmed is only for direct input "
        "records such as a true calibration-layer Applied flag, retained "
        "snapshot-count/data-quality facts, or another explicitly observed "
        "machine-readable event. Numeric errors, biases, top misses, diagnostic "
        "patterns, or the absence of a calibration flag support only partial "
        "root-cause evidence. If the overwritten intraday timeline makes a "
        "claim unverifiable, use not_observed and confidence low. Use "
        "rollingPatternContext to distinguish repeated operating patterns from "
        "single-day anomalies. Return at most three hypotheses and "
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


def _log_openai_usage(label: str, model: str, data: dict) -> None:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    total_tokens = usage.get("total_tokens")
    print(
        "[OPENAI-USAGE] "
        f"{label} model={model} "
        f"input_tokens={input_tokens} "
        f"output_tokens={output_tokens} "
        f"total_tokens={total_tokens}"
    )


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
    _log_openai_usage("analysis", model, data)
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
    _log_openai_usage("multilingual", model, data)
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
        "Chinese-only text, and avoid sports-style words such as 승리/패배 when "
        "describing forecast comparison. For Korean hour ranges, translate "
        "'hours 11:00-15:00 JST' as '11~15시 구간' or an equivalent hour-band "
        "phrase, never as a calendar day range such as '11-15일'. "
        "For recommendations in Korean, phrase suggestions as experimental "
        "review candidates such as '... 조건을 백테스트 후보로 검토합니다' "
        "or '... 기준을 실험 후보로 둡니다', not as direct commands like "
        "'추가합니다' or '동결합니다'. "
        "Use this Korean terminology: "
        "'intraday execution' -> 'intraday 실행', 'residual damping' -> "
        "'잔차 감쇠', 'business type' -> '영업일 구분', 'positive bias' -> "
        "'양수 바이어스', and 'ramp window' -> '램프업 구간'. Never translate "
        "intraday as a word related to happiness. For ja, write natural modern Japanese; "
        "do not emit mojibake or pseudo-CJK text, and avoid 勝利/敗北 wording "
        "when describing forecast comparison. For Japanese hour ranges, translate "
        "'hours 11:00-15:00 JST' as '11〜15時台' or an equivalent hour-band "
        "phrase, never as a calendar day range such as '11-15日'. "
        "For recommendations in Japanese, phrase suggestions as experiment "
        "candidates such as '検証候補とします' or 'バックテスト対象にします', "
        "not as direct production commands. "
        "Use this Japanese terminology: "
        "'intraday execution' -> 'イントラデイ実行', 'residual damping' -> "
        "'残差ダンピング', and 'business type' -> '営業日/非営業日区分'."
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
    _log_openai_usage("localization", model, data)
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
        unit = item.get("unit")
        if isinstance(unit, str) and unit.lower() == "mw":
            unit = "MW"
        result.append({
            "source": str(source),
            "metric": str(metric),
            "value": item.get("value"),
            "unit": unit,
            "hour": item.get("hour"),
            "timeBand": item.get("timeBand"),
        })
    return result


def _evidence_supports_confirmed_status(evidence: list[dict]) -> bool:
    """Return true only when the evidence directly records an observed event.

    Root-cause hypotheses are intentionally conservative: a large error or bias
    can prove that a miss happened, but it should not by itself confirm why the
    miss happened.  Confirmed status is reserved for machine-readable event
    records, such as a calibration layer that explicitly applied.
    """
    for item in evidence:
        source = str(item.get("source") or "").lower()
        metric = str(item.get("metric") or "")
        value = item.get("value")
        source_is_calibration = (
            "operational-calibration" in source
            or "calibrationfacts" in source
            or "calibrationhistoryfacts" in source
        )
        if source_is_calibration:
            if metric.endswith("Applied") and value is True:
                return True
            if metric in {
                "snapshotCount",
                "appliedSnapshotCount",
                "calibrationSnapshotCount",
            }:
                return True
        if "dataquality" in source and metric in {
            "observedHours",
            "fallbackActualHours",
            "comparableHours",
        }:
            return True
    return False


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


_UNDERPREDICTION_WORDS = (
    "underprediction",
    "under-prediction",
    "underpredicted",
    "underestimated",
    "below actual",
    "below the actual",
    "lower than actual",
    "forecast below",
    "과소예측",
    "과소 예측",
    "과소평가",
    "과소 평가",
    "저평가",
    "실제보다 낮",
    "낮게 예측",
    "過小予測",
    "過小評価",
    "実績より低",
    "低く予測",
)
_OVERPREDICTION_WORDS = (
    "overprediction",
    "over-prediction",
    "overpredicted",
    "overestimated",
    "above actual",
    "above the actual",
    "higher than actual",
    "forecast above",
    "과대예측",
    "과대 예측",
    "과대평가",
    "과대 평가",
    "고평가",
    "실제보다 높",
    "높게 예측",
    "過大予測",
    "過大評価",
    "実績より高",
    "高く予測",
)
_SIGNED_ERROR_METRICS = {
    "modelerrormw",
    "modelbiasmw",
    "meanmodelbiasmw",
}
_DAILY_PERFORMANCE_METRICS = {
    "modelmaemw",
    "tepcomaemw",
    "modelwapepct",
    "tepcowapepct",
    "modelrmsemw",
    "tepcormsemw",
    "modelmaxerrormw",
    "tepcomaxerrormw",
    "maegapmw",
    "wapegappct",
}
_DIAGNOSTIC_ONLY_FEATURES = {
    "controllerDiagnosis",
    "stageAttribution",
    "freezeImpact",
    "freezeContext",
}
_ACCURACY_EVIDENCE_SOURCES = {
    "reports/daily",
    "operationreport",
    "reports/internal/daily-diagnostics",
    "daily-diagnostics",
}


def _hypothesis_has_sign_conflict(
    title: str,
    explanation: str,
    evidence: list[dict],
) -> bool:
    text = f"{title} {explanation}".lower()
    mentions_under = any(word in text for word in _UNDERPREDICTION_WORDS)
    mentions_over = any(word in text for word in _OVERPREDICTION_WORDS)
    if not mentions_under and not mentions_over:
        return False
    for item in evidence:
        metric = str(item.get("metric") or "").replace("_", "").lower()
        value_text = str(item.get("value") or "").lower()
        if metric in {"dominantdirection", "recenttrendverdict"}:
            if "overprediction" in value_text and mentions_under:
                return True
            if "underprediction" in value_text and mentions_over:
                return True
        if metric not in _SIGNED_ERROR_METRICS:
            continue
        value = _as_float(item.get("value"))
        if value is None or abs(value) < 100.0:
            continue
        if value > 0.0 and mentions_under:
            return True
        if value < 0.0 and mentions_over:
            return True
    return False


def _hypothesis_uses_only_daily_performance_evidence(evidence: list[dict]) -> bool:
    if not evidence:
        return False
    for item in evidence:
        source = str(item.get("source") or "").lower()
        metric = str(item.get("metric") or "").replace("_", "").lower()
        if source not in {"performance", "reports/daily"} or metric not in _DAILY_PERFORMANCE_METRICS:
            return False
        if item.get("hour") is not None:
            return False
    return True


def _hypothesis_uses_only_controller_diagnostics(evidence: list[dict]) -> bool:
    if not evidence:
        return False
    return all(
        str(item.get("source") or "").lower() == "controllerdiagnosis"
        for item in evidence
    )


def _hypothesis_is_freeze_only(hypothesis: dict) -> bool:
    features = set(_as_string_list(hypothesis.get("relatedFeatures")))
    if features:
        return features == {"serving.published_forecast_freeze"}
    evidence = hypothesis.get("evidence") or []
    if not evidence:
        return False
    return all(
        isinstance(item, dict)
        and str(item.get("source") or "").lower() in {"freezeimpact", "freezecontext"}
        for item in evidence
    )


def _hypothesis_has_concrete_non_freeze_evidence(hypothesis: dict) -> bool:
    if _hypothesis_is_freeze_only(hypothesis):
        return False
    if hypothesis.get("evidenceStatus") == "not_observed":
        return False
    evidence = _normalize_evidence(hypothesis.get("evidence"))
    if evidence and _hypothesis_uses_only_daily_performance_evidence(evidence):
        return False
    features = set(_as_string_list(hypothesis.get("relatedFeatures")))
    if any(
        feature not in _DIAGNOSTIC_ONLY_FEATURES
        and feature != "serving.published_forecast_freeze"
        for feature in features
    ):
        return True
    if not evidence:
        return False
    return any(
        str(item.get("source") or "").lower() in _ACCURACY_EVIDENCE_SOURCES
        for item in evidence
    )


def _normalize_feature_name(value: Any) -> str:
    text = str(value or "").strip()
    return FEATURE_NAME_ALIASES.get(text, text)


def _recommendation_targets_operational_feature(recommendation: dict) -> bool:
    target = str(recommendation.get("target") or "")
    return (
        bool(target)
        and target != "serving.published_forecast_freeze"
        and target not in _DIAGNOSTIC_ONLY_FEATURES
        and target in ALLOWED_RECOMMENDATION_TARGETS
    )


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
        evidence = _normalize_evidence(item.get("evidence"))
        if evidence_status != "not_observed" and not evidence:
            continue
        if _hypothesis_uses_only_daily_performance_evidence(evidence):
            continue
        if _hypothesis_uses_only_controller_diagnostics(evidence):
            continue
        if _hypothesis_has_sign_conflict(title, explanation, evidence):
            continue
        if (
            evidence_status == "confirmed"
            and not _evidence_supports_confirmed_status(evidence)
        ):
            evidence_status = "partial"
            if confidence == "high":
                confidence = "medium"
        result.append({
            "id": str(item.get("id") or f"h{index}"),
            "severity": severity,
            "confidence": confidence,
            "evidenceStatus": evidence_status,
            "title": title,
            "explanation": explanation,
            "evidence": evidence,
            "relatedHours": [
                int(hour) for hour in (item.get("relatedHours") or [])
                if isinstance(hour, int)
            ],
            "relatedTimeBands": _as_string_list(item.get("relatedTimeBands")),
            "relatedFeatures": [
                _normalize_feature_name(feature)
                for feature in _as_string_list(item.get("relatedFeatures"))
            ],
            "counterEvidence": _as_string_list(item.get("counterEvidence")),
        })
    return result or fallback


def _normalize_recommendations(
    value: Any,
    fallback: list[dict],
    hypotheses_by_id: dict[str, dict] | None = None,
) -> list[dict]:
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
        target = _normalize_feature_name(_meaningful_text(item.get("target")))
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
        linked_hypotheses = _as_string_list(item.get("linkedHypotheses"))
        linked_features: list[str] = []
        if hypotheses_by_id is not None:
            linked_hypotheses = [
                hypothesis_id
                for hypothesis_id in linked_hypotheses
                if hypothesis_id in hypotheses_by_id
            ]
            if _as_string_list(item.get("linkedHypotheses")) and not linked_hypotheses:
                continue
            for hypothesis_id in linked_hypotheses:
                for feature in _as_string_list(
                    hypotheses_by_id.get(hypothesis_id, {}).get("relatedFeatures")
                ):
                    if feature not in linked_features:
                        linked_features.append(feature)
            operational_linked_features = [
                feature for feature in linked_features
                if feature not in _DIAGNOSTIC_ONLY_FEATURES
            ]
            operational_linked_features = [
                _normalize_feature_name(feature)
                for feature in operational_linked_features
            ]
            if operational_linked_features and target not in operational_linked_features:
                target = operational_linked_features[0]
        if target not in ALLOWED_RECOMMENDATION_TARGETS:
            continue
        proposed_replay_command = _meaningful_text(item.get("proposedReplayCommand"))
        command_status = (
            item.get("commandStatus")
            if proposed_replay_command
            and item.get("commandStatus") in {
                "implemented",
                "proposed_not_implemented",
                "manual_validation",
            }
            else None
        )
        recommendation = {
            "id": str(item.get("id") or f"r{index}"),
            "priority": priority,
            "type": rec_type,
            "target": target,
            "suggestion": suggestion,
            "expectedEffect": expected_effect,
            "risk": risk,
            "validationPlan": validation_plan,
            "proposedReplayCommand": proposed_replay_command or None,
            "commandStatus": command_status,
            "linkedHypotheses": linked_hypotheses,
            "autoApply": False,
        }
        result.append({
            key: val
            for key, val in recommendation.items()
            if val is not None
        })
    return result or fallback


def _hypotheses_by_id(hypotheses: Any) -> dict[str, dict]:
    if not isinstance(hypotheses, list):
        return {}
    return {
        str(item.get("id")): item
        for item in hypotheses
        if isinstance(item, dict) and item.get("id")
    }


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
    fallback_hypotheses = list(report.get("rootCauseHypotheses") or [])
    normalized_hypotheses = _normalize_hypotheses(
        analysis.get("rootCauseHypotheses"),
        fallback_hypotheses,
    )
    normalized_hypotheses = [
        hypothesis
        for hypothesis in normalized_hypotheses
        if not (
            isinstance(hypothesis, dict)
            and (
                _hypothesis_uses_only_daily_performance_evidence(
                    _normalize_evidence(hypothesis.get("evidence"))
                )
                or _hypothesis_uses_only_controller_diagnostics(
                    _normalize_evidence(hypothesis.get("evidence"))
                )
            )
        )
    ]
    if normalized_hypotheses and all(
        _hypothesis_is_freeze_only(hypothesis)
        for hypothesis in normalized_hypotheses
        if isinstance(hypothesis, dict)
    ):
        existing_ids = {
            str(hypothesis.get("id"))
            for hypothesis in normalized_hypotheses
            if isinstance(hypothesis, dict)
        }
        for fallback_hypothesis in fallback_hypotheses:
            if not isinstance(fallback_hypothesis, dict):
                continue
            if _hypothesis_is_freeze_only(fallback_hypothesis):
                continue
            if not _hypothesis_has_concrete_non_freeze_evidence(fallback_hypothesis):
                continue
            if str(fallback_hypothesis.get("id")) in existing_ids:
                continue
            normalized_hypotheses.insert(0, fallback_hypothesis)
            break
    if not any(
        isinstance(hypothesis, dict)
        and _hypothesis_has_concrete_non_freeze_evidence(hypothesis)
        for hypothesis in normalized_hypotheses
    ):
        existing_ids = {
            str(hypothesis.get("id"))
            for hypothesis in normalized_hypotheses
            if isinstance(hypothesis, dict)
        }
        for fallback_hypothesis in fallback_hypotheses:
            if not isinstance(fallback_hypothesis, dict):
                continue
            if str(fallback_hypothesis.get("id")) in existing_ids:
                continue
            if not _hypothesis_has_concrete_non_freeze_evidence(fallback_hypothesis):
                continue
            normalized_hypotheses.insert(0, fallback_hypothesis)
            break
    if not any(
        isinstance(hypothesis, dict) and _hypothesis_is_freeze_only(hypothesis)
        for hypothesis in normalized_hypotheses
    ):
        freeze_hypothesis = _deterministic_freeze_hypothesis(report)
        if freeze_hypothesis is not None:
            normalized_hypotheses.append(freeze_hypothesis)
    unique_hypotheses = []
    freeze_seen = False
    for hypothesis in normalized_hypotheses:
        if not isinstance(hypothesis, dict):
            continue
        if _hypothesis_is_freeze_only(hypothesis):
            if freeze_seen:
                continue
            freeze_seen = True
            deterministic_freeze = _deterministic_freeze_hypothesis(report)
            if deterministic_freeze is not None:
                hypothesis = deterministic_freeze
        unique_hypotheses.append(hypothesis)
    normalized_hypotheses = unique_hypotheses[:3]
    report["rootCauseHypotheses"] = normalized_hypotheses
    messages = MESSAGES.get(report.get("language"), MESSAGES["ko"])
    report["featureRecommendations"] = _normalize_recommendations(
        analysis.get("featureRecommendations"),
        _recommendations(report["rootCauseHypotheses"], messages),
        _hypotheses_by_id(report["rootCauseHypotheses"]),
    )
    if not any(
        isinstance(recommendation, dict)
        and _recommendation_targets_operational_feature(recommendation)
        for recommendation in report["featureRecommendations"]
    ):
        existing_rec_ids = {
            str(recommendation.get("id"))
            for recommendation in report["featureRecommendations"]
            if isinstance(recommendation, dict)
        }
        recommendation_seed_hypotheses = [
            hypothesis for hypothesis in fallback_hypotheses
            if isinstance(hypothesis, dict)
            and _hypothesis_has_concrete_non_freeze_evidence(hypothesis)
        ] + [
            hypothesis for hypothesis in report["rootCauseHypotheses"]
            if isinstance(hypothesis, dict)
        ]
        for fallback_recommendation in _recommendations(
            recommendation_seed_hypotheses,
            messages,
        ):
            if not isinstance(fallback_recommendation, dict):
                continue
            if str(fallback_recommendation.get("id")) in existing_rec_ids:
                continue
            if not _recommendation_targets_operational_feature(fallback_recommendation):
                continue
            report["featureRecommendations"].append(fallback_recommendation)
            break
    if any(
        isinstance(hypothesis, dict) and _hypothesis_is_freeze_only(hypothesis)
        for hypothesis in report["rootCauseHypotheses"]
    ) and not any(
        isinstance(recommendation, dict)
        and recommendation.get("target") == "serving.published_forecast_freeze"
        for recommendation in report["featureRecommendations"]
    ):
        freeze_seed = [
            hypothesis for hypothesis in report["rootCauseHypotheses"]
            if isinstance(hypothesis, dict) and _hypothesis_is_freeze_only(hypothesis)
        ]
        for fallback_recommendation in _recommendations(freeze_seed, messages):
            if fallback_recommendation.get("target") == "serving.published_forecast_freeze":
                report["featureRecommendations"].append(fallback_recommendation)
                break
    unique_recommendations = []
    seen_targets = set()
    for recommendation in report["featureRecommendations"]:
        if not isinstance(recommendation, dict):
            continue
        target = recommendation.get("target")
        if target != "serving.published_forecast_freeze" and target not in ALLOWED_RECOMMENDATION_TARGETS:
            continue
        if target in seen_targets:
            continue
        seen_targets.add(target)
        unique_recommendations.append(recommendation)
    if not any(
        _recommendation_targets_operational_feature(recommendation)
        for recommendation in unique_recommendations
    ):
        seed = [
            hypothesis for hypothesis in fallback_hypotheses
            if isinstance(hypothesis, dict)
            and _hypothesis_has_concrete_non_freeze_evidence(hypothesis)
        ]
        for fallback_recommendation in _recommendations(seed, messages):
            target = fallback_recommendation.get("target")
            if target in seen_targets:
                continue
            if not _recommendation_targets_operational_feature(fallback_recommendation):
                continue
            seen_targets.add(target)
            unique_recommendations.append(fallback_recommendation)
            break
    report["featureRecommendations"] = unique_recommendations[:3]
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
    return _polish_report_language(report)


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


def _polish_localized_text(language: str, value: Any) -> Any:
    if isinstance(value, str):
        result = value
        for old, new in METRIC_TERM_REPLACEMENTS:
            result = result.replace(old, new)
        for old, new in GENERAL_TEXT_REPLACEMENTS:
            result = result.replace(old, new)
        for old, new in LOCALIZED_TEXT_REPLACEMENTS.get(language, []):
            result = result.replace(old, new)
        if language == "ko":
            for old, new in (
                ("11-15일", "11~15시 구간"),
                ("11~15일", "11~15시 구간"),
                ("11-18일", "11~18시 구간"),
                ("11~18일", "11~18시 구간"),
                ("15-17일", "15~17시 구간"),
                ("15~17일", "15~17시 구간"),
            ):
                result = result.replace(old, new)
        elif language == "ja":
            for old, new in (
                ("11-15日", "11〜15時台"),
                ("11〜15日", "11〜15時台"),
                ("11-18日", "11〜18時台"),
                ("11〜18日", "11〜18時台"),
                ("15-17日", "15〜17時台"),
                ("15〜17日", "15〜17時台"),
            ):
                result = result.replace(old, new)
        return result
    if isinstance(value, list):
        return [_polish_localized_text(language, item) for item in value]
    if isinstance(value, dict):
        return {
            key: _polish_localized_text(language, item)
            for key, item in value.items()
        }
    return value


def _looks_like_calibration_coverage_confusion(note: str) -> bool:
    lowered = note.lower()
    has_calibration = any(
        token in lowered
        for token in ("calibration", "보정", "キャリブレーション", "補正")
    )
    has_missing = any(
        token in lowered
        for token in ("missing", "누락", "欠落", "不足")
    )
    has_observed = any(
        token in lowered
        for token in ("observed", "관찰", "관측", "観察", "実測")
    )
    has_coverage = any(
        token in lowered
        for token in ("coverage", "커버리지", "カバレッジ")
    )
    return has_calibration and has_missing and has_observed and has_coverage


def _final_actual_coverage_is_complete(report: dict) -> bool:
    data_quality = report.get("dataQuality") or {}
    return (
        data_quality.get("observedHours") == 24
        and data_quality.get("fallbackActualHours") == 0
    )


def _final_coverage_note(language: str) -> str:
    if language == "en":
        return (
            "Performance metrics use the finalized 24-hour actual CSV; "
            "intraday calibration snapshots are referenced only as pre-final "
            "operational history."
        )
    if language == "ja":
        return (
            "性能評価は確定CSVの24時間実測値を基準にしており、intraday補正スナップショットは"
            "確定前の運用履歴としてのみ参照しています。"
        )
    return (
        "성능 평가는 확정 CSV의 24시간 실측을 기준으로 했고, intraday 보정 스냅샷은 "
        "확정 전 운영 이력으로만 참고했습니다."
    )


def _clarify_operator_notes_coverage(report: dict) -> dict:
    if not _final_actual_coverage_is_complete(report):
        return report
    notes = _as_string_list(report.get("operatorNotes"))
    if not notes:
        return report

    language = str(report.get("language") or "ko")
    replacement = _final_coverage_note(language)
    result = []
    replaced = False
    for note in notes:
        if _looks_like_calibration_coverage_confusion(note):
            if not replaced:
                result.append(replacement)
                replaced = True
            continue
        result.append(note)
    report["operatorNotes"] = result
    return report


def _recommendation_copy_override(language: str, target: str) -> dict[str, str] | None:
    """Keep high-risk recommendations framed as reviewable experiments."""
    if target == "intraday_correction.day_level_scale":
        if language == "en":
            return {
                "suggestion": (
                    "Treat a daytime scale-up rule as a backtest candidate when "
                    "hours 11:00-15:00 JST repeatedly show model bias below -500 MW."
                ),
                "expectedEffect": (
                    "Check whether persistent daytime underprediction improves without "
                    "pushing the evening curve upward."
                ),
                "risk": (
                    "A broad scale-up rule can overcorrect mild-demand days or days "
                    "with a sharp afternoon decline."
                ),
                "validationPlan": (
                    "Replay the recent 7-14 days and compare daytime MAE/WAPE, evening "
                    "MAE, and max-error hours before considering deployment."
                ),
            }
        if language == "ja":
            return {
                "suggestion": (
                    "11〜15時台でモデルバイアスが-500 MWを下回る状態が反復する場合、"
                    "昼間スケール補正をバックテスト候補として扱います。"
                ),
                "expectedEffect": (
                    "昼間の過小予測が改善し、夕方の曲線を過度に押し上げないかを確認します。"
                ),
                "risk": (
                    "穏やかな需要日や午後に急低下する日では、過補正になる可能性があります。"
                ),
                "validationPlan": (
                    "直近7〜14日をリプレイし、昼間MAE/WAPE、夕方MAE、最大誤差時間を比較してから採用を判断します。"
                ),
            }
        return {
            "suggestion": (
                "11~15시 구간에서 모델 바이어스가 -500 MW 이하로 반복될 때, "
                "낮 시간 스케일 보정을 백테스트 후보로 둡니다."
            ),
            "expectedEffect": (
                "낮 시간 과소예측이 줄어드는지 보되, 저녁 예측선을 과하게 끌어올리지 않는지 함께 확인합니다."
            ),
            "risk": (
                "수요가 온화한 날이나 오후에 급락하는 날에는 과보정으로 바뀔 수 있습니다."
            ),
            "validationPlan": (
                "최근 7~14일 리플레이에서 낮 시간 MAE/WAPE, 저녁 MAE, 최대 오차 시간을 함께 비교합니다."
            ),
        }
    if target == "serving.published_forecast_freeze":
        if language == "en":
            return {
                "suggestion": (
                    "Review the published-forecast freeze policy as an experiment when "
                    "the published versus recalculated gap exceeds 500 MW in hours "
                    "15:00-17:00 JST."
                ),
                "expectedEffect": (
                    "Reduce visible serving drift when a later recalculation materially "
                    "changes the afternoon line."
                ),
                "risk": (
                    "Relaxing freeze behavior too much can make the public curve look "
                    "unstable during intraday updates."
                ),
                "validationPlan": (
                    "For the next 10 intraday runs, compare published/recalculated gaps, "
                    "actual error, and whether a refresh would have improved the served line."
                ),
            }
        if language == "ja":
            return {
                "suggestion": (
                    "15〜17時台で公開線と再計算線の差が500 MWを超える場合、"
                    "公開予測線の保持ポリシーを検証候補として見直します。"
                ),
                "expectedEffect": (
                    "午後の再計算で曲線が大きく変わった場合の、画面上の乖離を抑えます。"
                ),
                "risk": (
                    "保持を緩めすぎると、intraday更新時に公開曲線が不安定に見える可能性があります。"
                ),
                "validationPlan": (
                    "次の10回のintraday実行で、公開線と再計算線の差、実誤差、再公開した場合の改善幅を比較します。"
                ),
            }
        return {
            "suggestion": (
                "15~17시 구간에서 발표선과 재계산선의 차이가 500 MW를 넘는 경우, "
                "예측선 보존 정책을 실험 후보로 재검토합니다."
            ),
            "expectedEffect": (
                "오후 재계산 결과가 크게 달라졌을 때, 화면에 남는 예측선 괴리를 줄일 수 있는지 확인합니다."
            ),
            "risk": (
                "보존 정책을 너무 느슨하게 하면 intraday 갱신 때 공개 곡선이 불안정해 보일 수 있습니다."
            ),
            "validationPlan": (
                "다음 10회 intraday 실행에서 발표선-재계산선 갭, 실제 오차, 재공개 시 개선폭을 비교합니다."
            ),
        }
    return None


def _format_mw(value: Any) -> str:
    number = _as_float(value)
    if number is None:
        return "n/a"
    return f"{number:.1f} MW"


def _format_pct(value: Any) -> str:
    number = _as_float(value)
    if number is None:
        return "n/a"
    return f"{number:.2f}%"


def _largest_freeze_gap(report: dict) -> dict | None:
    gaps = (
        ((report.get("diagnosticContext") or {}).get("freezeImpact") or {})
        .get("largestGaps")
        or []
    )
    if not isinstance(gaps, list):
        return None
    candidates = [
        gap for gap in gaps
        if isinstance(gap, dict) and _as_float(gap.get("freezeGapMw")) is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda gap: abs(_as_float(gap.get("freezeGapMw")) or 0.0))


def _deterministic_executive_summary_copy(report: dict) -> dict | None:
    perf = report.get("performance") or {}
    if not isinstance(perf, dict):
        return None
    hours_float = _as_float(perf.get("comparableHours"))
    if hours_float is None or hours_float <= 0:
        return None

    hours = int(hours_float)
    language = str(report.get("language") or "ko")
    current = report.get("executiveSummary") or {}
    verdict = current.get("modelVerdict") or perf.get("verdict") or "mixed"
    model_adv = perf.get("modelAdvantageHours")
    tepco_adv = perf.get("tepcoAdvantageHours")
    model_text = (
        f"MAE {_format_mw(perf.get('modelMaeMw'))}, "
        f"WAPE {_format_pct(perf.get('modelWapePct'))}"
    )
    tepco_text = (
        f"MAE {_format_mw(perf.get('tepcoMaeMw'))}, "
        f"WAPE {_format_pct(perf.get('tepcoWapePct'))}"
    )
    advantage_text = f"{model_adv}/{hours}"
    tepco_advantage_text = f"{tepco_adv}/{hours}"
    freeze_gap = _largest_freeze_gap(report)

    if language == "en":
        headlines = {
            "model_better": "The model had lower daily error than TEPCO.",
            "tepco_better": "TEPCO had lower daily error than the model.",
            "close": "Model and TEPCO errors were close.",
            "mixed": "Daily accuracy was mixed across hour bands.",
            "insufficient": "Daily accuracy could not be evaluated.",
        }
        freeze_sentence = ""
        if freeze_gap is not None:
            freeze_sentence = (
                " The largest published-versus-recalculated gap was "
                f"{_format_mw(freeze_gap.get('freezeGapMw'))} at "
                f"{freeze_gap.get('hour')}:00 JST."
            )
        summary = (
            f"Across {hours} comparable hours, the model recorded {model_text}; "
            f"TEPCO recorded {tepco_text}. Model advantage hours were "
            f"{advantage_text}, while TEPCO advantage hours were "
            f"{tepco_advantage_text}.{freeze_sentence}"
        )
    elif language == "ja":
        headlines = {
            "model_better": "モデルの日次誤差はTEPCO予測より小さくなりました。",
            "tepco_better": "TEPCO予測の日次誤差はモデルより小さくなりました。",
            "close": "モデルとTEPCO予測の日次誤差は近い水準でした。",
            "mixed": "時間帯によって優位性が分かれました。",
            "insufficient": "日次精度を評価する十分なデータがありません。",
        }
        freeze_sentence = ""
        if freeze_gap is not None:
            freeze_sentence = (
                " 公開予測と再計算線の最大差は"
                f"{freeze_gap.get('hour')}:00 JSTで"
                f"{_format_mw(freeze_gap.get('freezeGapMw'))}でした。"
            )
        summary = (
            f"比較可能な{hours}時間で、モデルは{model_text}、"
            f"TEPCOは{tepco_text}でした。モデル優位は{advantage_text}、"
            f"TEPCO優位は{tepco_advantage_text}です。{freeze_sentence}"
        )
    else:
        headlines = {
            "model_better": "모델의 일간 오차가 TEPCO 예측보다 작았습니다.",
            "tepco_better": "TEPCO 예측의 일간 오차가 모델보다 작았습니다.",
            "close": "모델과 TEPCO 예측의 일간 오차가 비슷했습니다.",
            "mixed": "시간대별로 성능 우위가 엇갈렸습니다.",
            "insufficient": "일간 성능을 평가할 데이터가 부족합니다.",
        }
        freeze_sentence = ""
        if freeze_gap is not None:
            freeze_sentence = (
                " 가장 큰 발표선-재계산선 차이는 "
                f"{freeze_gap.get('hour')}:00 JST에 "
                f"{_format_mw(freeze_gap.get('freezeGapMw'))}였습니다."
            )
        summary = (
            f"비교 가능 {hours}시간 기준 모델은 {model_text}, "
            f"TEPCO는 {tepco_text}였습니다. 모델 우위 시간은 "
            f"{advantage_text}, TEPCO 우위 시간은 {tepco_advantage_text}입니다."
            f"{freeze_sentence}"
        )

    return {
        "severity": current.get("severity", "info"),
        "headline": headlines.get(verdict, headlines["mixed"]),
        "summary": summary,
        "modelVerdict": verdict,
        "confidence": current.get("confidence", "medium"),
    }


def _deterministic_freeze_hypothesis(report: dict) -> dict | None:
    gap = _largest_freeze_gap(report)
    if gap is None:
        return None
    gaps = (
        ((report.get("diagnosticContext") or {}).get("freezeImpact") or {})
        .get("largestGaps")
        or []
    )
    evidence = []
    related_hours = []
    for item in gaps[:3]:
        if not isinstance(item, dict):
            continue
        hour = item.get("hour")
        evidence.append({
            "source": "freezeImpact",
            "metric": "freezeGapMw",
            "value": _round_number(item.get("freezeGapMw")),
            "unit": "MW",
            "hour": hour,
            "timeBand": None,
        })
        if isinstance(hour, int):
            related_hours.append(hour)
    language = str(report.get("language") or "ko")
    if language == "en":
        title = "Published forecast freeze left a visible serving gap."
        explanation = (
            "The published line differed materially from the latest recalculated "
            "post-calibration line, so served chart shape should be reviewed "
            "separately from raw model accuracy."
        )
    elif language == "ja":
        title = "公開予測の固定により表示線に差が残りました。"
        explanation = (
            "公開された予測線と最新の再計算後ラインに大きな差があるため、"
            "rawモデル精度とは分けて表示上の形状リスクを確認します。"
        )
    else:
        title = "예측선 보존 정책으로 표시선 격차가 남았습니다."
        explanation = (
            "공개된 예측선과 최신 재계산 후 라인 사이에 큰 차이가 있어, "
            "raw 모델 정확도와 별도로 화면에 남는 곡선 형태 리스크를 확인해야 합니다."
        )
    return {
        "id": "serving.published_forecast_freeze",
        "severity": "warning",
        "confidence": "medium",
        "evidenceStatus": "partial",
        "title": title,
        "explanation": explanation,
        "evidence": evidence,
        "relatedHours": related_hours,
        "relatedTimeBands": [],
        "relatedFeatures": ["serving.published_forecast_freeze"],
        "counterEvidence": [],
    }


def _executive_summary_needs_repair(report: dict) -> bool:
    summary = report.get("executiveSummary") or {}
    if not isinstance(summary, dict):
        return False
    text = " ".join(
        str(summary.get(field) or "")
        for field in ("headline", "summary")
    )
    lowered = text.lower()
    return "mape" in lowered or "mean absolute percentage error" in lowered


def _polish_report_language(report: dict) -> dict:
    language = str(report.get("language") or "")
    if language not in MESSAGES:
        return _clarify_operator_notes_coverage(report)

    summary = report.get("executiveSummary")
    if isinstance(summary, dict):
        for field in ("headline", "summary"):
            summary[field] = _polish_localized_text(language, summary.get(field))
        deterministic_summary = _deterministic_executive_summary_copy(report)
        if deterministic_summary is not None:
            report["executiveSummary"] = deterministic_summary

    for hypothesis in report.get("rootCauseHypotheses") or []:
        if not isinstance(hypothesis, dict):
            continue
        for field in ("title", "explanation", "counterEvidence"):
            hypothesis[field] = _polish_localized_text(language, hypothesis.get(field))

    for recommendation in report.get("featureRecommendations") or []:
        if not isinstance(recommendation, dict):
            continue
        override = _recommendation_copy_override(
            language,
            str(recommendation.get("target") or ""),
        )
        if override:
            recommendation.update(override)
        for field in ("suggestion", "expectedEffect", "risk", "validationPlan"):
            recommendation[field] = _polish_localized_text(
                language,
                recommendation.get(field),
            )

    report["operatorNotes"] = _polish_localized_text(
        language,
        report.get("operatorNotes") or [],
    )
    report["limitations"] = _polish_localized_text(
        language,
        report.get("limitations") or [],
    )
    report = _clarify_operator_notes_coverage(report)
    if isinstance(report.get("dataQuality"), dict):
        report["dataQuality"]["limitations"] = report["limitations"]
    return report


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


def _critical_analysis_text_blob(analysis: dict) -> str:
    """Return prose fields that must be readable in the target language."""
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
    return "\n".join(parts)


def _count_pattern(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text))


def _validate_localized_analysis(language: str, analysis: dict) -> None:
    text = _critical_analysis_text_blob(analysis) or _analysis_text_blob(analysis)
    hangul_count = _count_pattern(r"[\uac00-\ud7a3]", text)
    kana_count = _count_pattern(r"[\u3040-\u30ff]", text)
    cjk_count = _count_pattern(r"[\u4e00-\u9fff]", text)
    if language == "ko" and hangul_count < 8:
        raise ValueError("Korean localization did not contain Hangul text")
    if language == "ko" and cjk_count >= 8 and cjk_count > hangul_count * 2:
        raise ValueError("Korean localization looked CJK-corrupted")
    if language == "ja" and kana_count < 8:
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


def _merge_localized_reports_from_payload(
    fallback_reports: dict[str, dict],
    master_layer: dict,
    localized_payload: dict,
    localization_targets: list[str],
    analysis_model: str,
    localization_model: str,
) -> dict[str, dict]:
    localized_reports = localized_payload.get("reports")
    if not isinstance(localized_reports, dict):
        localized_reports = {}

    merged_reports: dict[str, dict] = {}
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
    return merged_reports


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
    localization_error: Exception | None = None
    for attempt in (1, 2):
        try:
            localized_payload = _call_openai_localization_analysis(
                localization_context,
                api_key,
                localization_model,
                localization_targets,
            )
            merged_reports.update(
                _merge_localized_reports_from_payload(
                    fallback_reports,
                    master_layer,
                    localized_payload,
                    localization_targets,
                    analysis_model,
                    localization_model,
                )
            )
            localization_error = None
            break
        except (
            OSError,
            urllib.error.URLError,
            TimeoutError,
            ValueError,
            json.JSONDecodeError,
        ) as e:
            localization_error = e
            if attempt == 1 and _consume_openai_budget(budget):
                print(
                    "[WARN] OpenAI localization failed "
                    f"for {date_iso} ({','.join(localization_targets)}): "
                    f"{_redact_error(e)}; retrying once with {localization_model}"
                )
                continue
            print(
                "[WARN] OpenAI localization failed "
                f"for {date_iso} ({','.join(localization_targets)}): "
                f"{_redact_error(e)}; using English master fallback"
            )
            break

    if localization_error is not None:
        for language in localization_targets:
            merged_reports[language] = _english_master_localization_fallback_report(
                fallback_reports[language],
                master_report,
                analysis_model,
                localization_model,
                localization_error,
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
                messages["openai_failed_template"].format(error=_redact_error(error)),
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

    api_key = _clean_env_value(PROJECT_OPENAI_API_KEY_ENV)
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
            messages["openai_failed_template"].format(error=_redact_error(e)),
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
    api_key_available = bool(_clean_env_value(PROJECT_OPENAI_API_KEY_ENV))
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
    api_key = _clean_env_value(PROJECT_OPENAI_API_KEY_ENV)
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
                existing_provider = (
                    (existing_report.get("generator") or {}).get("provider")
                )
                should_retry_latest_fallback = (
                    bool(api_key)
                    and bool(should_use_openai)
                    and date_iso == latest_date
                    and latest_only
                    and language in allowed_locales
                    and existing_provider != "openai"
                    and budget.get("remaining", 0) > 0
                )
                if should_retry_latest_fallback:
                    existing_report = None
                else:
                    date_reports[language] = existing_report
                    continue
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
                print(
                    "[WARN] OpenAI daily report failed "
                    f"for {date_iso}: {_redact_error(e)}; using fallback reports"
                )
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
        help="Maximum OpenAI report attempts in this run. Defaults to OPENAI_DAILY_REPORT_MAX_CALLS_PER_RUN or 3.",
    )
    parser.add_argument(
        "--openai-languages",
        default=None,
        help="Comma-separated locales allowed to use OpenAI. Defaults to OPENAI_DAILY_REPORT_LOCALES or ko,en,ja.",
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
