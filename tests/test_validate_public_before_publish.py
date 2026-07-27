"""Tests for the final public-artifact publish gate."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.validate_public_before_publish import _load_json


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_load_json_rejects_nonfinite_numbers(tmp_path: Path, token: str):
    path = tmp_path / "payload.json"
    path.write_text(f'{{"value": {token}}}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="non-finite"):
        _load_json(path)
