"""Evaluate fixed-vintage TEPCO AREA forecasts without using them as features."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


AREA_ROWS_PER_DAY = 48


def read_area_file(path: Path, prefix: str) -> pd.DataFrame:
    """Convert one 48-slot AREA CSV from half-hour kWh to hourly average MW."""
    frame = pd.read_csv(path, encoding="cp932", skiprows=2)
    if len(frame) != AREA_ROWS_PER_DAY or frame.shape[1] < 7:
        raise ValueError(f"Unexpected TEPCO AREA file layout: {path}")

    slots = pd.to_numeric(frame.iloc[:, 1], errors="raise").astype(int)
    if set(slots) != set(range(1, AREA_ROWS_PER_DAY + 1)):
        raise ValueError(f"Unexpected TEPCO AREA time slots: {path}")
    target_dates = pd.to_datetime(
        frame.iloc[:, 0].astype(str),
        format="%Y%m%d",
        errors="raise",
    )
    if target_dates.dt.date.nunique() != 1:
        raise ValueError(f"TEPCO AREA file contains multiple dates: {path}")

    half_hour = pd.DataFrame({
        "date": target_dates.dt.date,
        "hour": ((slots - 1) // 2).astype(int),
        "half": ((slots - 1) % 2).astype(int),
        "demandMw": pd.to_numeric(frame.iloc[:, 4], errors="coerce") * 2 / 1000,
        "generationMw": (
            pd.to_numeric(frame.iloc[:, 5], errors="coerce") * 2 / 1000
        ),
        "renewableMw": (
            pd.to_numeric(frame.iloc[:, 6], errors="coerce") * 2 / 1000
        ),
    })
    records: list[dict] = []
    for (target, hour), rows in half_hour.groupby(["date", "hour"]):
        ordered = rows.sort_values("half")
        records.append({
            "date": target,
            "hour": int(hour),
            f"{prefix}DemandMw": float(ordered["demandMw"].mean()),
            f"{prefix}GenerationMw": float(ordered["generationMw"].mean()),
            f"{prefix}RenewableMw": float(ordered["renewableMw"].mean()),
            f"{prefix}DemandIntraHourDeltaMw": float(
                ordered["demandMw"].iloc[1] - ordered["demandMw"].iloc[0]
            ),
        })
    return pd.DataFrame.from_records(records)


def load_area_rows(area_dirs: list[Path]) -> pd.DataFrame:
    actual_parts: list[pd.DataFrame] = []
    forecast_parts: list[pd.DataFrame] = []
    for directory in area_dirs:
        actual_parts.extend(
            read_area_file(path, "actual")
            for path in sorted(directory.glob("AREA_JISEKI_*.csv"))
        )
        forecast_parts.extend(
            read_area_file(path, "forecast")
            for path in sorted(directory.glob("AREA_YOSOKU_*.csv"))
        )
    if not actual_parts or not forecast_parts:
        raise FileNotFoundError(
            "Need AREA_JISEKI_*.csv and AREA_YOSOKU_*.csv files."
        )
    actual = pd.concat(actual_parts, ignore_index=True)
    forecast = pd.concat(forecast_parts, ignore_index=True)
    return actual.merge(forecast, on=["date", "hour"], how="inner")


def load_served_forecasts(data_dir: Path) -> pd.DataFrame:
    records: list[dict] = []
    for path in sorted((data_dir / "forecast").glob("*.json")):
        try:
            target = pd.Timestamp(path.stem).date()
        except ValueError:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        model_name = str((payload.get("model") or {}).get("name") or "")
        if not model_name.startswith("lgbm_quantile"):
            continue
        for row in payload.get("series", []):
            value = row.get("forecastMw")
            if value is None:
                continue
            records.append({
                "date": target,
                "hour": int(pd.Timestamp(row["ts"]).hour),
                "servedForecastMw": float(value),
            })
    return pd.DataFrame.from_records(records)


def metric(actual: pd.Series, predicted: pd.Series) -> dict:
    valid = actual.notna() & predicted.notna()
    if not valid.any():
        return {
            "hours": 0,
            "maeMw": None,
            "meanBiasMw": None,
            "wapePct": None,
            "rmseMw": None,
            "maxErrorMw": None,
        }
    actual_values = actual.loc[valid].to_numpy(dtype=float)
    predicted_values = predicted.loc[valid].to_numpy(dtype=float)
    errors = predicted_values - actual_values
    denominator = float(np.abs(actual_values).sum())
    return {
        "hours": int(valid.sum()),
        "maeMw": round(float(np.mean(np.abs(errors))), 1),
        "meanBiasMw": round(float(np.mean(errors)), 1),
        "wapePct": round(float(np.abs(errors).sum() / denominator * 100), 3)
        if denominator > 0
        else None,
        "rmseMw": round(float(np.sqrt(np.mean(np.square(errors)))), 1),
        "maxErrorMw": round(float(np.max(np.abs(errors))), 1),
    }


def build_report(area_dirs: list[Path], served_dir: Path | None = None) -> dict:
    rows = load_area_rows(area_dirs)
    if served_dir is not None:
        served = load_served_forecasts(served_dir)
        if not served.empty:
            rows = rows.merge(served, on=["date", "hour"], how="left")
    if "servedForecastMw" not in rows:
        rows["servedForecastMw"] = np.nan

    daytime = rows[rows["hour"].between(9, 18)]
    matched = rows[rows["servedForecastMw"].notna()]
    matched_daytime = matched[matched["hour"].between(9, 18)]
    report = {
        "schemaVersion": "1.0.0",
        "benchmark": "tepco_fixed_previous_evening_area_forecast",
        "modelInputPolicy": "benchmark_only_never_used_as_forecast_feature",
        "period": {
            "start": min(rows["date"]).isoformat(),
            "end": max(rows["date"]).isoformat(),
            "days": int(rows["date"].nunique()),
            "hours": int(len(rows)),
        },
        "tepcoAllAreaHours": metric(
            rows["actualDemandMw"],
            rows["forecastDemandMw"],
        ),
        "tepcoDaytime09To18AllAreaHours": metric(
            daytime["actualDemandMw"],
            daytime["forecastDemandMw"],
        ),
        "matchedServedHours": {
            "tepcoFixedDayAhead": metric(
                matched["actualDemandMw"],
                matched["forecastDemandMw"],
            ),
            "servedModel": metric(
                matched["actualDemandMw"],
                matched["servedForecastMw"],
            ),
        },
        "matchedServedDaytime09To18": {
            "tepcoFixedDayAhead": metric(
                matched_daytime["actualDemandMw"],
                matched_daytime["forecastDemandMw"],
            ),
            "servedModel": metric(
                matched_daytime["actualDemandMw"],
                matched_daytime["servedForecastMw"],
            ),
        },
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--area-dir", type=Path, action="append", required=True)
    parser.add_argument("--served-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = build_report(args.area_dir, args.served_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(args.output)


if __name__ == "__main__":
    main()
