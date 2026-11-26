"""Offline report renderer. Verified daily facts do not depend on narrative selection."""

from datetime import date, datetime, timedelta
import re

from . import experimental_luna_report_contract as core

LIVE = core.refs.prior.live
LOCALES = core.LOCALES
OBSERVED = {None, "observed"}
LIMITS = {
    "snapshot_limit": ("Only retained calibration runs can be reconstructed.",
                       "보정 실행 이력은 보존된 스냅샷 범위에서만 재구성할 수 있습니다.",
                       "補正の実行履歴を復元できるのは、保存されたスナップショットの範囲だけです。"),
    "timeline_limit": ("No intermediate calibration history is available here.",
                       "중간 보정 실행 이력이 없어 발행 과정 전체를 복원할 수 없습니다.",
                       "途中の補正履歴がなく、発行の経過全体は復元できません。"),
    "diagnostics_missing": ("Daily internal diagnostics are unavailable.", "일간 내부 진단 자료가 없습니다.",
                            "日別の内部診断資料はありません。"),
    "no_calibration": ("No calibration record is available for this date.", "이 날짜의 보정 기록이 없습니다.",
                       "この日の補正記録はありません。"),
}


def population(day, actual, forecast, operation, coverage):
    """Return the daily report's JST triples, never an hourly reconstruction from a latest run."""
    for source in (actual, forecast, operation):
        if not source or source.get("date") != day or source.get("timezone") != "Asia/Tokyo":
            return "source_missing_or_mismatched", {}
        if (source.get("availability") != "ok" or source.get("provisional") is True
                or source.get("finalized") is False or source.get("isFinal") is False):
            return "unconfirmed", {}
    try:
        stamp = datetime.fromisoformat(operation["generatedAt"])
        if stamp.utcoffset() != timedelta(hours=9) or stamp.date() <= date.fromisoformat(day):
            return "unconfirmed", {}
    except (ValueError, TypeError, KeyError):
        return "unconfirmed", {}
    if coverage.get("scope") != "final_daily_actuals_for_performance":
        return "unconfirmed", {}
    sides = []
    for doc, fields in ((actual, ("actualMw", "tepcoForecastMw")), (forecast, ("forecastMw",))):
        seen, selected = set(), {}
        for row in doc.get("series", []):
            try:
                ts = datetime.fromisoformat(row["ts"])
                if (ts.utcoffset() != timedelta(hours=9) or ts.date().isoformat() != day or ts.minute
                        or ts.second or ts.microsecond or ts.hour in seen):
                    return "invalid_hour_identity", {}
            except (TypeError, ValueError, KeyError):
                return "invalid_hour_identity", {}
            seen.add(ts.hour)
            if row.get("provisional") is True or row.get("finalized") is False:
                return "unconfirmed", {}
            if (doc is actual and row.get("actualSource") not in OBSERVED
                    or not all(core._finite(row.get(f)) for f in fields)):
                continue
            selected[ts.hour] = row
        sides.append(selected)
    a, f = sides
    triples = {h: (a[h]["actualMw"], f[h]["forecastMw"], a[h]["tepcoForecastMw"]) for h in sorted(a.keys() & f.keys())}
    if len(triples) != operation.get("summary", {}).get("comparableHours"):
        return "population_mismatch", {}
    if not core._full_final(coverage) or len(triples) != 24:
        return "partial", triples
    return "daily_report_full", triples


def peak(triples):
    """Preserve ties. An error at actual peak is not the difference of the daily maxima."""
    maxima = [max(r[i] for r in triples.values()) for i in range(3)]
    a, p, t = [[h for h in sorted(triples) if triples[h][i] == value] for i, value in enumerate(maxima)]
    return {"actual": a, "published": p, "tepco": t, "maxima": maxima,
            "timing": p[0] - a[0] if len(a) == len(p) == 1 else None,
            "errorsAtActualPeak": [round(triples[h][1] - triples[h][0], 1) for h in a]}


def _hours(hours):
    return ", ".join(f"{h:02d}:00" for h in hours)


def _values(values, signed=False):
    return " / ".join(format(x, "+,.1f" if signed else ",.1f") for x in values) + " MW"


def interval_inputs_valid(triples, forecast, level):
    rows = {x["ts"]: x for x in forecast["series"]}
    for h in triples:
        row = rows.get(f'{forecast["date"]}T{h:02}:00:00+09:00', {})
        lo, hi = (row.get(f"p{level}{k}Mw") for k in ("Lower", "Upper"))
        if not core._finite(lo) or not core._finite(hi) or lo > hi:
            return False
    return bool(triples)


def render(fallback, packet, raw, sources, *, assembled_at=None):
    """sources: pinned JSON payloads keyed by existing inputRefs, never mutable live endpoints."""
    for key in ("operationReport", "actual", "forecast", "internalDiagnostics", "operationalCalibration",
                "operationalCalibrationHistory"):
        src = sources.get(key)
        expected = (fallback.get("inputSnapshot", {}).get("sources", {}).get(key) or {}).get("fingerprint")
        if (LIVE._fingerprint_json_values(src) if src is not None else None) != expected:
            raise ValueError(f"input fingerprint mismatch: {key}")
    if (packet.get("date") != fallback["date"] or
            packet.get("inputSnapshot") != LIVE._compact_input_snapshot_for_prompt(fallback.get("inputSnapshot"))):
        raise ValueError("packet/report identity mismatch")
    op = sources.get("operationReport") or {}
    cov = (packet.get("coverageContext") or {}).get("finalActualCoverage") or {}
    state, triples = population(fallback["date"], sources.get("actual"), sources.get("forecast"), op, cov)
    for role in ("internalDiagnostics", "operationalCalibration", "operationalCalibrationHistory"):
        if sources.get(role) is not None and sources[role].get("date") != fallback["date"]:
            raise ValueError("diagnostic target date mismatch: " + role)
    if state != "daily_report_full":
        # Do not run a full-day interpretation on an unconfirmed, duplicate or partial population.
        from copy import deepcopy
        docs = {l: deepcopy(fallback) for l in LOCALES}
        receipt = {"mandatory": {}, "conditional": [], "additional": {}}
        for i, (loc, doc) in enumerate(docs.items()):
            m = LIVE.MESSAGES[loc]
            doc.update(language=loc, contentLanguage=loc, rootCauseHypotheses=[], featureRecommendations=[],
                       operatorNotes=[], limitations=[], diagnosticContext=None)
            doc["generator"].update(provider="fallback", model=None)
            day_note = ("A full-day comparison cannot be confirmed.", "하루 전체의 비교 모집단을 확인할 수 없습니다.",
                        "一日全体を比較できることは確認できません。")[i]
            report_summary = LIVE._deterministic_executive_summary_copy(doc)
            doc["executiveSummary"].update(headline=report_summary["headline"] if report_summary else m["headline_insufficient"],
                                           summary=day_note)
            doc["limitations"].append(day_note)
            doc["dataQuality"]["limitations"] = doc["limitations"]
    else:
        # Zero change is not a positive or negative direction.
        rows = core.refs.evidence(packet)
        raw_checked = None if raw is None else {"observations": [
            item for item in raw.get("observations", []) if isinstance(item, dict)
            and not (item.get("claim") == "same_direction" and
                     (r := rows.get(item.get("evidenceId"), {})).get("kind") == "shape"
                     and r["actualChange"] * r["publishedChange"] <= 0)]}
        docs, receipt = core.render(fallback, packet, raw_checked)
    trace = {}

    def add(key, words, *args, section="operatorNotes"):
        rendered = {}
        for loc, text in zip(LOCALES, words, strict=True):
            line = text.format(*args)
            docs[loc][section].append(line)
            rendered[loc] = line
        trace[key] = {"section": section, "text": rendered}

    if state == "daily_report_full":
        p = peak(triples)
        add("daily_peak", ("Peak hours (JST), actual / published / TEPCO: {} / {} / {}. Peak levels: {}.",
                           "피크 시각(JST)은 실측 / 공개 예측 / TEPCO 순서로 {} / {} / {}입니다. 각 최대 수요는 {}입니다.",
                           "ピーク時刻（JST）は実績・公開予測・TEPCOの順に {} / {} / {}、各最大需要は {} です。"),
            *(_hours(p[k]) for k in ("actual", "published", "tepco")), _values(p["maxima"]))
        if p["timing"] is None:
            add("tied_peak", ("There are tied maxima; no single timing difference is reported.",
                              "동률인 피크가 있어 단일 시차를 표시하지 않습니다.", "同率のピークがあるため、時刻差を一つに定めません。"))
            add("tied_peak_level", ("At actual peak hours {} JST, published errors respectively: {}.",
                                    "실측 피크 {} JST 각각의 공개 예측 오차는 순서대로 {}입니다.",
                                    "実績ピーク {} JST での公開予測誤差は順に {} です。"),
                _hours(p["actual"]), _values(p["errorsAtActualPeak"], True))
        else:
            add("peak_timing", ("Published peak minus actual peak: {:+d} h; published error at the actual peak: {}.",
                                "공개 피크 시각에서 실측 피크 시각을 뺀 차이는 {:+d}시간이며, 실측 피크 시각의 공개 예측 오차는 {}입니다.",
                                "公開予測ピークと実績ピークの時刻差（公開－実績）は {:+d} 時間、実績ピーク時の公開予測誤差は {} です。"),
                p["timing"], _values(p["errorsAtActualPeak"], True))
        s = op["summary"]
        if s.get("verdict") == "mixed":
            for i, loc in enumerate(LOCALES):
                docs[loc]["executiveSummary"]["headline"] = (
                    "The daily error metrics do not give a single winner.",
                    "일간 오차 지표를 함께 보면 한쪽의 우위로 판정되지 않습니다.",
                    "日別の誤差指標を総合すると、どちらか一方が優位とは判定できません。")[i]
        add("risk_and_wins", ("RMSE (published / TEPCO): {}. Hours closer to actual: published {}, TEPCO {}, tied {}.",
                              "RMSE(공개 예측 / TEPCO)는 {}입니다. 실측에 더 가까웠던 시간은 공개 예측 {}개, TEPCO {}개이며 동률은 {}개입니다.",
                              "RMSE（公開予測・TEPCO）は {}。実績に近かった時間数は公開予測 {}、TEPCO {}、同差 {} です。"),
            _values([s["modelRmseMw"], s["tepcoRmseMw"]]), s["modelWins"], s["tepcoWins"], s["ties"])
        bands = op.get("timeBands", [])
        if bands:
            parts = [f'{b["label"]}: {_values([b["modelMaeMw"], b["tepcoMaeMw"]])}' for b in bands]
            add("band_comparator", ("MAE by JST band (published / TEPCO): {}.", "시간대별 MAE(JST, 공개 예측 / TEPCO): {}.",
                                    "時間帯別MAE（JST、公開予測・TEPCO）: {}。"), "; ".join(parts))
        if not core.refs.evidence(packet):
            for m in op.get("topMisses", []):
                h = m["hour"]
                add(f"point.{h}", ("{} JST: published minus actual {}.", "{} JST 공개 예측에서 실측을 뺀 오차는 {}입니다.",
                                   "{} JST の公開予測から実績を引いた誤差は {} です。"), _hours([h]), _values([m["modelErrorMw"]], True))
            shape = core._day_shape(op)
            if shape:
                add("quiet_shape", tuple(core._capsule(shape)[l] for l in LOCALES))
        shape = op.get("shape") or {}
        if shape.get("transitionHours"):
            add("shape_mae", ("Across {} adjacent hourly transitions, change MAE (published / TEPCO) was {}.",
                              "연속한 {}개 시간쌍에서 시간당 변화량 MAE(공개 예측 / TEPCO)는 {}였습니다.",
                              "隣接する {} 組の時間変化に対するMAE（公開予測・TEPCO）は {} でした。"),
                shape["transitionHours"], _values([shape["modelDeltaMaeMw"], shape["tepcoDeltaMaeMw"]]))

        rows = core.refs.evidence(packet)
        calibration_rows = (sources.get("operationalCalibration") or {}).get("hourlyDiagnostics") or []
        for b in packet.get("eventEvidenceBundles") or []:
            key, h = b.get("eventId"), b.get("hour")
            if rows.get(key, {}).get("kind") != "point" or rows[key]["fromHourJst"] != h:
                continue
            sv = (b.get("stageEvidence") or {}).get("stageValues") or {}
            stages = [sv.get(k) for k in ("rawLgbmMw", "preCalibrationMw", "postCalibrationMw")]
            if all(map(core._finite, stages)) and sv.get("actualMw") == triples[h][0] and sv.get("publishedMw") == triples[h][1]:
                add(f"stage.{key}", ("{} JST in the retained calculation: raw / before calibration / after calibration: {}. Replay the original issue separately before attributing the published miss.",
                                     "{} JST 대상 보존 실행의 원천 예측 / 보정 전 / 보정 후: {}. 공개 오차의 기여를 판단하려면 당시 발행 실행을 별도로 재현하세요.",
                                     "{} JST を対象とする保存実行の元予測・補正前・補正後は {}。公開誤差への寄与を判定する前に当時の発行回を別に再現します。"),
                    _hours([h]), _values(stages))
            else:
                add(f"stage_missing.{key}", ("{} JST: recover the original issue before testing the raw, pre- and post-calibration stages. Same-issue attribution is unavailable here.",
                    "{} JST: 당시 실행을 확보한 뒤 원천 예측·보정 전·보정 후를 대조하세요. 여기서는 같은 실행의 기여를 확정할 수 없습니다.",
                    "{} JST：発行時の実行を確保してから元予測・補正前・補正後を比較します。ここでは同一実行の寄与を確定できません。"), _hours([h]))
            target_rows = [r for r in calibration_rows if r.get("hour") == h]
            slope = (b.get("shapeEvidence") or {}).get("sameDayActualSlopeMw")
            if len(target_rows) == 1 and core._finite(slope) and slope == target_rows[0].get("sameDayActualSlopeMw"):
                add(f"snapshot_slope.{key}", ("{} JST target: observed slope recorded in calibration {}. This is not the finalized daily change.",
                    "{} JST 대상 보정 기록의 당시 실측 기울기는 {}입니다. 확정 일간 시계열의 변화량과는 구분합니다.",
                    "{} JST 対象の補正記録にある当時の実績変化は {}。確定した一日の実績の変化量とは区別します。"),
                    _hours([h]), _values([slope], True))
        vintages = sorted({r["fromHourJst"] for r in rows.values() if r["kind"] == "vintage"})
        if vintages:
            add("vintage_replay", ("Replay {} JST at the original issue times. Compare absolute errors and changes between releases; a later recalculation need not have been available then.",
                                   "{} JST를 당시 발행 입력으로 재현해 절대오차와 연속 발행 사이의 수정 폭을 비교하세요. 최신 재계산값이 당시에도 가능했다는 뜻은 아닙니다.",
                                   "{} JST を発行当時の入力で再現し、絶対誤差と連続発行間の改定幅を比較します。最新の再計算値が当時も得られたとは限りません。"), _hours(vintages))
        for i, loc in enumerate(LOCALES):
            for ticket in docs[loc]["featureRecommendations"]:
                if ticket["target"] in ("lag_24h_hourly_delta", "business_midday_x_lag_24h_delta"):
                    ticket["validationPlan"] += (" Use the preceding 2–4 weeks of comparable replay data.",
                        " 직전 2~4주의 비교 가능한 리플레이 자료를 사용하세요.", " 直近2～4週間の比較可能なリプレイ資料を使います。")[i]
                if ticket["target"] == "business_midday_x_lag_24h_delta":
                    ticket["validationPlan"] += (" Inspect the largest misses around 11:00, 12:00 and 15:00 JST.",
                         " 11·12·15시(JST) 주변의 최대오차를 각각 확인하세요.", " 11・12・15時（JST）付近の最大誤差を個別に確認します。")[i]
        for level in (95, 99):
            if not interval_inputs_valid(triples, sources["forecast"], level):
                for doc in docs.values():
                    band = (doc.get("diagnosticContext") or {}).get("bandQuality") or {}
                    for name in (f"p{level}CoverageHours", f"p{level}CoverageRate"):
                        band.pop(name, None)
                add(f"interval_missing.{level}", ("P{} coverage is unavailable: not all comparable hours have valid bounds.",
                    "비교 시간 일부의 상·하한을 확인할 수 없어 P{} 포함률을 표시하지 않습니다.",
                    "比較対象時間の一部で上下限が確認できず、P{}の包含率は表示しません。"), level, section="limitations")
    else:
        p = None
        if state == "partial":
            add("partial", ("{} comparable hours; these do not establish a daily peak.",
                            "비교 가능한 {}시간만으로 하루 전체의 피크를 정할 수 없습니다.",
                            "比較可能な {} 時間だけでは一日のピークを特定できません。"), len(triples))
            if triples:
                observed = peak(triples)
                add("partial_peaks", ("Among these hours only, actual / published maxima occurred at {} / {} JST.",
                    "이 표본 안에서만 보면 실측 / 공개 예측 최댓값의 시각은 각각 {} / {} JST입니다.",
                    "この標本内での実績・公開予測の最大時刻はそれぞれ {} / {} JST です。"),
                    _hours(observed["actual"]), _hours(observed["published"]))
            for m in op.get("topMisses") or []:
                h = m.get("hour")
                if h in triples and core._finite(m.get("modelErrorMw")):
                    add(f"partial_point.{h}", ("{} JST: published error in the available sample {}.",
                         "{} JST: 비교 가능한 표본에서 공개 예측 오차는 {}입니다.",
                         "{} JST：比較可能な標本での公開予測誤差は {} です。"), _hours([h]), _values([m["modelErrorMw"]], True))
            for b in op.get("timeBands") or []:
                bounds = core._window(b.get("label"))
                if not bounds:
                    continue
                a, z = bounds
                n = sum(a <= h <= z for h in triples)
                if n and n == b.get("hours") and all(core._finite(b.get(k)) for k in ("modelBiasMw", "modelMaeMw")):
                    add("partial."+b["code"], ("{} JST, {} comparable hours: signed bias {}; MAE {}.",
                        "{} JST 비교 가능한 {}시간: 편향 {}, MAE {}.",
                        "{} JST の比較可能な {} 時間：バイアス {}、MAE {}。"),
                        b["label"], n, _values([b["modelBiasMw"]], True), _values([b["modelMaeMw"]]))

    summary = (sources.get("internalDiagnostics") or {}).get("diagnosticSummary") or {}
    regime = summary.get("dayLevelRegime") or {}
    if "cool_lag_overheat_regime" in (regime.get("flags") or []):
        add("lag_flag", ("The daily diagnostic flagged a cooler day with an elevated lag; it does not establish the cause of an error.",
            "일간 진단에 전일 대비 냉각·시차 수요 과열 신호가 기록됐습니다. 예측 오차의 원인으로 확인된 것은 아닙니다.",
            "日別診断に前日比の冷え込みとラグ需要の過熱が記録されました。誤差原因の特定ではありません。"))
        if all(core._finite(regime.get(k)) for k in ("lag24OverheatMeanMw", "tempDelta24hMeanC")):
            add("lag_measurements", ("Mean lag excess: {}; mean temperature change vs 24 h earlier: {} °C.",
                "평균 시차 수요 초과분은 {}, 24시간 전 대비 평균 기온 변화는 {} °C였습니다.",
                "平均ラグ超過量は {}、24時間前との平均気温差は {} °C でした。"),
                _values([regime["lag24OverheatMeanMw"]], True), f'{regime["tempDelta24hMeanC"]:+.1f}')
    for band in summary.get("weatherDeltaRiskByBand") or []:
        if (band.get("assessment") not in (None, "", "neutral") and core._window(band.get("label"))
                and all(core._finite(band.get(k)) for k in ("coolingDelta24hMean", "modelBiasMw"))):
            add("weather."+band["label"], ("{} JST: cooling change vs 24 h earlier {} °C; forecast bias {}. Association only.",
                "{} JST: 24시간 전 대비 냉방도 변화 {} °C, 예측 편향 {}. 원인으로 단정할 수 없습니다.",
                "{} JST：24時間前との冷房度の差 {} °C、予測バイアス {}。因果関係は未確認です。"),
                band["label"], f'{band["coolingDelta24hMean"]:+.1f}', _values([band["modelBiasMw"]], True))
    for i, loc in enumerate(LOCALES):
        m, doc = LIVE.MESSAGES[loc], docs[loc]
        doc["generatedAt"] = assembled_at or datetime.now().astimezone().isoformat(timespec="seconds")
        doc["generator"]["promptVersion"] = "luna_bound_observations.scope6"
        cal, hist = sources.get("operationalCalibration"), sources.get("operationalCalibrationHistory")
        for c in LIVE._calibration_hypotheses(cal, 0, m):
            # The flag is evidence of activation, not evidence that it helped.
            magnitude = c["evidence"][1]
            val = magnitude["value"]
            suffix = f' ({val}{(" " + magnitude["unit"]) if magnitude["unit"] else ""})' if core._finite(val) else ""
            doc["operatorNotes"].append(c["title"] + suffix)
        for c in LIVE._calibration_history_hypotheses(hist, 0, m):
            data = {x["metric"]: x["value"] for x in c["evidence"]}
            if not re.fullmatch(r"[A-Za-z0-9_.:-]+", str(data["dominantAppliedRegimeReason"])):
                continue
            doc["operatorNotes"].append(("Retained runs: {snapshotCount}; most frequent recorded reason: {dominantAppliedRegimeReason} ({dominantReasonCount}).",
                "보존 실행 {snapshotCount}건 중 가장 빈번한 기록 사유: {dominantAppliedRegimeReason} ({dominantReasonCount}회).",
                "保存された実行 {snapshotCount} 件の最多記録理由：{dominantAppliedRegimeReason}（{dominantReasonCount}回）。")[i].format(**data))
            applied = sum(bool(x.get("applied") or x.get("appliedRegimeReason")) for x in hist["snapshots"])
            doc["operatorNotes"][-1] += (" Runs with a correction or reason on record: {}.",
                " 보정 적용 또는 사유가 기록된 실행은 {}건입니다.", " 補正の適用または理由の記録がある実行は {} 件です。")[i].format(applied)
        limits = LIVE._build_limitations(m, sources.get("internalDiagnostics"), cal, hist)[1:]
        doc["limitations"].extend(copy[i] for key, copy in LIMITS.items() if m[key] in limits)
        if state in ("daily_report_full", "partial"):
            doc["limitations"].append(("TEPCO and the published model are compared at the same target hours. The TEPCO values in the daily source do not establish matched issue times.",
                "TEPCO와 공개 모델은 같은 실측 시간에 대해 비교했습니다. 일간 자료의 TEPCO 값만으로 두 예측의 발행 시점까지 같다고 볼 수 없습니다.",
                "TEPCOと公開モデルは同じ対象時刻で比較しています。日別資料のTEPCO値だけでは予測の発行時刻の一致は確認できません。")[i])
        doc["reviewPopulation"] = state
        doc["dataQuality"]["limitations"] = list(doc["limitations"])
    return docs, {**receipt, "population": state, "peak": p, "facts": trace}
