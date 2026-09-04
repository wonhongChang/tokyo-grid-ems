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
    state_status: str = "not_evaluated"
    latest_residual_date: str | None = None
    state_lag_days: int | None = None

    def to_metadata(self) -> dict:
        return {
            "applied": self.applied,
            "adjustmentMw": round(float(self.adjustment_mw), 1),
            "historyDates": list(self.history_dates),
            "stateStatus": self.state_status,
            "latestResidualDate": self.latest_residual_date,
            "stateLagDays": self.state_lag_days,
        }


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
        # The previous finalized day is unavailable before the morning monthly
        # CSV refresh, so one publication-day gap is expected. A larger gap
        # means the rolling state is no longer trustworthy for serving.
        serving_policy = config.get("serving_calibration", {}).get(
            "same_regime_day_level",
            {},
        )
        self.max_state_lag_days = max(
            1,
            int(
                serving_policy.get(
                    "max_state_lag_days",
                    calibration.get("max_state_lag_days", 2),
                )
            ),
        )
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

    @staticmethod
    def _raw_forecast_values(payload: dict) -> dict[int, float] | None:
        forecast_build = payload.get("forecastBuild") or {}
        rows = forecast_build.get("series")
        if not isinstance(rows, list):
            rows = forecast_build.get("hourly", [])
        values: dict[int, float] = {}
        for row in rows:
            raw_value = (row.get("forecastMwByStage") or {}).get("raw_lgbm")
            if raw_value is None:
                continue
            try:
                values[int(row["hour"])] = float(raw_value)
            except (KeyError, TypeError, ValueError):
                return None
        return values if set(values) == set(range(24)) else None

    @staticmethod
    def _is_day_ahead_origin(generated_at: str, target_date: date) -> bool:
        try:
            return pd.Timestamp(generated_at).date() < target_date
        except (TypeError, ValueError):
            return False

    def _valid_origin_payload(
        self,
        payload: dict,
        target_date: date,
        artifact_hash: str,
    ) -> tuple[dict[int, float], str] | None:
        model = payload.get("model") or {}
        generated_at = str(payload.get("generatedAt") or "")
        if (
            model.get("contract") != self.model_contract
            or model.get("artifactSha256") != artifact_hash
            or not self._is_day_ahead_origin(generated_at, target_date)
        ):
            return None
        values = self._raw_forecast_values(payload)
        return (values, generated_at) if values is not None else None

    def _origin_raw_forecast(
        self,
        target_date: date,
    ) -> tuple[dict[int, float], str, str] | None:
        artifact_hash = self._model_artifact_sha256()
        if not artifact_hash:
            return None

        immutable_path = (
            self.out_dir
            / "forecast_origins"
            / target_date.isoformat()
            / f"{artifact_hash}.json"
        )
        if immutable_path.exists():
            try:
                payload = json.loads(immutable_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict):
                origin = self._valid_origin_payload(
                    payload,
                    target_date,
                    artifact_hash,
                )
                if origin is not None:
                    values, generated_at = origin
                    return values, generated_at, "immutable_day_ahead_origin"

        # Backward-compatible migration path. Only a retained snapshot captured
        # before the target date is eligible; same-day recalculations are never
        # relabeled as a fixed day-ahead origin.
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
        for entry in sorted(snapshots, key=lambda item: item.get("generatedAt", "")):
            relative_path = entry.get("path")
            if not relative_path:
                continue
            path = self.out_dir / relative_path
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            origin = self._valid_origin_payload(
                payload,
                target_date,
                artifact_hash,
            )
            if origin is not None:
                values, generated_at = origin
                return values, generated_at, "legacy_retained_day_ahead_snapshot"
        return None

    @staticmethod
    def _latest_residual_date(state: dict, target_date: date) -> date | None:
        candidates: list[date] = []
        for entry in state.get("entries") or []:
            try:
                entry_date = date.fromisoformat(str(entry.get("date")))
            except ValueError:
                continue
            if entry_date < target_date:
                candidates.append(entry_date)
        return max(candidates) if candidates else None

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
                    raw_forecast, generated_at, origin_source = origin
                    residual = float(np.mean([
                        actuals[hour] - raw_forecast[hour]
                        for hour in range(24)
                    ]))
                    entries.append({
                        "date": current_iso,
                        "isNonBusinessDay": bool(_is_nonworking(current)),
                        "meanResidualMw": round(residual, 1),
                        "originGeneratedAt": generated_at,
                        "source": origin_source,
                    })
                    known_dates.add(current_iso)
                    changed = True
            current += timedelta(days=1)
        entries.sort(key=lambda entry: entry["date"])
        state["entries"] = entries[-60:]
        latest_residual_date = self._latest_residual_date(state, target_date)
        latest_iso = (
            latest_residual_date.isoformat()
            if latest_residual_date is not None
            else None
        )
        if state.get("latestResidualDate") != latest_iso:
            state["latestResidualDate"] = latest_iso
            changed = True
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
            return SameRegimeCalibrationResult(
                forecasts,
                0.0,
                (),
                False,
                "disabled_or_unavailable",
            )
        state = self.refresh(target_date)
        if state is None:
            return SameRegimeCalibrationResult(
                forecasts,
                0.0,
                (),
                False,
                "missing_or_incompatible_state",
            )
        latest_residual_date = self._latest_residual_date(state, target_date)
        state_lag_days = (
            (target_date - latest_residual_date).days
            if latest_residual_date is not None
            else None
        )
        latest_residual_iso = (
            latest_residual_date.isoformat()
            if latest_residual_date is not None
            else None
        )
        if state_lag_days is None or state_lag_days > self.max_state_lag_days:
            return SameRegimeCalibrationResult(
                forecasts,
                0.0,
                (),
                False,
                "stale_state",
                latest_residual_iso,
                state_lag_days,
            )
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
                "insufficient_same_regime_history",
                latest_residual_iso,
                state_lag_days,
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
                "no_material_adjustment",
                latest_residual_iso,
                state_lag_days,
            )
        return SameRegimeCalibrationResult(
            self._shift(forecasts, adjustment),
            adjustment,
            tuple(entry["date"] for entry in history),
            True,
            "fresh",
            latest_residual_iso,
            state_lag_days,
        )
