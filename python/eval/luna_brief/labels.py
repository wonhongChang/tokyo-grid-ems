"""Localized labels for the offline daily operations brief, based on the verified v7 ledger."""
from python.eval import experimental_luna_full_relations as full

LANG = ("en","ko","ja")
def tr(s,lang):
    parts=s.split("|")
    return parts[LANG.index(lang)] if len(parts)==3 else s


GROUP = {
    "coverage":"Evaluation populations|평가 모집단|評価母集団",
    "daily":"Daily accuracy|일간 정확도|日別精度",
    "peak":"Peak timing and level|피크 시각과 수요|ピーク時刻と需要",
    "band":"Accuracy by time band|구간 평균 비교|時間帯別の平均比較",
    "point":"Same-hour comparison|같은 시간의 예측 비교|同一対象時刻の予測比較",
    "change":"Adjacent-hour changes|연속 시간의 변화|隣接時刻間の変化",
    "stages":"Retained calibration stages|보존 실행의 단계별 예측|保存実行の段階別予測",
    "vintage":"Published vs latest recalculation|공개 예측과 최신 재계산 비교|公開予測と最新再計算の比較",
    "check":"Checks to perform|확인 절차|確認手順",
    "experiment":"Conditional replay designs|조건부 리플레이 설계|条件付きリプレイ設計",
    "shape_daily":"Daily ramp accuracy|일간 변화량 오차|日別の変化量誤差",
    "weather":"Weather diagnostic by band|구간별 기상 진단|時間帯別の気象診断",
    "regime":"Daily diagnostic flags|일간 진단 플래그|日別診断フラグ",
    "control":"Recorded controller activity|기록된 보정 작동|記録された補正の作動",
    "history":"Retained runs|보존 실행 이력|保存された実行履歴",
}
PAIR = ("Daily report actuals at matched JST targets. Signed error = forecast minus actual. Matching issue times are not established."
        "|일간 자료의 같은 대상 시각 실측(JST) 기준입니다. 오차는 예측−실측입니다. 발행 시각 일치는 확인되지 않았습니다."
        "|日別資料の同じ対象時刻の実績（JST）で比較します。誤差は予測−実績。発行時刻の一致は確認できません。")
STAGE = ("One retained calculation, not a reconstruction of the original publication. Its recorded actual can differ from the daily actual."
         "|보존된 한 실행의 결과입니다. 원래 발행 당시를 복원한 값이 아니며, 당시 실측과 일간 실측은 다를 수 있습니다."
         "|保存された一つの実行の結果です。当初の発行の再現ではなく、記録時の実績は日別実績と異なることがあります。")
REPLAY = ("After-the-fact review, not an instruction to change a forecast. Recover issue-time inputs before a replay."
          "|사후 확인 절차이며 예측 변경 지시가 아닙니다. 리플레이 전에 발행 당시 입력을 확보해야 합니다."
          "|事後の確認手順で、予測変更の指示ではありません。リプレイ前に発行時点の入力を確保します。")
BASIS={k:PAIR for k in GROUP}
ASSOCIATION=("Recorded diagnostic context for this date, not proof of the cause or of availability at publication."
             "|해당 날짜에 기록된 진단 맥락입니다. 오차의 원인이나 발행 당시의 가용성을 입증하지 않습니다."
             "|対象日について記録された診断情報です。誤差の原因や発行時の利用可能性を示すものではありません。")
BASIS.update(stages=STAGE, control=STAGE, check=REPLAY, experiment=REPLAY, weather=ASSOCIATION,regime=ASSOCIATION,
    history="Multiple retained runs, not additional target hours.|같은 대상일의 여러 실행이며, 비교 시간이 늘어난 것이 아닙니다.|同じ対象日の複数の保存実行で、比較対象時刻が増えたわけではありません。",
    coverage="Daily observations and retained-run observations are separate populations.|일간 실측과 보존 실행의 관측 시간은 다른 모집단입니다.|日別実績と保存実行の観測時間は別の母集団です。")
VOCAB = {
    "day":"Day|일간|日別", "published":"Published|공개 예측|公開予測", "latest":"Latest recalculation|최신 재계산|最新再計算",
    "tepco":"TEPCO", "tie":"Tie|동률|同差", "over":"Over|과대|過大", "under":"Under|과소|過小", "equal":"Exact|일치|一致",
    "daily_report_full":"Full daily sample|일간 전체 표본|日別全標本", "partial":"Partial sample|부분 표본|部分標本",
    "unconfirmed":"Not confirmed|확정 여부 미확인|確定を確認できず","invalid_hour_identity":"Ambiguous target hour|대상 시각 불일치|対象時刻不整合",
    "population_mismatch":"Incompatible sample|비교 모집단 불일치|比較母集団不一致","source_missing_or_mismatched":"Missing or mismatched source|원자료 누락 또는 불일치|原資料の欠落・不一致",
    "close":"Close|비슷함|同程度", "model_better":"Model better|모델 우위|モデル優位", "tepco_better":"TEPCO better|TEPCO 우위|TEPCO優位",
    "mixed":"Mixed|혼재|混在","insufficient":"Insufficient|자료 부족|資料不足",
    "issue_required":"Issue-time inputs not established|당시 발행 입력 확인 필요|発行時の入力を要確認",
    "large_point":"Large same-hour error|같은 시각의 큰 오차|同じ時刻の大きな誤差",
    "verified_gap":"Recorded gap meets review criterion|기록된 선 간 차이가 검토 조건 충족|記録された予測間差が確認条件を満たす",
    "replay_vintage":"If studying revisions, recover original releases first|발행 이력 조사 시에만 원 발행본 우선 확보|改定調査を行う場合のみ、まず当初の発行記録を確保",
    "paired_release_errors":"Compare absolute error and revision size at matched lead|같은 리드의 절대오차·발행 간 수정량 대조|同一リードの絶対誤差・改定幅を比較",
    "replay_stages":"Recover the original run; compare raw, pre- and post-calibration|당시 실행을 복원해 원천·보정 전·보정 후 대조|当時の実行を復元し元予測・補正前・補正後を比較",
    "original_and_retained":"Compare with publication separately; check an opposite case|당시 공개선은 별도로 비교하고 반대 사례 확인|当時の公開予測を別に比較し逆方向の例を確認",
    "matched_replay":"Match issue, target and cohort; include the opposite case. No automatic change.|발행·대상·비교집단을 맞추고 반대 사례도 포함. 자동 변경 없음.|発行・対象・比較群をそろえ逆方向の例を含む。自動変更なし。",
    "point":"Point error|시간 오차|時刻別誤差","shape":"Change mismatch|변화량 불일치|変化量の不一致",
    "observed":"Observed|관측|観測","tepco_forecast_fallback":"TEPCO forecast substitute|TEPCO 예측 대체값|TEPCO予測の代替値",
}
FIELDS = {
    "observed":"Observed hours|관측 시간 수|観測時間数","comparable":"Paired hours|비교 시간 수|比較時間数",
    "fallback":"Substitute hours|대체 실측 시간 수|代替実績時間数","snapshotHours":"Retained observed hours|보존 실행 관측 시간 수|保存実行の観測時間数",
    "population":"Scope|범위|範囲","hours":"Hours|시간 수|時間数","bias":"Mean signed bias|평균 부호 편향|平均符号付き誤差",
    "modelMaeMw":"Published MAE","tepcoMaeMw":"TEPCO MAE","modelWapePct":"Published WAPE (%)","tepcoWapePct":"TEPCO WAPE (%)",
    "modelRmseMw":"Published RMSE","tepcoRmseMw":"TEPCO RMSE","modelWins":"Model wins|모델 우위 시간|モデル優位時間数",
    "tepcoWins":"TEPCO wins|TEPCO 우위 시간|TEPCO優位時間数","ties":"Ties|동률 시간|同差時間数","verdict":"Rule verdict|기존 규칙 판정|既存規則の判定",
    "actual":"Daily actual|일간 실측|日別実績","published":VOCAB["published"],"tepco":"TEPCO",
    "actualPeak":"Actual peak|실측 피크|実績ピーク","publishedHours":"Published peak times|공개 피크 시각|公開ピーク時刻",
    "publishedPeak":"Published peak|공개 피크|公開ピーク","tepcoHours":"TEPCO peak times|TEPCO 피크 시각|TEPCOピーク時刻","tepcoPeak":"TEPCO peak|TEPCO 피크|TEPCOピーク",
    "timing":"Published − actual (hours)|공개−실측 시차(시간)|公開−実績の時刻差（時間）",
    "error":"Published − actual|공개−실측|公開−実績","direction":"Published direction|공개 오차 방향|公開誤差の方向",
    "tepcoError":"TEPCO − actual|TEPCO−실측|TEPCO−実績","tepcoDirection":"TEPCO direction|TEPCO 오차 방향|TEPCO誤差の方向",
    "closer":"Lower absolute error|절대오차가 작은 쪽|絶対誤差が小さい側","lowerMAE":"Lower MAE|MAE가 작은 쪽|MAEが小さい側",
    "actualDelta":"Actual change|실측 변화|実績変化","publishedDelta":"Published change|공개 변화|公開変化","tepcoDelta":"TEPCO change|TEPCO 변화|TEPCO変化",
    "deltaError":"Published − actual change|공개−실측 변화량|公開−実績変化量","tepcoDeltaError":"TEPCO − actual change|TEPCO−실측 변화량|TEPCO−実績変化量",
    "transitionHours":"Adjacent pairs|인접 시간쌍|隣接ペア","modelDeltaMaeMw":"Published change MAE|공개 변화량 MAE|公開変化量MAE",
    "tepcoDeltaMaeMw":"TEPCO change MAE|TEPCO 변화량 MAE|TEPCO変化量MAE","maxActualRiseMw":"Largest actual rise|실측 최대 상승|実績最大上昇",
    "maxActualDropMw":"Largest actual drop|실측 최대 하락|実績最大下落","maxModelRiseMw":"Largest published rise|공개 최대 상승|公開最大上昇",
    "maxModelDropMw":"Largest published drop|공개 최대 하락|公開最大下落","run":"Retained run timestamp|보존 실행 기록 시각|保存実行の記録時刻",
    "raw_lgbm":"Raw|원천|元予測","same_regime_level_calibrated":"Regime level|동일 레짐 레벨|同一局面水準",
    "analog_adjusted":"Analog day|유사일 보정|類似日補正","post_holiday_guarded":"Post-holiday|휴일 후 보정|休日後補正",
    "midday_guarded":"Midday|점심 보정|昼間補正","localized_shape_guarded":"Local shape|국소 형상 보정|局所形状補正",
    "pre_calibration":"Pre-calibration|보정 전|補正前","post_calibration":"Post-calibration|보정 후|補正後",
    "snapshotActual":"Actual in retained run|보존 실행 실측|保存実行内の実績","snapshotSource":"Its source|당시 실측 출처|記録時の実績出典",
    "snapshotSlope":"Recorded slope|기록된 기울기|記録時の傾き","latest":VOCAB["latest"],"basis":"Recalculation stage|재계산 단계|再計算段階",
    "gap":"Published − latest|공개−최신 재계산|公開−最新再計算","latestError":"Latest − actual|재계산−실측|再計算−実績",
    "procedure":"Check|확인 절차|確認手順","compare":"Compare|비교 항목|比較項目","condition":"When|표시 조건|表示条件",
    "asOf":"Issue-time evidence|발행 시점 근거|発行時の根拠","trigger":"Event|검증 계기|検証契機",
    "eligibility":"Test hypothesis / conditions|실험 가설 및 조건|実験仮説・条件",
    "rawError":"Raw − daily actual|원천−일간 실측|元予測−日別実績","preError":"Pre − daily actual|보정 전−일간 실측|補正前−日別実績",
    "postError":"Post − daily actual|보정 후−일간 실측|補正後−日別実績",
    "feature":"Experiment target|실험 대상|実験対象","window":"Replay window (JST)|재현 구간(JST)|再現区間（JST）",
    "metrics":"Evaluation metrics|평가 지표|評価指標","protocol":"Test conditions|시험 조건|試験条件",
    "coolingDelta24hMean":"24h cooling change (°C)|24시간 냉방도 변화(°C)|24時間冷房度差（°C）",
    "modelBiasMw":"Published bias|공개 편향|公開バイアス","assessment":"Recorded assessment|기록된 판정|記録された判定",
    "flags":"Recorded flags|기록된 플래그|記録されたフラグ","lag24OverheatMeanMw":"Mean lag excess|평균 시차 초과|平均ラグ超過",
    "tempDelta24hMeanC":"24h temperature change (°C)|24시간 기온 변화(°C)|24時間気温差（°C）",
    "flag":"Applied flag|적용 플래그|適用フラグ","measure":"Measurement|측정 항목|測定項目","value":"Value|값|値","unit":"Unit|단위|単位",
    "snapshotCount":"Retained runs|보존 횟수|保存回数","dominantAppliedRegimeReason":"Most frequent reason|최빈 사유|最多理由",
    "dominantReasonCount":"Occurrences|기록 횟수|記録回数","latestGeneratedAt":"Latest timestamp|마지막 기록 시각|最終記録時刻",
    "appliedRuns":"Runs with application or reason|보정 적용·사유가 있는 실행|補正適用・理由がある実行",
}
for k in ("modelMaeMw","modelRmseMw","modelWapePct"):
    metric=FIELDS[k].removeprefix("Published ")
    FIELDS[k]+="|공개 "+metric+"|公開"+metric
VOCAB.update({k:FIELDS[k] for k in full.STAGES})
VOCAB.update(
    evening_intersection="Evening overforecast, observed decline and positive post-calibration change|저녁 과대예측·관측 하락·보정 후 상승 동시 확인|夕方の過大予測、観測低下、補正後の上昇が同時に成立",
    morning_hypothesis="Test previous-day ramp vs same-business-type anchors; time alone does not establish a cause|전날 램프와 같은 영업형태 기준 비교. 시각만으로 원인 확정 불가|前日ランプと同じ営業区分の基準を比較。時刻のみでは原因不明",
    midday_hypothesis="Separate raw shape, calibration and publication before testing a midday interaction|원천 형상·보정·공개선을 분리한 뒤 점심 상호작용 검증|元の形状・補正・公開を区別して昼の相互作用を検証",
)
MW=set("modelMaeMw tepcoMaeMw modelRmseMw tepcoRmseMw bias actual published tepco actualPeak publishedPeak tepcoPeak error tepcoError actualDelta publishedDelta tepcoDelta deltaError tepcoDeltaError modelDeltaMaeMw tepcoDeltaMaeMw maxActualRiseMw maxActualDropMw maxModelRiseMw maxModelDropMw snapshotActual snapshotSlope latest gap latestError modelBiasMw lag24OverheatMeanMw".split())|set(full.STAGES)
MW.update(("rawError","preError","postError"))


def label(key,lang):
    return tr(FIELDS[key],lang)+(" (MW)" if key in MW else "")


def cell(key,value,lang):
    if value is None: return tr("Not established|미확인|未確認",lang)
    if isinstance(value,list): return " · ".join(cell(key,x,lang) for x in value)
    if key=="metrics" and value in full.common.core.METRICS:
        return full.common.core.METRICS[value][LANG.index(lang)]
    if isinstance(value,str): return tr(VOCAB.get(value,value),lang)
    if key in MW: return f"{value:,.1f}"
    return str(value)
