"""Fixed learned candidate specifications; native LightGBM serialization."""
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np

from . import CONTRACT
from .evidence import FEATURES, encode, frame, implementation_sha, sha

PARAMS = dict(objective="regression_l1", n_estimators=240, learning_rate=0.035,
              num_leaves=12, min_child_samples=45, reg_lambda=10.0,
              colsample_bytree=1.0, subsample=1.0, random_state=20261003,
              deterministic=True, force_col_wise=True, n_jobs=2, verbosity=-1)
CANDIDATES = {
    "L1": {"basis": "raw", "target": "direct_error", "description": "Raw + learned absolute error"},
    "L2": {"basis": "champion", "target": "remaining_error", "description": "Recorded post + learned remaining error"},
    "L3": {"basis": "pre", "target": "anchored_error_change", "description": "Pre + latest raw residual + learned residual change; intraday heuristics bypassed"},
}


def anchor(record, spec):
    if spec["target"] != "anchored_error_change":
        return 0.0
    v = record["features"].get("raw_residual_1")
    return float(v) if v is not None else 0.0


def train(records, name):
    if name not in CANDIDATES or not records:
        raise ValueError("Unknown candidate or empty training population")
    if any(r["actual"] is None or r["actual_state"] != "finalized" for r in records):
        raise ValueError("Only finalized labels may train a candidate")
    spec = CANDIDATES[name]
    targets = np.array([r["actual"] - r[spec["basis"]] - anchor(r, spec) for r in records])
    # A frequently captured hour must not outweigh an infrequently captured hour.
    counts = {}
    for r in records:
        k = (r["date"], r["hour"]); counts[k] = counts.get(k, 0) + 1
    weights = np.array([1 / counts[(r["date"], r["hour"])] for r in records])
    model = lgb.LGBMRegressor(**PARAMS)
    model.fit(frame(records), targets, sample_weight=weights)
    return model.booster_


def predict(booster, records, spec):
    if not records:
        return []
    delta = booster.predict(frame(records), num_threads=2)
    return [float(r[spec["basis"]] + anchor(r, spec) + d) for r, d in zip(records, delta)]


def save(booster, directory, name, training_records, input_sha):
    p = Path(directory)
    if p.exists() and any(p.iterdir()):
        raise ValueError("Model output already exists")
    p.mkdir(parents=True, exist_ok=True)
    content = booster.model_to_string().encode()
    (p / "model.txt").write_bytes(content)
    identity = {"contract": CONTRACT, "candidate": name, "spec": CANDIDATES[name],
                "features": list(FEATURES), "params": PARAMS, "modelSha256": sha(content),
                "inputManifestSha256": input_sha, "trainingStart": min(r['date'] for r in training_records),
                "trainingEnd": max(r['date'] for r in training_records), "trainingRows": len(training_records),
                "implementationSha256": implementation_sha(__file__),
                "featureImplementationSha256": implementation_sha(Path(__file__).with_name('evidence.py')),
                "lightgbmVersion": lgb.__version__, "productionPromotion": False}
    (p / "identity.json").write_bytes(encode(identity))
    return identity


def load(directory, identity_sha):
    p = Path(directory)
    b = (p / "identity.json").read_bytes()
    if sha(b) != identity_sha:
        raise ValueError("Model identity hash mismatch")
    identity = json.loads(b)
    if identity['contract'] != CONTRACT or identity['features'] != list(FEATURES):
        raise ValueError("Feature contract mismatch")
    if identity['candidate'] not in CANDIDATES or identity['spec'] != CANDIDATES[identity['candidate']]:
        raise ValueError("Candidate contract mismatch")
    if identity['featureImplementationSha256'] != implementation_sha(Path(__file__).with_name('evidence.py')):
        raise ValueError("Feature implementation changed")
    if identity['implementationSha256'] != implementation_sha(__file__):
        raise ValueError("Model implementation changed")
    content = (p / "model.txt").read_bytes()
    if sha(content) != identity['modelSha256']:
        raise ValueError("Model artifact hash mismatch")
    return lgb.Booster(model_str=content.decode()), identity
