"""Sequentially check supplied UIDs through the restored gateway/Python flow."""

import argparse
import csv
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports" / "restored-batch"
MARKER = "UPSTREAM_OBSERVATION "

BOOTSTRAP = '''
import json
import re
from urllib.parse import urlsplit
import ff_api
from app import app
for session in ff_api.pool.sessions:
    original = session.cr_session.post
    def observed(*args, _original=original, **kwargs):
        response = _original(*args, **kwargs)
        item = {"uid": kwargs.get("json", {}).get("login_id"), "http_status": response.status_code}
        if response.status_code == 429:
            item["retry_after"] = response.headers.get("retry-after")
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            item["nickname_present"] = isinstance(body.get("nickname"), str) and bool(body["nickname"].strip())
            if isinstance(body.get("url"), str):
                url = urlsplit(body["url"])
                item["challenge_url_redacted"] = f"{url.scheme}://{url.netloc}{url.path}"
            for key in ("error", "error_code", "code", "message"):
                value = body.get(key)
                if isinstance(value, (int, bool)) or isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_ .:,-]{0,160}", value):
                    item[key] = value
        print("UPSTREAM_OBSERVATION " + json.dumps(item), flush=True)
        return response
    session.cr_session.post = observed
app.run(host="127.0.0.1", port=3200)
'''


def now():
    return datetime.now(timezone.utc).isoformat()


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


def observations(log):
    result = []
    for line in log.read_text().splitlines():
        if line.startswith(MARKER):
            result.append(json.loads(line.removeprefix(MARKER)))
    return result


def safe_cell(value):
    value = str(value if value is not None else "")
    return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value


def save(report):
    report["checked"] = len(report["results"])
    report["success"] = sum(item["success"] for item in report["results"])
    report["failed"] = report["checked"] - report["success"]
    temporary = OUTPUT / ".uid-results.json.tmp"
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(OUTPUT / "uid-results.json")
    columns = ["uid", "success", "nickname", "region", "http_status", "upstream_status", "attempts", "code", "error", "checked_at"]
    temporary = OUTPUT / ".uid-results.csv.tmp"
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        for item in report["results"]:
            writer.writerow([safe_cell(item.get(key)) for key in columns])
    temporary.replace(OUTPUT / "uid-results.csv")


def retry_delay(items):
    seconds = 60
    for item in items:
        if item["http_status"] != 429:
            continue
        raw = item.get("retry_after")
        try:
            seconds = max(seconds, int(raw))
        except (TypeError, ValueError):
            try:
                seconds = max(seconds, int((parsedate_to_datetime(raw) - datetime.now(timezone.utc)).total_seconds()) + 1)
            except (TypeError, ValueError, OverflowError):
                pass
    return seconds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uids", type=Path, default=ROOT / "scripts/uids.txt")
    args = parser.parse_args()
    uids = re.split(r"[\s,]+", args.uids.read_text().strip())
    if not uids or len(set(uids)) != len(uids) or any(not re.fullmatch(r"[0-9]{6,20}", uid) for uid in uids):
        parser.error("UIDs must be unique 6-20 digit strings")
    subprocess.run([sys.executable, "scripts/check-restoration.py"], cwd=ROOT, check=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"flow": "Node gateway -> exact archived Python/curl_cffi -> full Chromium session",
              "historical_results_reused": False, "started_at": now(), "completed_at": None,
              "total_requested": len(uids), "checked": 0, "success": 0, "failed": 0, "results": []}
    save(report)
    python = os.environ.get("FF_TEST_PYTHON", sys.executable)
    worker_env = os.environ.copy()
    worker_env["PORT"] = "3200"
    worker_env.setdefault("FF_CHROMIUM_EXECUTABLE", "/usr/bin/chromium")
    gateway_env = os.environ.copy()
    gateway_env.update({"PORT": "3100", "FF_WORKER_URL": "http://127.0.0.1:3200"})
    gateway_env["NO_PROXY"] = ",".join(filter(None, [gateway_env.get("NO_PROXY", gateway_env.get("no_proxy", "")), "localhost", "127.0.0.1", "::1"]))
    worker_log_path = OUTPUT / "worker-run.log"
    processes = []
    try:
        with worker_log_path.open("w") as worker_log, (OUTPUT / "gateway-run.log").open("w") as gateway_log:
            worker = subprocess.Popen([python, "-u", "-c", BOOTSTRAP], cwd=ROOT / "worker", env=worker_env, stdout=worker_log, stderr=subprocess.STDOUT)
            processes.append(worker)
            ready(3200, "/health", worker)
            gateway = subprocess.Popen(["node", "--use-env-proxy", "server.js"], cwd=ROOT, env=gateway_env, stdout=gateway_log, stderr=subprocess.STDOUT)
            processes.append(gateway)
            ready(3100, "/api/health", gateway)
            print(f"Restored worker and gateway ready; checking {len(uids)} UIDs sequentially.", flush=True)
            for index, uid in enumerate(uids):
                before = len(observations(worker_log_path))
                try:
                    status, body = get(3100, f"/api/ff/{uid}", 100)
                    success = status == 200 and body.get("success") is True
                    item = {"uid": uid, "http_status": status, "success": success,
                            "checked_at": body.get("checked_at", now()), "response": body}
                    for key in ["nickname", "region", "open_id", "img_url", "code", "error"]:
                        if key in body:
                            item[key] = body[key]
                except Exception as error:
                    item = {"uid": uid, "success": False, "code": "BATCH_CLIENT_ERROR", "error": type(error).__name__, "checked_at": now()}
                trace = [record for record in observations(worker_log_path)[before:] if record.get("uid") == uid]
                item["attempts"] = len(trace)
                item["upstream_observations"] = trace
                item["upstream_status"] = trace[-1]["http_status"] if trace else None
                report["results"].append(item)
                save(report)
                description = f"{item.get('nickname')} ({item.get('region')})" if item["success"] else item.get("code")
                print(f"[{index + 1}/{len(uids)}] {uid}: {description}", flush=True)
                if item.get("code") == "LOOKUP_RATE_LIMIT" or any(record["http_status"] == 429 for record in trace):
                    pause = retry_delay(trace)
                    print(f"Rate limit: waiting {pause}s before continuing.", flush=True)
                    while pause > 0:
                        step = min(30, pause)
                        time.sleep(step)
                        pause -= step
                elif item.get("code") == "WORKER_TIMEOUT":
                    print("Backend timeout: allowing the original request to finish before continuing.", flush=True)
                    time.sleep(40)
                if index < len(uids) - 1:
                    time.sleep(2.5)
    except Exception as error:
        report["harness_error"] = type(error).__name__
        save(report)
        raise
    finally:
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    assert [item["uid"] for item in report["results"]] == uids
    report["completed_at"] = now()
    save(report)
    print(f"Completed all {len(uids)} UIDs: {report['success']} successful, {report['failed']} failed. Reports: {OUTPUT}", flush=True)


if __name__ == "__main__":
    main()
