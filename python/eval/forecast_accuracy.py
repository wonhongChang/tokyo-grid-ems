"""Build model-vs-TEPCO forecast accuracy reports from published JSON files."""
from __future__ import annotations

import json
import math
from pathlib import Path

_CLOSE_MAE_GAP_MW = 100.0
_CLOSE_WAPE_GAP_PCT = 0.2
_RMSE_RISK_GAP_MW = 300.0


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _win_counts(rows: list[dict]) -> tuple[int, int, int]:
    model_wins = sum(1 for row in rows if row["modelAbsErrorMw"] < row["tepcoAbsErrorMw"])
    tepco_wins = sum(1 for row in rows if row["tepcoAbsErrorMw"] < row["modelAbsErrorMw"])
    ties = len(rows) - model_wins - tepco_wins
    return model_wins, tepco_wins, ties


def _metrics(rows: list[dict], prefix: str) -> dict:
    abs_key = f"{prefix}AbsErrorMw"
    error_key = f"{prefix}ErrorMw"
    abs_errors = [float(row[abs_key]) for row in rows]
    signed_errors = [float(row[error_key]) for row in rows]
    actual_sum = sum(float(row["actualMw"]) for row in rows)
    if not abs_errors:
        return {
            "maeMw": None,
            "wapePct": None,
            "rmseMw": None,
            "maxErrorMw": None,
            "maxErrorHour": None,
        }

    max_error_row = max(rows, key=lambda row: float(row[abs_key]))
    return {
        "maeMw": _mean(abs_errors),
        "wapePct": round(sum(abs_errors) / actual_sum * 100, 2) if actual_sum > 0 else None,
        "rmseMw": round(math.sqrt(sum(error ** 2 for error in signed_errors) / len(signed_errors)), 1),
        "maxErrorMw": round(float(max_error_row[abs_key]), 1),
        "maxErrorHour": int(max_error_row["hour"]),
    }


def _verdict(model: dict, tepco: dict) -> str:
    model_mae_mw = model.get("maeMw")
    tepco_mae_mw = tepco.get("maeMw")
    model_wape_pct = model.get("wapePct")
    tepco_wape_pct = tepco.get("wapePct")
    model_rmse_mw = model.get("rmseMw")
    tepco_rmse_mw = tepco.get("rmseMw")
    if (
        model_mae_mw is None
        or tepco_mae_mw is None
        or model_wape_pct is None
        or tepco_wape_pct is None
    ):
        return "insufficient"
    gap_mw = model_mae_mw - tepco_mae_mw
    wape_gap_pct = model_wape_pct - tepco_wape_pct
    if abs(gap_mw) <= _CLOSE_MAE_GAP_MW and abs(wape_gap_pct) <= _CLOSE_WAPE_GAP_PCT:
        return "close"

    if gap_mw < 0 and wape_gap_pct < 0:
        if (
            model_rmse_mw is not None
            and tepco_rmse_mw is not None
            and model_rmse_mw - tepco_rmse_mw > _RMSE_RISK_GAP_MW
        ):
            return "mixed"
        return "model_better"

    if gap_mw > 0 and wape_gap_pct > 0:
        if (
            model_rmse_mw is not None
            and tepco_rmse_mw is not None
            and tepco_rmse_mw - model_rmse_mw > _RMSE_RISK_GAP_MW
        ):
            return "mixed"
        return "tepco_better"

    return "mixed"


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
        if actual_point.get("actualSource") == "tepco_forecast_fallback":
            continue
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
            "modelErrorMw": round(float(model_forecast_mw) - float(actual_mw), 1),
            "tepcoErrorMw": round(float(tepco_forecast_mw) - float(actual_mw), 1),
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
        model_metrics = _metrics(rows, "model")
        tepco_metrics = _metrics(rows, "tepco")
        model_mae_mw = model_metrics["maeMw"]
        tepco_mae_mw = tepco_metrics["maeMw"]
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
            "modelWapePct": model_metrics["wapePct"],
            "tepcoWapePct": tepco_metrics["wapePct"],
            "modelRmseMw": model_metrics["rmseMw"],
            "tepcoRmseMw": tepco_metrics["rmseMw"],
            "modelMaxErrorMw": model_metrics["maxErrorMw"],
            "tepcoMaxErrorMw": tepco_metrics["maxErrorMw"],
            "modelMaxErrorHour": model_metrics["maxErrorHour"],
            "tepcoMaxErrorHour": tepco_metrics["maxErrorHour"],
            "maeGapMw": mae_gap_mw,
            "wapeGapPct": (
                round(model_metrics["wapePct"] - tepco_metrics["wapePct"], 2)
                if model_metrics["wapePct"] is not None and tepco_metrics["wapePct"] is not None
                else None
            ),
            "verdict": _verdict(model_metrics, tepco_metrics),
            "modelWins": model_wins,
            "tepcoWins": tepco_wins,
            "ties": ties,
            "modelAdvantageHours": model_wins,
            "tepcoAdvantageHours": tepco_wins,
            "equalHours": ties,
            "modelAdvantageRate": round(model_wins / len(rows), 3) if rows else None,
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
        model_metrics = _metrics(hour_rows, "model")
        tepco_metrics = _metrics(hour_rows, "tepco")
        hourly.append({
            "hour": hour,
            "samples": len(hour_rows),
            "modelMaeMw": model_metrics["maeMw"],
            "tepcoMaeMw": tepco_metrics["maeMw"],
            "modelWapePct": model_metrics["wapePct"],
            "tepcoWapePct": tepco_metrics["wapePct"],
            "modelRmseMw": model_metrics["rmseMw"],
            "tepcoRmseMw": tepco_metrics["rmseMw"],
            "modelMaxErrorMw": model_metrics["maxErrorMw"],
            "tepcoMaxErrorMw": tepco_metrics["maxErrorMw"],
            "modelWins": model_wins,
            "tepcoWins": tepco_wins,
            "ties": ties,
            "modelAdvantageHours": model_wins,
            "tepcoAdvantageHours": tepco_wins,
            "equalHours": ties,
            "modelAdvantageRate": round(model_wins / len(hour_rows), 3) if hour_rows else None,
        })

    model_wins, tepco_wins, ties = _win_counts(summary_rows)
    model_win_rate = round(model_wins / len(summary_rows), 3) if summary_rows else None
    model_summary_metrics = _metrics(summary_rows, "model")
    tepco_summary_metrics = _metrics(summary_rows, "tepco")

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
            "modelMaeMw": model_summary_metrics["maeMw"],
            "tepcoMaeMw": tepco_summary_metrics["maeMw"],
            "modelWapePct": model_summary_metrics["wapePct"],
            "tepcoWapePct": tepco_summary_metrics["wapePct"],
            "modelRmseMw": model_summary_metrics["rmseMw"],
            "tepcoRmseMw": tepco_summary_metrics["rmseMw"],
            "modelMaxErrorMw": model_summary_metrics["maxErrorMw"],
            "tepcoMaxErrorMw": tepco_summary_metrics["maxErrorMw"],
            "modelMaxErrorHour": model_summary_metrics["maxErrorHour"],
            "tepcoMaxErrorHour": tepco_summary_metrics["maxErrorHour"],
            "verdict": _verdict(model_summary_metrics, tepco_summary_metrics),
            "modelWins": model_wins,
            "tepcoWins": tepco_wins,
            "ties": ties,
            "modelWinRate": model_win_rate,
            "modelAdvantageHours": model_wins,
            "tepcoAdvantageHours": tepco_wins,
            "equalHours": ties,
            "modelAdvantageRate": model_win_rate,
        },
        "daily": summary_daily,
        "hourly": hourly,
    }
