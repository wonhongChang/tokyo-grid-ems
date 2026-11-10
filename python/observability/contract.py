"""The complete vocabulary allowed on the diagnostic wire."""
import re

OPERATIONS = frozenset("""
etl.batch etl.intraday etl.fetch etl.fetch_historical etl.local_run data.restore restore.probe restore.fetch source.fetch input.inventory input.parse input.quality
weather.fetch weather.enrich cache.prepare forecast.issue features.build model.load model.predict
forecast.calibrate forecast.intraday forecast.publish publication.freeze snapshot.retain
origin.record publish.validate publish.request git.publish workflow.dispatch public.observe
""".split())
OUTCOMES = frozenset("ok failed skipped degraded unknown".split())
SERVICES = frozenset(("tgems-etl", "tgems-host", "tgems-public", "tgems-fixture"))
PARENT = re.compile(r"00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})\Z")


def valid_parent(value):
    m = PARENT.fullmatch(value or "")
    return bool(m and int(m[1], 16) and int(m[2], 16))


def error_kind(exc):
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, PermissionError):
        return "permission"
    if isinstance(exc, OSError):
        return "io"
    if isinstance(exc, (TypeError, ValueError, KeyError)):
        return "invalid"
    return "execution"
