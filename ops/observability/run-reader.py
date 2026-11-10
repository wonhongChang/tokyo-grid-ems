"""Windows scheduled entry point. This process owns no ETL schedules or inputs."""
import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import sys


def limit_process():
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    class Basic(ctypes.Structure):
        _fields_=[("process_time",ctypes.c_int64),("job_time",ctypes.c_int64),("flags",w.DWORD),
                  ("min_ws",ctypes.c_size_t),("max_ws",ctypes.c_size_t),("active",w.DWORD),
                  ("affinity",ctypes.c_size_t),("priority",w.DWORD),("scheduling",w.DWORD)]
    class Extended(ctypes.Structure):
        _fields_=[("basic",Basic),("io",ctypes.c_uint64*6),("process_memory",ctypes.c_size_t),
                  ("job_memory",ctypes.c_size_t),("peak_process",ctypes.c_size_t),("peak_job",ctypes.c_size_t)]
    kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR];kernel.CreateJobObjectW.restype=w.HANDLE
    kernel.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
    kernel.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]
    kernel.CloseHandle.argtypes=[w.HANDLE]
    job=kernel.CreateJobObjectW(None,None)
    if not job:raise ctypes.WinError(ctypes.get_last_error())
    limits=Extended();limits.basic.flags=0x100;limits.process_memory=256*1024*1024
    rate=(w.DWORD*2)(0x1|0x4,1000)  # enabled, hard cap, 10% of system CPU
    for info,value in [(9,limits),(15,rate)]:
        if not kernel.SetInformationJobObject(job,info,ctypes.byref(value),ctypes.sizeof(value)):
            raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.AssignProcessToJobObject(job,w.HANDLE(-1)):
        raise ctypes.WinError(ctypes.get_last_error())
    return kernel,job


if __name__=="__main__":
    if os.name!="nt" or not sys.flags.isolated or not sys.dont_write_bytecode:
        raise SystemExit("Use the dedicated isolated Windows reader interpreter (-I -B)")
    # Only the child environment is narrowed; no user, system or ETL setting is written.
    for name in tuple(os.environ):
        if name.upper().startswith(("TGEMS_","OTEL_","OPENAI_","TOKYO_GRID_EMS_","GITHUB_","GH_","TYPESAFE_")):
            os.environ.pop(name,None)
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    from python.observability.reader_control import ManagedReader
    from python.observability.public import main
    kernel,job=limit_process()
    try:
        main(["--live-public","--watch"],managed=ManagedReader())
    finally:
        kernel.CloseHandle(job)
