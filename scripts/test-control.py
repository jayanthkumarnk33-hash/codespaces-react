"""One control UID through Node gateway -> exact archived Python implementation."""

import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[1]
reports = root / "reports"
reports.mkdir(exist_ok=True)
python = os.environ.get("FF_TEST_PYTHON", sys.executable)
worker_env = os.environ.copy()
worker_env["PORT"] = "3200"
worker_env.setdefault("FF_CHROMIUM_EXECUTABLE", "/usr/bin/chromium")
gateway_env = os.environ.copy()
gateway_env.update({"PORT": "3100", "FF_WORKER_URL": "http://127.0.0.1:3200"})
existing = gateway_env.get("NO_PROXY", gateway_env.get("no_proxy", ""))
gateway_env["NO_PROXY"] = ",".join(filter(None, [existing, "localhost", "127.0.0.1", "::1"]))

bootstrap = '''
import json
from urllib.parse import urlsplit
import ff_api
from app import app
for session in ff_api.pool.sessions:
    original = session.cr_session.post
    def observed(*args, _original=original, **kwargs):
        response = _original(*args, **kwargs)
        item = {"uid": kwargs.get("json", {}).get("login_id"), "http_status": response.status_code}
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            item["nickname_present"] = isinstance(body.get("nickname"), str) and bool(body["nickname"].strip())
            if isinstance(body.get("url"), str):
                url = urlsplit(body["url"])
                item["challenge_url_redacted"] = f"{url.scheme}://{url.netloc}{url.path}"
        print("UPSTREAM_OBSERVATION " + json.dumps(item), flush=True)
        return response
    session.cr_session.post = observed
app.run(host="127.0.0.1", port=3200)
'''


def get(port, path, timeout=5):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def ready(port, path, process):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            status, _ = get(port, path, 2)
            if status == 200:
                return
        except (OSError, http.client.HTTPException):
            pass
        if process.poll() is not None:
            raise RuntimeError("Process exited during startup")
        time.sleep(0.2)
    raise TimeoutError("Startup timed out")


processes = []
report = {"uid": "11111119", "flow": "Node gateway -> archived Python/curl_cffi -> full Chromium session",
          "uid_api_requests": 1, "historical_result_reused": False}
with (reports / "restored-worker-run.log").open("w") as worker_log, (reports / "gateway-run.log").open("w") as gateway_log:
    try:
        worker = subprocess.Popen([python, "-u", "-c", bootstrap], cwd=root / "worker", env=worker_env, stdout=worker_log, stderr=subprocess.STDOUT)
        processes.append(worker)
        ready(3200, "/health", worker)
        gateway = subprocess.Popen(["node", "--use-env-proxy", "server.js"], cwd=root, env=gateway_env, stdout=gateway_log, stderr=subprocess.STDOUT)
        processes.append(gateway)
        ready(3100, "/api/health", gateway)
        print("Worker and gateway ready; checking only UID 11111119.", flush=True)
        status, body = get(3100, "/api/ff/11111119", 100)
        report.update({"http_status": status, "result": body})
    except Exception as error:
        report["harness_error"] = type(error).__name__
    finally:
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

observations = []
for line in (reports / "restored-worker-run.log").read_text().splitlines():
    if line.startswith("UPSTREAM_OBSERVATION "):
        observations.append(json.loads(line.removeprefix("UPSTREAM_OBSERVATION ")))
report["garena_lookup_requests_made"] = len(observations)
report["upstream_observations"] = observations
(reports / "restored-control-11111119.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(report, ensure_ascii=False, indent=2))
