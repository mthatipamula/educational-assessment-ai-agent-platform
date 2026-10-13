"""Code sandbox: runs untrusted student Python against test cases.

Isolation is layered:
- Container (docker-compose): no network (internal-only network), read-only root filesystem, non-root user,
  all Linux capabilities dropped, no privilege escalation, memory/CPU/process limits.
- Per run: a fresh temp directory, an empty environment, Python's isolated mode (-I), CPU time, memory, file
  size and process-count rlimits, a wall-clock timeout, and output truncation.
In production this would run on a microVM or gVisor-style sandbox (e.g. Firecracker or a dedicated Fargate task).
"""
import json
import os
import resource
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY = 64 * 1024
MAX_TESTS = 20
WALL_TIMEOUT = 3.0
MAX_OUTPUT = 10_000
SLOTS = threading.BoundedSemaphore(4)

HARNESS = r'''
import json, sys
sys.setrecursionlimit(1000)
namespace = {"__name__": "student"}
with open(sys.argv[1]) as f:
    exec(compile(f.read(), "student.py", "exec"), namespace)
if "solve" not in namespace:
    raise SystemExit("Define a function named solve")
result = namespace["solve"](*json.loads(sys.argv[2]))
print("\n__RESULT__" + json.dumps(result))
'''


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))                       # seconds of CPU
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024,) * 2)        # memory
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024,) * 2)           # files it may write
    resource.setrlimit(resource.RLIMIT_NPROC, (16, 16))                     # no fork bombs
    os.setsid()


def _equal(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) < 1e-6
    return a == b


def run(code: str, tests: list[dict]) -> dict:
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "student.py"), "w") as f:
            f.write(code)
        with open(os.path.join(tmp, "harness.py"), "w") as f:
            f.write(HARNESS)
        for i, test in enumerate(tests[:MAX_TESTS]):
            try:
                proc = subprocess.run(
                    [sys.executable, "-I", "-S", "harness.py", "student.py", json.dumps(test["args"])],
                    cwd=tmp, env={}, capture_output=True, text=True, timeout=WALL_TIMEOUT, preexec_fn=_limits)
                out = proc.stdout[-MAX_OUTPUT:]
                if "__RESULT__" in out:
                    actual = json.loads(out.rsplit("__RESULT__", 1)[1])
                    results.append({"test": i + 1, "args": test["args"], "expected": test["expected"],
                                    "actual": actual, "passed": _equal(actual, test["expected"])})
                else:
                    err = (proc.stderr or out).strip().splitlines()
                    results.append({"test": i + 1, "args": test["args"], "passed": False,
                                    "error": err[-1][:300] if err else f"exited with code {proc.returncode}"})
            except subprocess.TimeoutExpired:
                results.append({"test": i + 1, "args": test["args"], "passed": False, "error": "Timed out (3s limit)"})
    return {"results": results}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        self._send(200, {"status": "UP"}) if self.path == "/health" else self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path != "/run":
            return self._send(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_BODY:
            return self._send(413, {"error": "request too large"})
        try:
            body = json.loads(self.rfile.read(length))
            code, tests = str(body["code"]), list(body["tests"])
        except (ValueError, KeyError, TypeError):
            return self._send(400, {"error": "expected {code, tests}"})
        if not SLOTS.acquire(timeout=10):
            return self._send(503, {"error": "sandbox busy"})
        try:
            self._send(200, run(code, tests))
        finally:
            SLOTS.release()

    def log_message(self, *args):  # quiet
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
