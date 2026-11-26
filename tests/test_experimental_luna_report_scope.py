import ast
from copy import deepcopy
import inspect

import pytest

from python.eval import daily_operation_report as daily
from python.eval import experimental_luna_report_scope as scope


DAY = "2026-01-01"
INSIGHTS = {
    "model_closer_overall", "tepco_closer_overall", "mixed_operational_assessment",
    "morning_ramp_underestimated", "morning_ramp_overestimated", "daytime_level_underestimated",
    "afternoon_plateau_underestimated", "large_single_hour_miss", "sharp_model_rise_mismatch",
    "sharp_model_drop_mismatch", "peak_timing_miss", "peak_level_underestimated", "peak_level_overestimated",
}


def test_require_scope_decision_for_each_legacy_insight():
    tree = ast.parse(inspect.getsource(daily._build_insights))
    emitted = {node.args[1].value for node in ast.walk(tree) if isinstance(node, ast.Call)
               and getattr(node.func, "id", None) == "_add_insight"}
    assert emitted == INSIGHTS
    for lang in scope.LOCALES:
        assert set(scope.LIVE.INSIGHT_TEMPLATES_BY_LANG[lang]) == emitted - {"mixed_operational_assessment"}


@pytest.mark.parametrize("band,bias,tag",[
    ("morning_ramp", -500.0,"morning_ramp_underestimated"),("morning_ramp",500.0,"morning_ramp_overestimated"),
    ("daytime",-700.0,"daytime_level_underestimated"),("late_afternoon",-500.0,"afternoon_plateau_underestimated")])
def test_band_threshold_is_for_commentary_not_whether_fact_exists(band,bias,tag):
    s={"verdict":"close"}
    row={"code":band,"label":"06-10","modelBiasMw":bias}
    assert [x["code"] for x in daily._build_insights(s,None,[row],[])] == [tag]
    row["modelBiasMw"] = bias * 0.99
    assert daily._build_insights(s,None,[row],[]) == []


@pytest.mark.parametrize("hours,mw,codes",[
    (1,799.9,[]),(-2,800,["peak_timing_miss","peak_level_overestimated"]),
    (2,-800,["peak_timing_miss","peak_level_underestimated"])])
def test_close_does_not_disable_peak_insight_thresholds(hours,mw,codes):
    assert [x["code"] for x in daily._build_insights({"verdict":"close"},
        {"model":{"timeErrorHours":hours,"errorAtActualPeakMw":mw}},[],[])] == codes


@pytest.mark.parametrize("magnitude,expected",[(1199.9,[]),(1200,["large_single_hour_miss"])])
def test_hour_threshold(magnitude,expected):
    assert [x["code"] for x in daily._build_insights({"verdict":"close"},None,[],
        [{"hour":0,"modelAbsErrorMw":magnitude}])] == expected


@pytest.mark.parametrize("delta,code",[(1500,"sharp_model_rise_mismatch"),(-1500,"sharp_model_drop_mismatch")])
def test_change_difference_is_not_demand_direction(delta,code):
    shape={"largeShapeBreaks":[{"modelDeltaErrorMw":delta,"fromHour":5,"toHour":6,"actualDeltaMw":2000,
                               "modelDeltaMw":2000+delta}]}
    assert [x["code"] for x in daily._build_insights({"verdict":"close"},None,[],[],shape)] == [code]


def inputs():
    base = {"date": DAY, "timezone": "Asia/Tokyo", "availability": "ok"}
    return ({**base, "series": [{"ts": f"{DAY}T{h:02d}:00:00+09:00", "actualMw": h + 1, "tepcoForecastMw": 30-h}
                                for h in range(24)]},
            {**base, "series": [{"ts": f"{DAY}T{h:02d}:00:00+09:00", "forecastMw": 30-h,
                                "p95LowerMw": 0, "p95UpperMw": 40} for h in range(24)]},
            {**base, "summary": {"comparableHours": 24}, "generatedAt": "2026-01-02T01:00:00+09:00"},
            {"scope": "final_daily_actuals_for_performance", "observedHours": 24, "comparableHours": 24,
             "fallbackActualHours": 0})


def test_peak_is_published_minus_actual_and_at_actual_hour_not_difference_of_maxima():
    state, r = scope.population(DAY, *inputs())
    assert state == "daily_report_full"
    assert scope.peak(r) == {"actual": [23], "published": [0], "tepco": [0], "maxima": [24, 30, 30],
                             "timing": -23, "errorsAtActualPeak": [-17]}


def test_multiple_ties_do_not_invent_unique_delta_or_error():
    a, f, op, c = inputs()
    a["series"][0]["actualMw"] = 24
    f["series"][2]["forecastMw"] = 30
    a["series"].reverse()
    assert scope.peak(scope.population(DAY, a, f, op, c)[1]) == {
        "actual": [0, 23], "published": [0, 2], "tepco": [0], "maxima": [24, 30, 30],
        "timing": None, "errorsAtActualPeak": [6, -17]}


@pytest.mark.parametrize("condition,expected", [
    ("missing", "partial"), ("fallback", "partial"), ("duplicate", "invalid_hour_identity"),
    ("wrongday", "invalid_hour_identity"), ("offhour", "invalid_hour_identity"), ("timezone", "invalid_hour_identity"),
    ("provisional", "unconfirmed"), ("not_final_row", "unconfirmed"), ("same_day_report", "unconfirmed"),
    ("latest_not_published", "source_missing_or_mismatched"), ("wrong_count", "population_mismatch"),
    ("unknown_scope", "unconfirmed")])
def test_invalid_or_unfinalized_inputs(condition, expected):
    a, f, op, c = inputs()
    if condition in ("missing", "fallback"):
        if condition == "missing":
            f["series"].pop()
        else:
            a["series"][0]["actualSource"] = "tepco_forecast_fallback"
        op["summary"]["comparableHours"] = 23
    elif condition == "duplicate":
        a["series"].append(deepcopy(a["series"][0]))
    elif condition in ("wrongday", "offhour", "timezone"):
        f["series"][6]["ts"] = {"wrongday":"2026-01-02T06:00:00+09:00","offhour":DAY+"T06:30:00+09:00",
                                 "timezone":DAY+"T06:00:00Z"}[condition]
    elif condition == "provisional": a["availability"] = "provisional"
    elif condition == "not_final_row": a["series"][5]["finalized"] = False
    elif condition == "same_day_report": op["generatedAt"] = DAY+"T23:59:59+09:00"
    elif condition == "latest_not_published": f["date"] = "2026-01-02"
    elif condition == "wrong_count": op["summary"]["comparableHours"] = 22
    else: c["scope"] = "retained_intraday_calibration_snapshot_not_final_actual_csv"
    status, rows = scope.population(DAY, a, f, op, c)
    assert status == expected
    assert len(rows) == (23 if expected == "partial" else 0)


def test_bounds_require_all_matched_hours_per_level():
    a, f, op, c = inputs()
    _, rows = scope.population(DAY, a, f, op, c)
    assert scope.interval_inputs_valid(rows, f, 95) and not scope.interval_inputs_valid(rows, f, 99)
    del f["series"][3]["p95LowerMw"]
    assert not scope.interval_inputs_valid(rows, f, 95)
    f["series"][3]["p95LowerMw"] = 41
    assert not scope.interval_inputs_valid(rows, f, 95)


def synthetic(tmp, change=None):
    live = scope.LIVE
    a, f, op, _ = inputs()
    stamp = op["generatedAt"]
    files = {"actual": a, "forecast": f}
    if change:
        change(files)
    refs = {k: f"{prefix}/{DAY}.json" for k, prefix in {
        "actual":"actual","forecast":"forecast","operationReport":"reports/daily",
        "internalDiagnostics":"reports/internal/daily-diagnostics",
        "operationalCalibration":"reports/internal/operational-calibration"}.items()}
    refs["operationalCalibrationHistory"] = f"reports/internal/operational-calibration/snapshots/{DAY}/index.json"
    for k, value in files.items():
        live._write_json(tmp / refs[k], value)
    report = daily.build_daily_operation_report(tmp, DAY, stamp)
    live._write_json(tmp / refs["operationReport"], report)
    files["operationReport"] = report
    fb = live._build_fallback_ai_daily_report(tmp, DAY, stamp, "en")
    ctx = live._sanitize_openai_context(live._load_openai_context(tmp, fb))["factPacket"]
    return fb, ctx, files


def test_source_guards_and_localized_absence(tmp_path):
    fb, packet, s = synthetic(tmp_path)
    docs, receipt = scope.render(fb, packet, None, s)
    assert receipt["population"] == "daily_report_full"
    for loc, doc in docs.items():
        for key in ("diagnostics_missing", "no_calibration", "timeline_limit"):
            assert scope.LIMITS[key][scope.LOCALES.index(loc)] in doc["limitations"]
    s["forecast"]["series"][0]["forecastMw"] += 1
    with pytest.raises(ValueError, match="fingerprint"): scope.render(fb, packet, None, s)


def test_zero_or_partial_never_silently_become_full_day(tmp_path):
    for n in (0, 19, 20, 23):
        def change(files):
            files["forecast"]["series"] = files["forecast"]["series"][:n]
        fb, packet, sources = synthetic(tmp_path / str(n), change)
        docs, r = scope.render(fb, packet, None, sources)
        assert r["peak"] is None and not r["additional"]
        assert ("partial_peaks" in r["facts"]) == (n >= 20)
        assert ("partial.morning_ramp" in r["facts"]) == (n >= 20)
        for doc in docs.values():
            assert not doc["rootCauseHypotheses"] and not doc["featureRecommendations"]
            assert doc["performance"] == fb["performance"]


def test_conditionally_report_measured_weather_and_flags_not_causal_cards(tmp_path):
    def extra(files):
        files["internalDiagnostics"] = {"date":DAY, "diagnosticSummary":{"dayLevelRegime":{"flags":["cool_lag_overheat_regime"]},
            "weatherDeltaRiskByBand":[{"assessment":"neutral","label":"00-05"},{"assessment":"possible","label":"06-10",
                                        "coolingDelta24hMean":2.5,"modelBiasMw":370.0}]}}
        files["operationalCalibration"] = {"date":DAY, "correction":{
            "businessTypeTransitionPriorApplied":True,"businessTypeTransitionPriorBiasMw":100.0,
            "positiveResidualMitigationApplied":True,"positiveResidualMitigationMaxMw":42,
            "businessTypeTransitionApplied":True,"businessTypeTransitionBiasMw":-150,
            "negResidualRecoveryDampingApplied":True,"negResidualRecoveryDampingFactor":0.4}}
        files["operationalCalibrationHistory"] = {"date":DAY, "snapshots":[{"appliedRegimeReason":["b"]},
                                                                             {"appliedRegimeReason":["a"]}]}
    fb,p,s = synthetic(tmp_path, extra)
    docs,r = scope.render(fb,p,None,s)
    assert {"lag_flag","weather.06-10"} <= r["facts"].keys()
    assert "weather.00-05" not in r["facts"]
    for loc, doc in docs.items():
        text = " ".join(doc["operatorNotes"])
        for k in ("calibration_prior_title","calibration_transition_title","calibration_positive_title","calibration_recovery_title"):
            assert scope.LIVE.MESSAGES[loc][k] in text
        assert {"en":"a (1)", "ko":"a (1회)", "ja":"a（1回）"}[loc] in text
        assert not doc["featureRecommendations"]


def test_mixed_keeps_verdict_without_claim_about_time_bands(tmp_path):
    fb,p,s = synthetic(tmp_path)
    s["operationReport"]["summary"]["verdict"] = "mixed"
    fb["performance"]["verdict"] = fb["executiveSummary"]["modelVerdict"] = "mixed"
    fb["inputSnapshot"]["sources"]["operationReport"]["fingerprint"] = scope.LIVE._fingerprint_json_values(s["operationReport"])
    docs,_ = scope.render(fb,p,None,s)
    assert docs["en"]["executiveSummary"]["modelVerdict"] == "mixed"
    assert "hour bands" not in docs["en"]["executiveSummary"]["headline"]
