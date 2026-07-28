"""Local subprocess proof for the Telegram-first runtime topology."""

from __future__ import annotations

import json
import os
import queue
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TextIO

try:  # Supports both direct execution from tools/ and package imports in tests.
    from telegram_first_security_context import CONTEXT_ENV, ROLE_ENV, emit_event
except ModuleNotFoundError:
    from tools.telegram_first_security_context import CONTEXT_ENV, ROLE_ENV, emit_event


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIRED_TASKS = {
    "core.tasks.generate_mini_report",
    "core.tasks.process_report_generation_job",
    "core.tasks.deliver_full_report",
}
WINDOWS_JOB_LAUNCHER = (
    "import subprocess, sys; "
    "ready = sys.stdin.readline().strip(); "
    "raise_code = subprocess.call(sys.argv[1:]) if ready == 'start' else 125; "
    "raise SystemExit(raise_code)"
)


@dataclass
class ManagedProcess:
    name: str
    process: subprocess.Popen[str]
    output: queue.Queue[str]
    lines: list[str]
    job_handle: int | None = None
    capture_handles: tuple[TextIO, ...] = ()


def _reader(stream: TextIO, output: queue.Queue[str], capture: TextIO | None = None) -> None:
    for line in iter(stream.readline, ""):
        if capture is not None:
            capture.write(line)
            capture.flush()
        output.put(line)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _create_windows_job(process: subprocess.Popen[str]) -> int:
    import ctypes
    from ctypes import wintypes

    class JobObjectBasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JobObjectExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JobObjectBasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    job_handle = kernel32.CreateJobObjectW(None, None)
    if not job_handle:
        raise ctypes.WinError(ctypes.get_last_error())
    information = JobObjectExtendedLimitInformation()
    information.BasicLimitInformation.LimitFlags = 0x00002000
    try:
        if not kernel32.SetInformationJobObject(
            job_handle,
            9,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        process_handle = wintypes.HANDLE(int(process._handle))
        if not kernel32.AssignProcessToJobObject(job_handle, process_handle):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(job_handle)
    except Exception:
        kernel32.CloseHandle(job_handle)
        raise


def _close_windows_job(job_handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = wintypes.HANDLE(job_handle)
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    if not kernel32.TerminateJobObject(handle, 1):
        error = ctypes.WinError(ctypes.get_last_error())
        kernel32.CloseHandle(handle)
        raise error
    if not kernel32.CloseHandle(handle):
        raise ctypes.WinError(ctypes.get_last_error())


def _start(name: str, args: list[str], env: dict[str, str]) -> ManagedProcess:
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process_args = args
    if os.name == "nt":
        base_executable = getattr(sys, "_base_executable", sys.executable)
        process_args = [base_executable, "-c", WINDOWS_JOB_LAUNCHER, *args]
    child_env = env.copy()
    role = {"api": "uvicorn", "celery": "celery-worker", "celery-beat": "celery-beat", "telegram": "telegram"}[name]
    child_env[ROLE_ENV] = role
    child_env["NURA_SECURITY_PROCESS_CYCLE"] = child_env.get("NURA_SECURITY_PROCESS_CYCLE", "1")
    captures: tuple[TextIO, ...] = ()
    process: subprocess.Popen[str] | None = None
    job_handle: int | None = None
    try:
        if child_env.get(CONTEXT_ENV):
            logs = os.path.join(child_env[CONTEXT_ENV], "logs")
            captures = (
                open(os.path.join(logs, f"{role}-cycle-{child_env['NURA_SECURITY_PROCESS_CYCLE']}.stdout.log"), "w", encoding="utf-8"),
                open(os.path.join(logs, f"{role}-cycle-{child_env['NURA_SECURITY_PROCESS_CYCLE']}.stderr.log"), "w", encoding="utf-8"),
            )
        process = subprocess.Popen(
            process_args,
            cwd=ROOT,
            env=child_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )
        if os.name == "nt":
            job_handle = _create_windows_job(process)
            assert process.stdin is not None
            process.stdin.write("start\n")
            process.stdin.flush()
        assert process.stdout is not None and process.stderr is not None
        output: queue.Queue[str] = queue.Queue()
        threading.Thread(target=_reader, args=(process.stdout, output, captures[0] if captures else None), daemon=True).start()
        threading.Thread(target=_reader, args=(process.stderr, output, captures[1] if captures else None), daemon=True).start()
        emit_event("process_start", safe_route_category=role)
        return ManagedProcess(name, process, output, [], job_handle, captures)
    except Exception as start_error:
        cleanup_errors: list[str] = []
        if job_handle is not None:
            try:
                _close_windows_job(job_handle)
            except Exception as error:  # noqa: BLE001 - retain the start failure
                cleanup_errors.append(f"job:{type(error).__name__}")
        if process is not None:
            try:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=10)
            except Exception as error:  # noqa: BLE001 - retain the start failure
                cleanup_errors.append(f"process:{type(error).__name__}")
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        for capture in captures:
            capture.close()
        if cleanup_errors:
            raise RuntimeError(
                "service_start_cleanup_failed:" + ";".join(cleanup_errors)
            ) from start_error
        raise


def _drain(managed: ManagedProcess) -> None:
    while True:
        try:
            managed.lines.append(managed.output.get_nowait())
        except queue.Empty:
            return


def _failure(managed: ManagedProcess) -> RuntimeError:
    _drain(managed)
    tail = "".join(managed.lines[-80:])
    return RuntimeError(f"{managed.name}_boot_failed:{tail[-4000:]}")


def _wait_for_line(managed: ManagedProcess, expected: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if managed.process.poll() is not None:
            raise _failure(managed)
        try:
            line = managed.output.get(timeout=0.2)
        except queue.Empty:
            continue
        managed.lines.append(line)
        if expected in line:
            return
    raise _failure(managed)


def _wait_for_ready(port: int, managed: ManagedProcess) -> None:
    deadline = time.monotonic() + 30
    url = f"http://127.0.0.1:{port}/ready"
    while time.monotonic() < deadline:
        if managed.process.poll() is not None:
            raise _failure(managed)
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if response.status == 200 and payload.get("status") == "ready":
                if payload.get("dependencies", {}).get("database") != "ok":
                    raise RuntimeError("api_database_not_ready")
                if payload.get("dependencies", {}).get("redis") != "ok":
                    raise RuntimeError("api_redis_not_ready")
                return
        except (OSError, urllib.error.URLError):
            time.sleep(0.2)
    raise _failure(managed)


def _run(args: list[str], env: dict[str, str], label: str) -> str:
    completed = subprocess.run(args, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    if completed.returncode:
        raise RuntimeError(f"{label}_failed:{(completed.stdout + completed.stderr)[-4000:]}")
    return completed.stdout


def _wait_for_worker(node: str, env: dict[str, str], managed: ManagedProcess) -> None:
    probe = (
        "import json; from core.tasks import celery_app; "
        f"print(json.dumps(celery_app.control.ping(destination=['{node}'], timeout=2) or []))"
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if managed.process.poll() is not None:
            raise _failure(managed)
        try:
            output = _run([sys.executable, "-c", probe], env, "celery_ping")
        except RuntimeError:
            time.sleep(0.3)
            continue
        if node in output and "pong" in output:
            registered = _run(
                [sys.executable, "-c", (
                    "import json; from core.tasks import celery_app; "
                    f"print(json.dumps(celery_app.control.inspect(destination=['{node}']).registered() or {{}}))"
                )],
                env,
                "celery_registered",
            )
            if all(task in registered for task in REQUIRED_TASKS):
                return
            raise RuntimeError("celery_required_tasks_not_registered")
        time.sleep(0.3)
    raise _failure(managed)


def _domain_counts(env: dict[str, str]) -> dict[str, int]:
    probe = """
import asyncio, json
from sqlalchemy import text
from core.database import dispose_async_database_state, get_async_sessionmaker
async def main():
    try:
        async with get_async_sessionmaker()() as session:
            print(json.dumps({name: (await session.execute(text(f'SELECT count(*) FROM {name}'))).scalar_one() for name in ('users', 'reports', 'orders')}))
    finally:
        await dispose_async_database_state()
asyncio.run(main())
"""
    return json.loads(_run([sys.executable, "-c", probe], env, "domain_count"))


def _stop(managed: ManagedProcess) -> None:
    try:
        if managed.process.poll() is None:
            if managed.name == "telegram":
                assert managed.process.stdin is not None
                managed.process.stdin.write("shutdown\n")
                managed.process.stdin.flush()
            elif os.name == "nt":
                managed.process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                managed.process.send_signal(signal.SIGINT)
            try:
                managed.process.wait(timeout=20)
            except subprocess.TimeoutExpired as error:
                managed.process.kill()
                managed.process.wait(timeout=10)
                raise RuntimeError(f"{managed.name}_graceful_shutdown_timeout") from error
        if managed.process.returncode != 0:
            interrupted = os.name == "nt" and managed.process.returncode in {
                -1073741510,
                3221225786,
            }
            _drain(managed)
            completed_shutdown = "Application shutdown complete." in "".join(managed.lines)
            if not interrupted and not completed_shutdown:
                raise _failure(managed)
    finally:
        emit_event("process_stop", safe_route_category=managed.name)
        for capture in managed.capture_handles:
            capture.close()
        if managed.job_handle is not None:
            _close_windows_job(managed.job_handle)
            managed.job_handle = None


def _boot_stack(env: dict[str, str]) -> None:
    port = _free_port()
    node = f"nura_service_boot_{os.getpid()}_{port}@localhost"
    queue_name = f"nura-service-boot-{port}"
    baseline_counts = _domain_counts(env)
    beat_schedule_dir = tempfile.mkdtemp(prefix="nura-service-boot-")
    processes: list[ManagedProcess] = []
    try:
        api = _start(
            "api",
            [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", str(port), "--lifespan", "on"],
            env,
        )
        processes.append(api)
        worker = _start(
            "celery",
            [sys.executable, "-m", "celery", "--quiet", "-A", "core.tasks", "worker", "--pool=solo", "--concurrency=1", "--hostname", node, "--queues", queue_name, "--without-gossip", "--without-mingle", "--without-heartbeat", "--loglevel=WARNING"],
            env,
        )
        processes.append(worker)
        beat = _start(
            "celery-beat",
            [
                sys.executable,
                "-m",
                "celery",
                "--quiet",
                "-A",
                "core.tasks",
                "beat",
                "--loglevel=WARNING",
                "--schedule",
                os.path.join(beat_schedule_dir, "schedule"),
            ],
            env,
        )
        processes.append(beat)
        telegram = _start(
            "telegram",
            [sys.executable, "-m", "tools.telegram_first_bot_boot_probe"],
            env,
        )
        processes.append(telegram)
        _wait_for_ready(port, api)
        _wait_for_worker(node, env, worker)
        _wait_for_line(telegram, "TELEGRAM_RUNTIME_READY")
        if beat.process.poll() is not None:
            raise _failure(beat)
        if _domain_counts(env) != baseline_counts:
            raise RuntimeError("service_boot_created_domain_records")
        for managed in (api, worker, telegram):
            _drain(managed)
            log = "".join(managed.lines)
            for sentinel in ("telegram-boot-sentinel", "yookassa-boot-sentinel", "ai-boot-sentinel"):
                if sentinel in log:
                    raise RuntimeError(f"startup_secret_leak:{managed.name}")
    finally:
        cleanup_errors: list[str] = []
        for managed in reversed(processes):
            try:
                _stop(managed)
            except Exception as error:  # noqa: BLE001 - aggregate all cleanup failures
                cleanup_errors.append(f"{managed.name}:{error}")
        shutil.rmtree(beat_schedule_dir, ignore_errors=True)
        if cleanup_errors:
            raise RuntimeError("service_boot_cleanup_failed:" + ";".join(cleanup_errors))


def prove_partial_start_cleanup(env: dict[str, str]) -> None:
    """Force a test-harness failure after bind and prove process/port cleanup."""
    port = _free_port()
    child = (
        "import socket, sys; "
        "sock=socket.socket(); sock.bind(('127.0.0.1', int(sys.argv[1]))); "
        "sock.listen(1); print('PARTIAL_HARNESS_READY', flush=True); "
        "assert sys.stdin.readline().strip() == 'shutdown'; sock.close()"
    )
    proof_env = env.copy()
    proof_env["NURA_SECURITY_PROCESS_CYCLE"] = "partial-start"
    managed: ManagedProcess | None = None
    controlled_failure = False
    try:
        managed = _start(
            "telegram",
            [sys.executable, "-c", child, str(port)],
            proof_env,
        )
        _wait_for_line(managed, "PARTIAL_HARNESS_READY")
        raise RuntimeError("controlled_partial_harness_failure")
    except RuntimeError as error:
        if str(error) != "controlled_partial_harness_failure":
            raise
        controlled_failure = True
    finally:
        if managed is not None:
            _stop(managed)
    if not controlled_failure:
        raise RuntimeError("partial_start_failure_not_exercised")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))


def run_service_boot(env: dict[str, str]) -> None:
    """Prove the full required topology and a repeat boot on one sandbox."""
    boot_env = env.copy()
    if boot_env.get(CONTEXT_ENV):
        import json

        registry = json.loads(
            open(os.path.join(boot_env[CONTEXT_ENV], "registry.json"), encoding="utf-8").read()
        )
        telegram_token = registry["telegram_token"]
        ai_key = registry["ai_api_key"]
        yookassa_shop = registry["yookassa_shop_id"]
        yookassa_secret = registry["yookassa_secret"]
    else:
        telegram_token = "123456:telegram-boot-sentinel-token-abcdefghi"
        ai_key = "ai-boot-sentinel"
        yookassa_shop = "boot-shop"
        yookassa_secret = "yookassa-boot-sentinel"
    boot_env.update({
        "PYTHONUNBUFFERED": "1",
        "TELEGRAM_BOT_TOKEN": telegram_token,
        "DEEPSEEK_API_KEY": ai_key,
        "YOOKASSA_SHOP_ID": yookassa_shop,
        "YOOKASSA_SECRET_KEY": yookassa_secret,
    })
    _boot_stack(boot_env)
    _boot_stack(boot_env)
