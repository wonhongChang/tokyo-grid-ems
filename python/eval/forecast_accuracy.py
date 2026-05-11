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


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _comparable_rows_for_date(public_dir: Path, date_iso: str) -> list[dict]:
    actual_path = public_dir / "actual" / f"{date_iso}.json"
    forecast_path = public_dir / "forecast" / f"{date_iso}.json"
    if not actual_path.exists() or not forecast_path.exists():
        return []

    actual = _load_json(actual_path)
    forecast = _load_json(forecast_path)
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
        model_wins, tepco_wins, ties = _win_counts(rows)
        daily.append({
            "date": date_iso,
            "hours": len(rows),
            "modelMaeMw": _mean([row["modelAbsErrorMw"] for row in rows]),
            "tepcoMaeMw": _mean([row["tepcoAbsErrorMw"] for row in rows]),
            "modelWins": model_wins,
            "tepcoWins": tepco_wins,
            "ties": ties,
        })
        all_rows.extend(rows)

    hourly: list[dict] = []
    for hour in range(24):
        hour_rows = [row for row in all_rows if row["hour"] == hour]
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

    model_wins, tepco_wins, ties = _win_counts(all_rows)
    model_win_rate = round(model_wins / len(all_rows), 3) if all_rows else None

    return {
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "generatedAt": generated_at,
        "windowDays": max_days,
        "summary": {
            "dates": len(daily),
            "hours": len(all_rows),
            "modelMaeMw": _mean([row["modelAbsErrorMw"] for row in all_rows]),
            "tepcoMaeMw": _mean([row["tepcoAbsErrorMw"] for row in all_rows]),
            "modelWins": model_wins,
            "tepcoWins": tepco_wins,
            "ties": ties,
            "modelWinRate": model_win_rate,
        },
        "daily": daily,
        "hourly": hourly,
    }
