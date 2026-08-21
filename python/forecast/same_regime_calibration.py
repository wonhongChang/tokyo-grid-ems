"""Conservative day-level calibration from finalized same-regime residuals."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from python.forecast.baseline import HourlyForecast
from python.forecast.feature_builder import _is_nonworking


_FALLBACK_SOURCE = "tepco_forecast_fallback"


@dataclass(frozen=True)
class SameRegimeCalibrationResult:
    forecasts: list[HourlyForecast]
    adjustment_mw: float
    history_dates: tuple[str, ...]
    applied: bool


class SameRegimeDayLevelCalibrator:
    """Apply a bounded prior-day scale correction without same-day leakage."""

    def __init__(self, config: dict, out_dir: Path) -> None:
        forecast_config = config.get("forecast", {})
        calibration = forecast_config.get(
            "same_regime_day_level_calibration",
            {},
        )
        self.enabled = bool(calibration.get("enabled", False))
        self.min_history_days = max(1, int(calibration.get("min_history_days", 3)))
        self.history_window_days = max(
            self.min_history_days,
            int(calibration.get("history_window_days", 3)),
        )
        self.shrinkage = min(
            1.0,
            max(0.0, float(calibration.get("shrinkage", 0.25))),
        )
        self.max_abs_adjustment_mw = max(
            0.0,
            float(calibration.get("max_abs_adjustment_mw", 1000.0)),
        )
        self.model_contract = str(forecast_config.get("model_contract", ""))
        self.out_dir = out_dir
        self.state_path = out_dir / str(
            calibration.get(
                "state_path",
                "metrics/same_regime_day_level_calibration.json",
            )
        )

    def _model_artifact_sha256(self) -> str | None:
        metadata_path = self.out_dir / ".lgbm_model_meta.json"
        if not metadata_path.exists():
            return None
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        value = payload.get("artifactSha256")
        return str(value) if value else None

    def _load_state(self) -> dict | None:
        if not self.state_path.exists():
            return None
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        artifact_hash = self._model_artifact_sha256()
        if (
            payload.get("modelContract") != self.model_contract
            or not artifact_hash
            or payload.get("artifactSha256") != artifact_hash
        ):
            return None
        return payload

    def _write_state(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _final_actuals(self, target_date: date) -> dict[int, float] | None:
        path = self.out_dir / "actual" / f"{target_date.isoformat()}.json"
        if not path.exists():
            return None
        try:
            series = json.loads(path.read_text(encoding="utf-8")).get("series", [])
        except (OSError, json.JSONDecodeError):
            return None
        values: dict[int, float] = {}
        for point in series:
            if (
                point.get("actualMw") is None
                or point.get("actualSource") == _FALLBACK_SOURCE
            ):
                continue
            try:
                hour = pd.Timestamp(point["ts"]).hour
                values[int(hour)] = float(point["actualMw"])
            except (KeyError, TypeError, ValueError):
                return None
        return values if set(values) == set(range(24)) else None

    def _origin_raw_forecast(self, target_date: date) -> tuple[dict[int, float], str] | None:
        index_path = (
            self.out_dir
            / "forecast_snapshots"
            / target_date.isoformat()
            / "index.json"
        )
        if not index_path.exists():
            return None
        try:
            snapshots = json.loads(index_path.read_text(encoding="utf-8")).get(
                "snapshots",
                [],
            )
        except (OSError, json.JSONDecodeError):
            return None
        artifact_hash = self._model_artifact_sha256()
        for entry in sorted(snapshots, key=lambda item: item.get("generatedAt", "")):
            relative_path = entry.get("path")
            if not relative_path:
                continue
            path = self.out_dir / relative_path
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            model = payload.get("model") or {}
            if (
                model.get("contract") != self.model_contract
                or model.get("artifactSha256") != artifact_hash
            ):
                continue
            values: dict[int, float] = {}
            for row in (payload.get("forecastBuild") or {}).get("hourly", []):
                raw_value = (row.get("forecastMwByStage") or {}).get("raw_lgbm")
                if raw_value is None:
                    continue
                try:
                    values[int(row["hour"])] = float(raw_value)
                except (KeyError, TypeError, ValueError):
                    values = {}
                    break
            if set(values) == set(range(24)):
                return values, str(payload.get("generatedAt") or "")
        return None

    def refresh(self, target_date: date) -> dict | None:
        state = self._load_state()
        if state is None:
            return None
        entries = list(state.get("entries") or [])
        known_dates = {str(entry.get("date")) for entry in entries}
        valid_from = date.fromisoformat(str(state["validFromDate"]))
        changed = False
        current = valid_from
        while current < target_date:
            current_iso = current.isoformat()
            if current_iso not in known_dates:
                actuals = self._final_actuals(current)
                origin = self._origin_raw_forecast(current)
                if actuals is not None and origin is not None:
                    raw_forecast, generated_at = origin
                    residual = float(np.mean([
                        actuals[hour] - raw_forecast[hour]
                        for hour in range(24)
                    ]))
                    entries.append({
                        "date": current_iso,
                        "isNonBusinessDay": bool(_is_nonworking(current)),
                        "meanResidualMw": round(residual, 1),
                        "originGeneratedAt": generated_at,
                    })
                    known_dates.add(current_iso)
                    changed = True
            current += timedelta(days=1)
        entries.sort(key=lambda entry: entry["date"])
        state["entries"] = entries[-60:]
        if changed:
            state["updatedAt"] = pd.Timestamp.now(
                tz="Asia/Tokyo"
            ).isoformat(timespec="seconds")
            self._write_state(state)
        return state

    @staticmethod
    def _shift(forecasts: list[HourlyForecast], adjustment: float) -> list[HourlyForecast]:
        return [
            HourlyForecast(
                ts=point.ts,
                forecast_mw=round(point.forecast_mw + adjustment, 1),
                p95_lower_mw=round(point.p95_lower_mw + adjustment, 1),
                p95_upper_mw=round(point.p95_upper_mw + adjustment, 1),
                p99_lower_mw=round(point.p99_lower_mw + adjustment, 1),
                p99_upper_mw=round(point.p99_upper_mw + adjustment, 1),
            )
            for point in forecasts
        ]

    def apply(
        self,
        forecasts: list[HourlyForecast],
        target_date: date,
        inference_features: pd.DataFrame,
    ) -> SameRegimeCalibrationResult:
        if not self.enabled or not forecasts or inference_features.empty:
            return SameRegimeCalibrationResult(forecasts, 0.0, (), False)
        state = self.refresh(target_date)
        if state is None:
            return SameRegimeCalibrationResult(forecasts, 0.0, (), False)
        is_non_business = bool(
            float(inference_features.iloc[0]["is_non_business_day"]) != 0.0
        )
        matching = [
            entry
            for entry in state.get("entries", [])
            if bool(entry.get("isNonBusinessDay")) == is_non_business
            and str(entry.get("date")) < target_date.isoformat()
            and np.isfinite(float(entry.get("meanResidualMw", np.nan)))
        ]
        matching.sort(key=lambda entry: entry["date"])
        history = matching[-self.history_window_days:]
        if len(history) < self.min_history_days:
            return SameRegimeCalibrationResult(
                forecasts,
                0.0,
                tuple(entry["date"] for entry in history),
                False,
            )
        adjustment = float(np.clip(
            self.shrinkage * np.median([
                float(entry["meanResidualMw"])
                for entry in history
            ]),
            -self.max_abs_adjustment_mw,
            self.max_abs_adjustment_mw,
        ))
        if abs(adjustment) < 0.05:
            return SameRegimeCalibrationResult(
                forecasts,
                0.0,
                tuple(entry["date"] for entry in history),
                False,
            )
        return SameRegimeCalibrationResult(
            self._shift(forecasts, adjustment),
            adjustment,
            tuple(entry["date"] for entry in history),
            True,
        )
