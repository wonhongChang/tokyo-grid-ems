"""Manual PS/host parent: propagate into one child CLI, preserving its exit status."""
import os
from pathlib import Path
import subprocess
import sys

from .runner import COMMANDS
from .runtime import Runtime


def main():
    args=sys.argv[1:]
    docker=args[:1]==["--docker"]
    if docker:args=args[1:]
    if not args or args[0] not in COMMANDS:raise SystemExit("Unknown observed CLI")
    if docker and args[0] not in ("batch","fetch"):
        raise SystemExit("Only manual ETL commands belong in the ETL container")
    rt=Runtime("tgems-host")
    try:
        with rt.stage("etl.local_run") as status:
            env={**os.environ,**rt.carrier()}
            if docker:
                cmd=["docker","compose","-p","tgems-observe-cli","-f","docker-compose.yml",
                     "-f","ops/observability/manual-etl.yml","run","--rm","--no-deps","--no-TTY"]
                for key in ("TGEMS_TRACEPARENT","TGEMS_OTEL_CORRELATION","TGEMS_OTEL_ENABLED","TGEMS_OTEL_FIXTURE"):
                    if key in env:cmd+=["-e",key]
                cmd+=["etl","python","-m","python.observability.runner",*args]
            else:
                cmd=[sys.executable,"-m","python.observability.runner",*args]
            rc=subprocess.run(cmd,cwd=Path(__file__).resolve().parents[2],env=env,
                              stdout=sys.stdout, stderr=sys.stderr).returncode
            if rc:status.outcome="failed"
        return rc
    finally:
        rt.close()


if __name__=="__main__":
    code=main()
    if os.name=="posix" and code<0:
        import signal
        if -code not in (signal.SIGKILL, signal.SIGSTOP):
            signal.signal(-code, signal.SIG_DFL)
        os.kill(os.getpid(), -code)
    sys.exit(code)
