import json
from pathlib import Path

import pytest

from python.eval.tepco_area_benchmark import build_report, read_area_file


def _write_area_file(path: Path, demand_offset: int) -> None:
    rows = [
        "updated_date,updated_time,target_date",
        "20260802,00:05:00,20260801",
        "date,slot,from,to,demand,generation,renewable",
    ]
    for slot in range(1, 49):
        hour = (slot - 1) // 2
        half = (slot - 1) % 2
        demand = 10_000_000 + demand_offset + slot * 1000
        rows.append(
            f"20260801,{slot},{hour}:{half * 30:02d},"
            f"{hour + (half + 1) // 2}:{((half + 1) % 2) * 30:02d},"
            f"{demand},9000000,100000"
        )
    path.write_text("\n".join(rows) + "\n", encoding="cp932")


def test_read_area_file_converts_half_hour_energy_to_hourly_mw(tmp_path):
    path = tmp_path / "AREA_JISEKI_20260801.csv"
    _write_area_file(path, 0)

    result = read_area_file(path, "actual")

    assert len(result) == 24
    assert result.iloc[0]["actualDemandMw"] == pytest.approx(20_003.0)
    assert result.iloc[0]["actualDemandIntraHourDeltaMw"] == pytest.approx(2.0)


def test_build_report_compares_fixed_forecast_and_optional_served_model(tmp_path):
    area_dir = tmp_path / "area"
    area_dir.mkdir()
    _write_area_file(area_dir / "AREA_JISEKI_20260801.csv", 0)
    _write_area_file(area_dir / "AREA_YOSOKU_20260801.csv", 100_000)
    served_dir = tmp_path / "served"
    (served_dir / "forecast").mkdir(parents=True)
    series = [
        {
            "ts": f"2026-08-01T{hour:02d}:00:00+09:00",
            "forecastMw": 20_026.0 + hour * 4.0,
        }
        for hour in range(24)
    ]
    (served_dir / "forecast" / "2026-08-01.json").write_text(
        json.dumps({"model": {"name": "lgbm_quantile_v14"}, "series": series}),
        encoding="utf-8",
    )

    report = build_report([area_dir], served_dir)

    assert report["modelInputPolicy"] == (
        "benchmark_only_never_used_as_forecast_feature"
    )
    assert report["tepcoAllAreaHours"]["maeMw"] == 200.0
    assert report["matchedServedHours"]["tepcoFixedDayAhead"]["maeMw"] == 200.0
    assert report["matchedServedHours"]["servedModel"]["maeMw"] == 23.0
