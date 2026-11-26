"""Reviewed report terms and sentence templates; ordering is en, ko, ja."""

TERMS = {
    "raw_lgbm": ("raw forecast", "원천 예측", "元の予測"),
    "analog_adjusted": ("analog-day adjusted forecast", "유사일 보정 예측", "類似日補正後の予測"),
    "pre_calibration": ("pre-calibration forecast", "보정 전 예측", "補正前の予測"),
    "post_calibration": ("post-calibration forecast", "보정 후 예측", "補正後の予測"),
    "published": ("published forecast", "공개 예측", "公開予測"),
}

SENTENCES = {
    "point": (
        "At {hour}, the published forecast minus finalized actual was {error}.",
        "{hour} 공개 예측에서 확정 실측을 뺀 오차는 {error}였습니다.",
        "{hour}の公開予測から確定実績を引いた誤差は{error}でした。",
    ),
    "band_label": (
        "Published forecast against finalized actuals by time band (signed mean error / MAE):",
        "시간대별 공개 예측과 확정 실측 비교 (부호 있는 평균 오차 / MAE):",
        "時間帯別の公開予測と確定実績の比較（平均符号付き誤差 / MAE）：",
    ),
    "band_values": ("{window} ({count} pairs): {bias} / {mae}",
                    "{window} ({count}쌍): {bias} / {mae}", "{window}（{count}組）：{bias} / {mae}"),
    "snapshot": (
        "Finalized daily evaluation: {final} observed hours. Retained calibration snapshot: {snapshot} observed hours; these are separate populations.",
        "일간 성능 평가의 확정 실측은 {final}시간, 보관된 보정 스냅샷의 실측은 {snapshot}시간입니다. 두 집계는 별개입니다.",
        "日次性能評価の確定実績は{final}時間、保存された補正スナップショットの実績は{snapshot}時間です。両者は別の集計対象です。",
    ),
    "final_only": ("Finalized daily evaluation: {final} observed hours.",
                   "일간 성능 평가의 확정 실측은 {final}시간입니다.", "日次性能評価の確定実績は{final}時間です。"),
    "point_title": ("Verified hourly forecast error", "확인된 시간별 예측 오차", "確認された時間別予測誤差"),
    "shape_title": ("Published forecast and demand change", "공개 예측과 실측의 변화", "公開予測と実績の変化"),
    "vintage_title": ("Published forecast versus latest recalculation", "공개 예측과 최신 재계산 비교", "公開予測と最新の再計算の比較"),
    "unverified_cause": (
        "The difference is observed, but the stage or input that introduced it is unverified.",
        "차이는 확인됐지만, 어떤 단계나 입력에서 발생했는지는 확인되지 않았습니다.",
        "差は確認できましたが、どの段階または入力に由来するかは未確認です。",
    ),
    "vintage_cause": (
        "Both errors use the same finalized actual. This does not establish why the forecasts differ.",
        "두 오차는 같은 확정 실측을 기준으로 하며, 예측선이 달라진 이유를 입증하지는 않습니다.",
        "両方の誤差は同じ確定実績を基準としています。予測が異なる原因を示すものではありません。",
    ),
    "check_point": (
        "Replay the hour the forecast missed and an opposite-direction case. Compare {stages} for the same issue and target.",
        "예측이 빗나간 시간대와 반대 방향 사례를 리플레이해 같은 발행 시점·대상 시간의 {stages}을 비교하세요.",
        "予測が外れた時間帯と逆方向の事例をリプレイし、同じ発行時点・対象時間の{stages}を比較してください。",
    ),
    "check_shape": (
        "Compare slopes for {stages} at the same issue time and target window; include an opposite-direction case.",
        "같은 발행 시점·대상 시간대에서 {stages}의 기울기를 비교하고, 반대 방향 사례도 포함하세요.",
        "同じ発行時点・対象時間帯で{stages}の傾きを比較し、逆方向の事例も含めてください。",
    ),
    "check_vintage": (
        "Check publication history and issue times. Compare same-run stages separately from the published and latest forecasts.",
        "공개 이력과 발행 시점을 확인하세요. 동일 실행의 단계별 비교와 공개선·최신 재계산선 비교는 분리하세요.",
        "公開履歴と発行時点を確認してください。同一実行内の段階比較と、公開予測・最新の再計算予測の比較は分けてください。",
    ),
    "ticket_check": (
        "Replay {window}. Compare {stages} for the same issue and target, then compare against the published forecast separately.",
        "{window}를 리플레이하세요. 같은 발행 시점·대상 시간의 단계({stages})를 비교한 뒤, 공개 예측과의 비교는 별도로 수행하세요.",
        "{window}をリプレイしてください。同じ発行時点・対象時間の段階（{stages}）を比較したうえで、公開予測との比較は別に行ってください。",
    ),
    "ticket_suggestion": ("Replay {window}; {focus}", "{window} 리플레이: {focus}", "{window}のリプレイ：{focus}"),
    "ticket_goal": (
        "Test the hypothesis against the same issue and target before considering any change.",
        "변경을 검토하기 전에 같은 발행 시점·대상 시간의 근거로 가설을 검증하세요.",
        "変更を検討する前に、同じ発行時点・対象時間の根拠で仮説を検証してください。",
    ),
    "ticket_metrics": (
        "Measure {metrics}; include an opposite-direction case. Report publication-vintage effects separately.",
        "{metrics}를 평가하고 반대 방향 사례를 포함하세요. 발행 시점에 따른 차이는 별도로 보고하세요.",
        "{metrics}を評価し、逆方向の事例も含めてください。発行時点による影響は分けて報告してください。",
    ),
    "ticket_notice": (
        "These replay proposals are for validation only and are not applied automatically.",
        "리플레이 제안은 검증용이며 자동으로 적용되지 않습니다.",
        "リプレイの提案は検証用であり、自動で適用されることはありません。",
    ),
    "limits": (
        "Analysis uses finalized daily actuals, published forecasts and retained diagnostics where available. Retained calibration observations are not finalized actuals. Latest recalculation is not the original published forecast; exact issue timing and causality require separate evidence.",
        "확정 일간 실측, 공개 예측, 확보된 진단 자료를 사용했습니다. 보관된 보정 관측은 확정 실측과 구분합니다. 최신 재계산은 당시 공개 예측과 다르며 정확한 발행 시점과 원인은 별도 근거가 필요합니다.",
        "確定した日次実績、公開予測、利用可能な診断資料を使用しました。保存された補正時の観測と確定実績は区別します。最新の再計算は当時の公開予測ではなく、正確な発行時点や原因には別の根拠が必要です。",
    ),
}

METRICS = {
    "06-11 MAE/WAPE": ("06–11 JST MAE/WAPE", "06~11시 JST MAE/WAPE", "06～11時 JSTのMAE/WAPE"),
    "11-15 MAE/WAPE": ("11–15 JST MAE/WAPE", "11~15시 JST MAE/WAPE", "11～15時 JSTのMAE/WAPE"),
    "16-19 MAE/WAPE": ("16–19 JST MAE/WAPE", "16~19시 JST MAE/WAPE", "16～19時 JSTのMAE/WAPE"),
    "max absolute error": ("maximum absolute error", "최대 절대오차", "最大絶対誤差"),
    "same-hour TEPCO absolute-error gap": (
        "same-hour absolute-error gap versus TEPCO", "동일 시간대 TEPCO 대비 절대오차 차이", "同じ時間のTEPCO予測との絶対誤差差",
    ),
    "shape delta error": ("shape-change error", "시간 간 변화량 오차", "時間帯間の変化量誤差"),
    "max error around lunch/daily peak": (
        "maximum error near lunch and the daily peak", "점심·일중 피크 전후 최대오차", "昼食時間帯・日中ピーク付近の最大誤差",
    ),
    "overprediction tail error": ("upper tail of overprediction errors", "과대예측 상위 꼬리 오차", "過大予測誤差の上側の裾"),
}

# Input ticket IDs come only from the deterministic public fact packet.
REPLAY = {
    "lag_24h_hourly_delta": {
        "focus": ("compare the previous-day ramp, recent same-business-day ramps, and weather inputs.",
                  "전날 램프, 최근 같은 영업일 유형의 램프, 기상 입력을 비교하세요.",
                  "前日のランプ、直近の同じ営業日区分のランプ、気象入力を比較してください。"),
        "risk": ("Damping can suppress a genuine business-day or cooling-demand ramp.",
                 "감쇠를 강화하면 실제 업무·냉방 수요 상승까지 누를 수 있습니다.",
                 "減衰を強めると、実際の業務・冷房需要の立ち上がりを抑えるおそれがあります。"),
    },
    "business_midday_x_lag_24h_delta": {
        "focus": ("check the midday shape and separate the raw forecast, analog-day effect, calibration and publication vintage.",
                  "점심 전후 형상을 검증하고 원천 예측, 유사일 효과, 보정, 공개 시점의 영향을 구분하세요.",
                  "昼前後の形状を検証し、元の予測、類似日の影響、補正、公開時点を切り分けてください。"),
        "risk": ("A stronger midday guard can overfit the lunch dip and weaken afternoon recovery.",
                 "점심 가드를 강화하면 점심 하락에 과적합해 오후 회복을 훼손할 수 있습니다.",
                 "昼のガードを強めると昼の落ち込みに過適合し、午後の回復を弱めるおそれがあります。"),
    },
    "intraday_correction.evening_decline_continuity_guard": {
        "focus": ("test whether a near-term cap helps when the published forecast rises against observed evening decline.",
                  "저녁 실측은 하락하는데 공개 예측이 상승한 조건에서 근거리 상한의 효과를 검증하세요.",
                  "夕方の実績が低下する一方で公開予測が上昇した条件で、短期上限の効果を検証してください。"),
        "risk": ("Damping can miss a genuine late-day heat or activity rebound.",
                 "감쇠하면 늦은 시간의 실제 냉방·활동 수요 반등을 놓칠 수 있습니다.",
                 "減衰により、夕方の実際の冷房・活動需要の持ち直しを見逃すおそれがあります。"),
    },
}
