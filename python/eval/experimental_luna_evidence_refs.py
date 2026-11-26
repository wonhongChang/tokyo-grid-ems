"""Isolated report QA: typed observations and protected bilingual rendering."""

from collections import Counter
from copy import deepcopy
from decimal import Decimal
import re
import unicodedata

from . import experimental_luna_report as prior

INSTRUCTIONS = (
    "Select at most three useful observations for a Tokyo grid report. Return an evidenceId and "
    "a claim code, never a number or free prose. Select at most one per kind. Signs are forecast "
    "minus finalized actual or ending minus starting MW. Prefer the most informative defensible "
    "interpretation, not a list of all rows. For vintages compare absolute, not signed, error: "
    "a smaller absolute error is closer; opposite_sides says nothing about comparative accuracy. "
    "For shape compare directions, not magnitudes. No cause, operational verdict, or intervention. "
    "Return an empty list when there are no eligible observations."
)
KINDS = {
    "point": ("overshot", "undershot"),
    "shape": ("opposite_directions", "same_direction"),
    "vintage": ("published_closer", "recalculated_closer", "equal_distance", "opposite_sides"),
}
SCHEMA = {
    "type": "object", "required": ["observations"], "additionalProperties": False,
    "properties": {"observations": {"type": "array", "maxItems": 3, "items": {
        "type": "object", "required": ["evidenceId", "claim"], "additionalProperties": False,
        "properties": {"evidenceId": {"type": "string"},
                       "claim": {"type": "string", "enum": [c for codes in KINDS.values() for c in codes]}},
    }}},
}


def evidence(packet):
    """Get independently matched rows. Target time is not issue-time provenance."""
    _, facts = prior._observations(packet)
    rows = {r["hour"]: r for r in packet.get("focusedRows", []) if type(r.get("hour")) is int}
    if len(rows) != len(packet.get("focusedRows", [])):
        return {}
    events = packet["analysisPriorities"]["events"] if facts else []
    if len({e.get("id") for e in events}) != len(events):
        return {}
    by_id = {e["id"]: e for e in events}
    output = {}
    for key, fact in facts.items():
        kind, hour, *values = fact
        if type(hour) is not int or not 0 <= hour < 24:
            continue
        row = {"evidenceId": key, "kind": kind, "fromHourJst": hour, "unit": "MW"}
        if kind == "point":
            row["publishedMinusActual"] = values[0]
        elif kind == "shape":
            end, actual, published = values
            if end >= 24:
                continue
            row.update(toHourJst=end, actualChange=actual, publishedChange=published)
        else:
            event = by_id[key]
            source = rows[hour]
            recalc = source.get("postCalibrationForecastMw")
            basis = "post_calibration"
            if recalc is None:
                recalc = source.get("preCalibrationForecastMw")
                basis = "pre_calibration"
            if not prior._eq(event["latestRecalculatedForecastMw"], recalc):
                continue
            row.update(publishedMinusActual=values[0], recalculatedMinusActual=values[1],
                       publishedMinusRecalculated=values[2], recalculatedBasis=basis)
        output[key] = row
    return output


def supported(row, claim):
    kind = row["kind"]
    if claim not in KINDS[kind]:
        return False
    if kind == "point":
        return claim == ("overshot" if row["publishedMinusActual"] > 0 else "undershot")
    if kind == "shape":
        opposite = row["actualChange"] * row["publishedChange"] < 0
        return claim == ("opposite_directions" if opposite else "same_direction")
    p, r = row["publishedMinusActual"], row["recalculatedMinusActual"]
    closer = "published_closer" if abs(p) < abs(r) else "recalculated_closer" if abs(p) > abs(r) else "equal_distance"
    return claim == closer or (claim == "opposite_sides" and p * r < 0)


def choose(raw, rows):
    """Return accepted refs and per-claim rejections; a bad card cannot poison its peers."""
    accepted, rejected, kinds = {}, [], set()
    for item in raw.get("observations", []):
        key, claim = item["evidenceId"], item["claim"]
        row = rows.get(key)
        if row is None or not supported(row, claim):
            rejected.append({"evidenceId": key, "claim": claim, "reason": "unverified_reference_or_claim"})
        elif row["kind"] in kinds:
            rejected.append({"evidenceId": key, "claim": claim, "reason": "duplicate_kind"})
        else:
            accepted[key] = claim
            kinds.add(row["kind"])
    return accepted, rejected


def _mw(number):
    return f"{Decimal(str(number)):+,.1f} MW"


COMPARISONS = {
    "published_closer": ("The published forecast was closer to the actual.",
                         "공개 예측이 확정 실측에 더 가까웠습니다.", "公開予測の方が確定実績に近い値でした。"),
    "recalculated_closer": ("The latest recalculated forecast was closer to the actual.",
                            "최신 재계산 예측이 확정 실측에 더 가까웠습니다.", "最新の再計算予測の方が確定実績に近い値でした。"),
    "equal_distance": ("Both forecasts were equally far from the actual.",
                       "두 예측의 절대오차는 같았습니다.", "両予測の絶対誤差は同じでした。"),
    "opposite_sides": ("The two forecasts erred in opposite directions.",
                       "두 예측의 오차 방향은 서로 반대였습니다.", "両予測の誤差の符号は逆でした。"),
    "opposite_directions": ("The trajectories moved in opposite directions.",
                            "실측과 공개 예측의 변화 방향은 반대였습니다.", "実績と公開予測は逆方向に変化しました。"),
    "same_direction": ("The trajectories moved in the same direction.",
                       "실측과 공개 예측의 변화 방향은 같았습니다.", "実績と公開予測は同方向に変化しました。"),
}


def capsule(row, claim, locale):
    """Render the exact same evidence/candidate relation in all three locales."""
    idx = ("en", "ko", "ja").index(locale)
    hour = f'{row["fromHourJst"]:02d}:00'
    if row["kind"] == "point":
        value = _mw(row["publishedMinusActual"])
        return (f"At {hour} JST, the published forecast minus finalized actual was {value}.",
                f"{hour} JST 공개 예측에서 확정 실측을 뺀 오차는 {value}였습니다.",
                f"{hour} JSTの公開予測から確定実績を引いた誤差は{value}でした。")[idx]
    if row["kind"] == "shape":
        end = f'{row["toHourJst"]:02d}:00'
        a, p = _mw(row["actualChange"]), _mw(row["publishedChange"])
        line = (f"From {hour} to {end} JST, finalized actual and published forecast changed by {a} and {p}, respectively.",
                f"{hour}~{end} JST 확정 실측과 공개 예측의 변화량은 각각 {a}, {p}였습니다.",
                f"{hour}～{end} JSTの確定実績と公開予測の変化量は、それぞれ{a}と{p}でした。")[idx]
    else:
        p, r = _mw(row["publishedMinusActual"]), _mw(row["recalculatedMinusActual"])
        line = (f"At {hour} JST, the published forecast and latest recalculated forecast had errors of {p} and {r} against the same finalized actual.",
                f"{hour} JST 동일한 확정 실측 대비 공개 예측 오차는 {p}, 최신 재계산 예측 오차는 {r}였습니다.",
                f"{hour} JSTの同じ確定実績に対する公開予測の誤差は{p}、最新の再計算予測の誤差は{r}でした。")[idx]
    return line + " " + COMPARISONS[claim][idx] if claim in COMPARISONS else line


def render(fallback, packet, raw):
    rows = evidence(packet)
    accepted, rejected = choose(raw, rows)
    # The legacy candidate still supplies deterministic verdicts and copy. No model prose
    # enters it; add only validated claims and reuse its exact card metadata/fallbacks.
    events, _ = prior._observations(packet)
    analysis = deepcopy(packet)
    priority = analysis.setdefault("analysisPriorities", {}) or {}
    analysis["analysisPriorities"] = priority
    ordered = [*accepted, *(k for k in rows if k not in accepted)]
    priority["events"] = [events[k] for k in ordered]
    report, _ = prior.merge(fallback, {}, analysis)
    locked = {}
    summaries = {lang: prior.live._deterministic_executive_summary_copy({**report, "language": lang})
                 for lang in ("en", "ko", "ja")}
    if all(summaries.values()):
        for field in ("headline", "summary"):
            locked[("executiveSummary", field)] = {lang: copy[field] for lang, copy in summaries.items()}
    coverage = packet.get("coverageContext") or {}
    for source, english, korean, japanese in (
        ("finalActualCoverage", "Finalized performance uses {n} observed hours.",
         "확정 성능 평가는 실측 {n}시간을 사용합니다.", "確定した性能評価は実績{n}時間を使用しています。"),
        ("intradayCalibrationCoverage",
         "The retained calibration snapshot has {n} observed hours; it is not the daily performance population.",
         "보관된 보정 스냅샷은 실측 {n}시간을 포함하며, 일간 성능 평가와는 별개입니다.",
         "保存された補正スナップショットには実績が{n}時間分あり、日次の性能評価とは別の集計対象です。"),
    ):
        n = (coverage.get(source) or {}).get("observedHours")
        if type(n) is int:
            index = report["operatorNotes"].index(english.format(n=n))
            locked[("operatorNotes", index)] = {
                "en": english.format(n=n), "ko": korean.format(n=n), "ja": japanese.format(n=n),
            }
    for i, card in enumerate(report["rootCauseHypotheses"]):
        key = card["sourceEventIds"][0]
        row = rows[key]
        kind = row["kind"]
        # Preserve safe, validation-only comparisons for a verified card, never a model action.
        claim = accepted.get(key)
        if claim is None and kind in ("point", "shape"):
            claim = next(c for c in KINDS[kind] if supported(row, c))
        path = ("rootCauseHypotheses", i, "explanation")
        locked[path] = {lang: capsule(row, claim, lang) for lang in ("en", "ko", "ja")}
        card["explanation"] = locked[path]["en"]
        if kind == "vintage" and key in accepted:
            packet_candidates = {"featureRecommendations": [{
                "target": "serving.published_forecast_freeze", "type": "evaluation",
                "linkedHypotheses": [card["id"]], "autoApply": False,
            }]}
            report["featureRecommendations"] = prior._candidate_tickets(packet, events, [card], packet_candidates)
    return report, locked, {"accepted": accepted, "rejected": rejected,
                            "fallbackEvidence": [c["sourceEventIds"][0] for c in report["rootCauseHypotheses"]
                                                 if c["sourceEventIds"][0] not in accepted]}


# Canonical names are kept out of the translated text as opaque slots. Temporal
# claims outside the typed capsules are not licensed to introduce another date.
GLOSSARY = {
    "same-day subsequent recalculation": ("당일 후속 재계산", "同日中の後続の再計算"),
    "later recalculations": ("후속 재계산", "後続の再計算"),
    "a later recalculation": ("후속 재계산", "後続の再計算"),
    "later recalculation": ("후속 재계산", "後続の再計算"),
    "latest recalculated forecasts": ("최신 재계산 예측", "最新の再計算予測"),
    "latest recalculated forecast": ("최신 재계산 예측", "最新の再計算予測"),
    "published-forecast": ("공개 예측", "公開予測"),
    "published forecasts": ("공개 예측", "公開予測"),
    "published forecast": ("공개 예측", "公開予測"),
    "recalculated forecasts": ("재계산 예측", "再計算予測"),
    "recalculated forecast": ("재계산 예측", "再計算予測"),
    "publication time": ("공개 시점", "公開時点"),
    "issue times": ("발행 시점", "発行時点"),
    "issue time": ("발행 시점", "発行時点"),
    "finalized actuals": ("확정 실측", "確定実績"),
    "finalized actual": ("확정 실측", "確定実績"),
}
TOKEN = re.compile(r"\[\[X([A-Z]+)\]\]")
MASKABLE = re.compile(
    r"(?<!\w)(?:" + "|".join(map(re.escape, sorted(GLOSSARY, key=len, reverse=True))) +
    r")(?!\w)|[+\-\u2212]?\d[\d,]*(?::\d\d|\.\d+)?(?: ?(?:MW|%|JST))?", re.I
)
LOCALE_SCRIPT = {"ko": re.compile("[\uac00-\ud7a3]"), "ja": re.compile("[\u3040-\u30ff]")}
WRONG_DAY = {"ko": re.compile(r"다음\s*날|다른\s*날|익일|이튿날|훗날"),
             "ja": re.compile("後日|翌日|別の日|翌営業日|次の日|次の営業日")}
TRANSLATION_INSTRUCTIONS = (
    "Translate the English slot text into natural Korean and Japanese. Use each opaque token verbatim "
    "exactly once in its slot; position tokens naturally but do not swap the roles of tokens. Token kinds "
    "describe grammar only. Do not add digits, facts, or timing. Later means subsequent, never another "
    "calendar day. Never introduce another day (e.g. Japanese 後日 or Korean 익일), a cause, or approval. "
    "Retain negations, uncertainty, and contrast. Return each slot id in both languages."
)


def _tag(index):
    # The names carry no numeric value, date, evidence identity, or numeric slot count.
    return chr(65 + index) if index < 26 else _tag(index // 26 - 1) + _tag(index % 26)


def translation_slots(report, locked):
    slots, refs = {}, {}
    for i, path in enumerate(prior.translatable(report)):
        if path in locked:
            continue
        key = "s" + _tag(i)
        replacements = {}
        def mask(match):
            value = match[0]
            token = "[[X" + _tag(len(replacements)) + "]]"
            locale_values = GLOSSARY.get(value.lower())
            kind = value.lower().replace(" ", "_") if locale_values else "protected_quantity_or_time"
            replacements[token] = (kind, *(locale_values or (value, value)))
            return token
        slots[key] = {"en": MASKABLE.sub(mask, prior._get(report, path)),
                      "tokenKinds": {token: row[0] for token, row in replacements.items()}}
        refs[key] = (path, replacements)
    return slots, refs


def localize(report, locked, locale, translated):
    """Leave an invalid slot in English and record it; never replace typed evidence."""
    result = deepcopy(report)
    slots, refs = translation_slots(report, locked)
    failures = {k: "unexpected_slot" for k in translated.keys() - slots.keys()}
    idx = ("ko", "ja").index(locale)
    for key, (path, replacements) in refs.items():
        text = translated.get(key)
        if not isinstance(text, str):
            failures[key] = "missing_or_invalid_slot"
            continue
        text = unicodedata.normalize("NFKC", text.strip())
        rest = TOKEN.sub("", text)
        if Counter(m[0] for m in TOKEN.finditer(text)) != Counter(replacements.keys()):
            failures[key] = "protected_token_mismatch"
        elif (not LOCALE_SCRIPT[locale].search(rest) or WRONG_DAY[locale].search(rest)
              or any(c.isnumeric() for c in rest) or "[[" in rest or "]]" in rest or "\ufffd" in rest):
            failures[key] = "unverified_localized_text"
        else:
            prior._get(result, path[:-1])[path[-1]] = TOKEN.sub(lambda m: replacements[m[0]][idx + 1], text)
    for path, text in locked.items():
        prior._get(result, path[:-1])[path[-1]] = text[locale]
    result["language"] = locale
    result["contentLanguage"] = locale if not failures else "en"
    result["dataQuality"]["limitations"] = result["limitations"]
    result["generator"].update(localizationStatus="ok" if not failures else "partial",
                               localizationModel="gpt-6-luna")
    return result, failures
