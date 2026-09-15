#!/usr/bin/env python
"""Run the whole local development stack from one terminal.

    .venv\\Scripts\\python.exe dev.py

Starts the FastAPI backend and the Next.js app, tags every line of their
output with which one printed it, and shuts both down together on Ctrl+C or
when either of them dies. It runs exactly the commands you would type by
hand - uvicorn's --reload and next dev already handle hot reloading, and
nothing here re-implements that.

It could once start a third service, the Streamlit app; that has been retired,
so there is nothing left for a --streamlit flag to launch.

It does not install anything, migrate anything, or touch the database.
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IS_WINDOWS = os.name == "nt"

# Child processes print characters a legacy Windows console cannot encode -
# next dev opens with "▲ Next.js". Without this, the first such line raises
# UnicodeEncodeError inside the reader thread, killing it: the service keeps
# running while its output silently stops, which is precisely the half-dead
# state this script exists to prevent.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# How long a process gets to exit politely before it is killed outright.
GRACE_SECONDS = 10


# --------------------------------------------------------------------------- #
# colour
# --------------------------------------------------------------------------- #
def _supports_colour() -> bool:
    """True when ANSI colour is safe to emit.

    Honours NO_COLOR, skips it when output is piped to a file, and on Windows
    turns on virtual terminal processing first - without that, the escape
    codes are printed literally on an older console.
    """
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stdout.isatty():
        return False
    if IS_WINDOWS:
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)          # STD_OUTPUT_HANDLE
            mode = ctypes.c_uint32()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                return False
            # 0x4 = ENABLE_VIRTUAL_TERMINAL_PROCESSING
            return bool(kernel32.SetConsoleMode(handle, mode.value | 0x4))
        except Exception:
            return False
    return True


COLOUR = _supports_colour()
RESET = "\033[0m" if COLOUR else ""


def paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}{RESET}" if COLOUR else text


# --------------------------------------------------------------------------- #
# process trees
# --------------------------------------------------------------------------- #
def _create_job_object():
    """A Windows job object that kills everything in it when it is closed.

    taskkill /F /T is not enough here, and this was found by running it rather
    than by reading about it: uvicorn --reload spawns its server through
    multiprocessing, /F kills the reloader instantly, and the server child is
    orphaned before the tree walk reaches it - leaving port 8000 held by a
    process with no parent. A job object has no such race. Every descendant a
    child spawns joins the job, and terminating the job takes all of them.

    Returns None when the job cannot be created; stop() then falls back.
    """
    if not IS_WINDOWS:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.windll.kernel32
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        ok = kernel32.SetInformationJobObject(
            job,
            9,  # JobObjectExtendedLimitInformation
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            kernel32.CloseHandle(job)
            return None
        return job
    except Exception:
        return None


def _assign_to_job(job, process: subprocess.Popen) -> bool:
    if job is None:
        return False
    try:
        import ctypes

        # Popen._handle is the process HANDLE on Windows. Private, but stable,
        # and the alternative is reopening the process by pid.
        return bool(ctypes.windll.kernel32.AssignProcessToJobObject(job, process._handle))
    except Exception:
        return False


def _descendants(pid: int) -> list[int]:
    """Every process below `pid`, snapshotted now.

    The job object is the primary mechanism, but it can miss a grandchild that
    was spawned in the window between Popen returning and the assignment -
    which the venv's python.exe shim makes likely, because it launches the real
    interpreter immediately and then exits. Taking the tree from the OS at stop
    time does not depend on that timing at all.
    """
    if not IS_WINDOWS:
        return []
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process | "
                "ForEach-Object { \"$($_.ProcessId) $($_.ParentProcessId)\" }",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except Exception:
        return []

    children: dict[int, list[int]] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            child, parent = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        children.setdefault(parent, []).append(child)

    found: list[int] = []
    queue = [pid]
    seen = {pid}
    while queue:
        current = queue.pop()
        for child in children.get(current, []):
            if child in seen:            # a pid table can contain cycles
                continue
            seen.add(child)
            found.append(child)
            queue.append(child)
    return found


def _terminate_job(job) -> bool:
    if job is None:
        return False
    try:
        import ctypes

        return bool(ctypes.windll.kernel32.TerminateJobObject(job, 1))
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# services
# --------------------------------------------------------------------------- #
class Service:
    """One child process, its label, and the thread pumping its output."""

    def __init__(
        self,
        name: str,
        colour: str,
        command: list[str],
        cwd: Path,
        env: dict[str, str] | None = None,
        watch: Path | None = None,
    ) -> None:
        self.name = name
        self.colour = colour
        self.command = command
        self.cwd = cwd
        self.env = env
        self.watch = watch
        self.process: subprocess.Popen[str] | None = None
        self.reader: threading.Thread | None = None
        self.job = None
        # True only across a deliberate watcher restart, so the supervisor
        # does not mistake the gap for a crash.
        self.restarting = False

    @property
    def tag(self) -> str:
        return paint(f"[{self.name}]", self.colour)

    def start(self, print_line) -> None:
        environment = {**os.environ, **(self.env or {})}
        # Python children buffer stdout when it is a pipe, which would hold
        # their output back until they exit. Unbuffered is the whole point here.
        environment.setdefault("PYTHONUNBUFFERED", "1")
        environment.setdefault("FORCE_COLOR", "1" if COLOUR else "0")

        self.process = subprocess.Popen(
            self.command,
            cwd=str(self.cwd),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,      # one interleaved stream, one label
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            # Its own process group on POSIX, so stop() can signal the whole
            # tree without signalling us as well. Ctrl+C then no longer reaches
            # the children directly, which is fine - stop() is what ends them.
            start_new_session=not IS_WINDOWS,
        )
        # Assign before the child gets far enough to spawn anything of its own.
        self.job = _create_job_object()
        if not _assign_to_job(self.job, self.process):
            self.job = None
        self.reader = threading.Thread(
            target=self._pump, args=(print_line,), daemon=True, name=f"{self.name}-out"
        )
        self.reader.start()

    def _pump(self, print_line) -> None:
        assert self.process is not None and self.process.stdout is not None
        try:
            for line in self.process.stdout:
                print_line(f"{self.tag} {line.rstrip()}")
        except Exception as exc:                      # never lose the stream
            print_line(f"{self.tag} (output stopped: {exc})")

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def stop(self, print_line) -> None:
        """Terminate, then kill after the grace period if it is still there.

        On Windows the job object takes the whole tree at once, which taskkill
        could not do reliably for uvicorn's reload child. On POSIX the process
        group does the same job. taskkill remains the fallback for the case
        where the job could not be created.
        """
        if self.process is None or self.process.poll() is not None:
            return

        try:
            if IS_WINDOWS:
                # Snapshot first: once the parent dies its children are
                # orphaned and the tree can no longer be walked.
                strays = _descendants(self.process.pid)
                if not _terminate_job(self.job):
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                        check=False,
                        capture_output=True,
                    )
                for pid in strays:
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(pid)],
                        check=False,
                        capture_output=True,
                    )
            else:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
        except Exception:
            self.process.terminate()

        try:
            self.process.wait(timeout=GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            print_line(f"{self.tag} did not stop in {GRACE_SECONDS}s - killing it")
            try:
                self.process.kill()
                self.process.wait(timeout=5)
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# building the service list
# --------------------------------------------------------------------------- #
def venv_python() -> str:
    """The virtualenv's interpreter if there is one, else whatever is on PATH."""
    candidate = ROOT / ".venv" / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
    if candidate.exists():
        return str(candidate)
    return sys.executable or "python"


def npm_command() -> str | None:
    # shutil.which finds npm.cmd on Windows; calling bare "npm" from Popen
    # without a shell does not.
    return shutil.which("npm") or shutil.which("npm.cmd")


def build_services(args: argparse.Namespace) -> tuple[list[Service], list[str]]:
    python = venv_python()
    services: list[Service] = []
    problems: list[str] = []

    services.append(
        Service(
            name="backend",
            colour="36",  # cyan
            command=[
                python,
                "-m",
                "uvicorn",
                "app.main:app",
                "--port",
                str(args.backend_port),
            ],
            cwd=ROOT / "backend",
            # Not --reload. uvicorn's reloader spawns its worker through
            # multiprocessing, and on Windows that spawn never completes when
            # stdout is a pipe rather than a console - it logs "Reloading..."
            # and then serves the OLD code forever. Reproduced with a bare
            # `uvicorn --reload | cat`, so it is not something this script
            # introduced, but this script always captures stdout in order to
            # tag the output. A silently stale server is the worst of the
            # options, so dev.py watches the files and restarts the service
            # itself - see watch_and_restart below.
            watch=ROOT / "backend" / "app",
        )
    )

    if not args.no_frontend:
        npm = npm_command()
        if npm is None:
            problems.append(
                "npm was not found on PATH, so the Next.js app cannot start. "
                "Install Node.js, or run with --no-frontend."
            )
        elif not (ROOT / "web" / "node_modules").exists():
            problems.append(
                "web/node_modules is missing. Run `npm install` inside web/ once, "
                "then try again (dev.py deliberately does not install for you)."
            )
        else:
            services.append(
                Service(
                    name="web",
                    colour="35",  # magenta
                    command=[npm, "run", "dev"],
                    cwd=ROOT / "web",
                    # A non-default backend port would otherwise leave the app
                    # calling 8000 and failing every request.
                    env={"NEXT_PUBLIC_API_BASE_URL": f"http://127.0.0.1:{args.backend_port}"},
                )
            )

    return services, problems


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def watch_and_restart(service: Service, print_line, stopping: threading.Event) -> None:
    """Restart one service when its watched directory changes.

    This is the hot reload uvicorn's own --reload cannot provide here (see the
    note on the backend service). watchfiles ships with uvicorn[standard], so
    it is already installed; if it somehow is not, the loop simply never runs
    and the service behaves like a normal non-reloading process.
    """
    if service.watch is None:
        return
    try:
        from watchfiles import watch
    except ImportError:
        print_line(f"{service.tag} watchfiles is unavailable - no hot reload")
        return

    for _changes in watch(str(service.watch), stop_event=stopping, debounce=400):
        if stopping.is_set():
            return
        print_line(f"{service.tag} change detected - restarting")
        service.restarting = True
        service.stop(print_line)
        try:
            service.start(print_line)
            service.restarting = False
        except Exception as exc:
            service.restarting = False
            print_line(f"{service.tag} could not restart: {exc}")
            stopping.set()
            return


def _readable_code(code: int | None) -> str:
    """Windows reports a killed process as 4294967295 rather than -1."""
    if code is None:
        return "?"
    if code > 0x7FFFFFFF:
        return str(code - 0x100000000)
    return str(code)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start the Grow Vyaapar development stack in one terminal.",
    )
    parser.add_argument(
        "--no-frontend",
        action="store_true",
        help="backend only; skip the Next.js app",
    )
    parser.add_argument(
        "--backend-port",
        type=int,
        default=8000,
        help="port for uvicorn (default: 8000)",
    )
    args = parser.parse_args()

    if not (ROOT / "backend" / "app" / "main.py").exists():
        print(f"dev.py must sit at the repo root; {ROOT} does not look like it.")
        return 1

    print_lock = threading.Lock()

    def print_line(text: str) -> None:
        # One lock so two services cannot interleave halfway through a line.
        with print_lock:
            print(text, flush=True)

    services, problems = build_services(args)
    for problem in problems:
        print_line(paint("! ", "31") + problem)
    if problems and len(services) < 2 and not args.no_frontend:
        return 1

    print_line(paint("Starting:", "1") + " " + ", ".join(s.name for s in services))
    print_line(paint(f"  backend   http://127.0.0.1:{args.backend_port}  (/docs)", "90"))
    if any(s.name == "web" for s in services):
        print_line(paint("  web       http://localhost:3000", "90"))
    print_line(paint("Ctrl+C stops everything.", "90"))
    print_line("")

    for service in services:
        try:
            service.start(print_line)
        except FileNotFoundError as exc:
            print_line(paint("! ", "31") + f"could not start {service.name}: {exc}")
            for started in services:
                started.stop(print_line)
            return 1

    # Ctrl+C sets a flag rather than unwinding through an exception. Relying on
    # KeyboardInterrupt meant Windows could finish its own control-C handling
    # and end the process (STATUS_CONTROL_C_EXIT) before the teardown below had
    # run - which happened to look fine only because the children share the
    # console and got the signal too. A hung child would have survived.
    stopping = threading.Event()

    def _on_interrupt(_signum, _frame) -> None:
        stopping.set()

    signal.signal(signal.SIGINT, _on_interrupt)
    if IS_WINDOWS and hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _on_interrupt)

    for service in services:
        if service.watch is not None:
            threading.Thread(
                target=watch_and_restart,
                args=(service, print_line, stopping),
                daemon=True,
                name=f"{service.name}-watch",
            ).start()

    exit_code = 0
    try:
        while not stopping.is_set():
            # A service being restarted by its watcher is momentarily not
            # alive; that is not a death worth tearing the stack down for.
            dead = next(
                (s for s in services if not s.alive and not s.restarting), None
            )
            if dead is not None:
                code = dead.process.returncode if dead.process else None
                print_line("")
                print_line(
                    paint("! ", "31")
                    + f"{dead.name} exited with code {_readable_code(code)} - "
                    "stopping the rest."
                )
                # Our own status is a plain 1: a Windows exit code does not fit
                # in the byte a shell reads, and 4294967295 is not information.
                exit_code = 0 if code == 0 else 1
                break
            time.sleep(0.25)
    except KeyboardInterrupt:                    # a second Ctrl+C mid-teardown
        stopping.set()

    if stopping.is_set():
        # The children share this console and get their own Ctrl+C, so they may
        # already be on their way out; stop() is idempotent either way.
        print_line("")
        print_line(paint("Stopping...", "90"))

    for service in services:
        service.stop(print_line)

    print_line(paint("All stopped.", "90"))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
