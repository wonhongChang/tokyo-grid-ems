"""Build model-vs-TEPCO forecast accuracy reports from published JSON files."""
from __future__ import annotations

import json
from pathlib import Path


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _win_counts(rows: list[dict]) -> tuple[int, int, int]:
    model_wins = sum(1 for row in rows if row["modelAbsErrorMw"] < row["tepcoAbsErrorMw"])
    tepco_wins = sum(1 for row in rows if row["tepcoAbsErrorMw"] < row["modelAbsErrorMw"])
    ties = len(rows) - model_wins - tepco_wins
    return model_wins, tepco_wins, ties


def _verdict(model_mae_mw: float | None, tepco_mae_mw: float | None) -> str:
    if model_mae_mw is None or tepco_mae_mw is None:
        return "insufficient"
    gap_mw = model_mae_mw - tepco_mae_mw
    if abs(gap_mw) <= 50.0:
        return "close"
    return "model_better" if gap_mw < 0 else "tepco_better"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _model_family(model_name: str) -> str:
    if model_name.endswith("_intraday_residual"):
        return model_name.removesuffix("_intraday_residual")
    return model_name


def _comparable_rows_for_date(public_dir: Path, date_iso: str) -> list[dict]:
    actual_path = public_dir / "actual" / f"{date_iso}.json"
    forecast_path = public_dir / "forecast" / f"{date_iso}.json"
    if not actual_path.exists() or not forecast_path.exists():
        return []

    actual = _load_json(actual_path)
    forecast = _load_json(forecast_path)
    model_name = forecast.get("model", {}).get("name") or "unknown"
    model_family = _model_family(model_name)
    forecast_by_hour = {
        point["ts"][11:13]: point
        for point in forecast.get("series", [])
        if point.get("forecastMw") is not None
    }

    rows: list[dict] = []
    for actual_point in actual.get("series", []):
        hour = actual_point.get("ts", "")[11:13]
        forecast_point = forecast_by_hour.get(hour)
        if forecast_point is None:
            continue

        actual_mw = actual_point.get("actualMw")
        tepco_forecast_mw = actual_point.get("tepcoForecastMw")
        model_forecast_mw = forecast_point.get("forecastMw")
        if actual_mw is None or tepco_forecast_mw is None or model_forecast_mw is None:
            continue

        model_abs_error_mw = abs(float(model_forecast_mw) - float(actual_mw))
        tepco_abs_error_mw = abs(float(tepco_forecast_mw) - float(actual_mw))
        rows.append({
            "date": date_iso,
            "hour": int(hour),
            "actualMw": round(float(actual_mw), 1),
            "modelForecastMw": round(float(model_forecast_mw), 1),
            "tepcoForecastMw": round(float(tepco_forecast_mw), 1),
            "modelAbsErrorMw": round(model_abs_error_mw, 1),
            "tepcoAbsErrorMw": round(tepco_abs_error_mw, 1),
            "modelName": model_name,
            "modelFamily": model_family,
        })
    return rows


def build_forecast_accuracy_report(
    public_dir: Path,
    generated_at: str,
    max_days: int = 30,
) -> dict:
    actual_dir = public_dir / "actual"
    if not actual_dir.exists():
        comparable_dates: list[str] = []
    else:
        comparable_dates = sorted(path.stem for path in actual_dir.glob("*.json"))
    comparable_dates = comparable_dates[-max_days:]

    all_rows: list[dict] = []
    daily: list[dict] = []
    for date_iso in comparable_dates:
        rows = _comparable_rows_for_date(public_dir, date_iso)
        if not rows:
            continue
        model_name = rows[0]["modelName"]
        model_family = rows[0]["modelFamily"]
        model_wins, tepco_wins, ties = _win_counts(rows)
        model_mae_mw = _mean([row["modelAbsErrorMw"] for row in rows])
        tepco_mae_mw = _mean([row["tepcoAbsErrorMw"] for row in rows])
        mae_gap_mw = (
            round(model_mae_mw - tepco_mae_mw, 1)
            if model_mae_mw is not None and tepco_mae_mw is not None
            else None
        )
        daily.append({
            "date": date_iso,
            "modelName": model_name,
            "modelFamily": model_family,
            "hours": len(rows),
            "modelMaeMw": model_mae_mw,
            "tepcoMaeMw": tepco_mae_mw,
            "maeGapMw": mae_gap_mw,
            "verdict": _verdict(model_mae_mw, tepco_mae_mw),
            "modelWins": model_wins,
            "tepcoWins": tepco_wins,
            "ties": ties,
        })
        all_rows.extend(rows)

    current_model_family = all_rows[-1]["modelFamily"] if all_rows else None
    summary_rows = [
        row for row in all_rows
        if current_model_family is not None and row["modelFamily"] == current_model_family
    ]
    summary_daily = [
        {**row, "includedInSummary": row["modelFamily"] == current_model_family}
        for row in daily
    ]
    excluded_dates = [
        row["date"] for row in summary_daily
        if not row["includedInSummary"]
    ]

    hourly: list[dict] = []
    for hour in range(24):
        hour_rows = [row for row in summary_rows if row["hour"] == hour]
        if not hour_rows:
            continue
        model_wins, tepco_wins, ties = _win_counts(hour_rows)
        hourly.append({
            "hour": hour,
            "samples": len(hour_rows),
            "modelMaeMw": _mean([row["modelAbsErrorMw"] for row in hour_rows]),
            "tepcoMaeMw": _mean([row["tepcoAbsErrorMw"] for row in hour_rows]),
            "modelWins": model_wins,
            "tepcoWins": tepco_wins,
            "ties": ties,
        })

    model_wins, tepco_wins, ties = _win_counts(summary_rows)
    model_win_rate = round(model_wins / len(summary_rows), 3) if summary_rows else None

    return {
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "generatedAt": generated_at,
        "windowDays": max_days,
        "modelScope": {
            "summaryModelFamily": current_model_family,
            "summaryModelNames": sorted({
                row["modelName"] for row in summary_rows
            }),
            "excludedDates": excluded_dates,
        },
        "summary": {
            "dates": sum(1 for row in summary_daily if row["includedInSummary"]),
            "hours": len(summary_rows),
            "modelMaeMw": _mean([row["modelAbsErrorMw"] for row in summary_rows]),
            "tepcoMaeMw": _mean([row["tepcoAbsErrorMw"] for row in summary_rows]),
            "modelWins": model_wins,
            "tepcoWins": tepco_wins,
            "ties": ties,
            "modelWinRate": model_win_rate,
        },
        "daily": summary_daily,
        "hourly": hourly,
    }
