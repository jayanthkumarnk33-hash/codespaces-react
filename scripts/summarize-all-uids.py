"""Verify complete batch coverage and produce the readable results table."""

from collections import Counter
import csv
from datetime import datetime
import html
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports/restored-batch"
report = json.loads((OUTPUT / "uid-results.json").read_text())
expected = (ROOT / "scripts/uids.txt").read_text().split()
assert report["completed_at"], "The batch is not complete"
assert [item["uid"] for item in report["results"]] == expected
assert len(set(expected)) == len(expected) == 87
assert report["checked"] == 87
assert report["success"] + report["failed"] == 87

for item in report["results"]:
    if item["success"]:
        assert item["http_status"] == item["upstream_status"] == 200
        assert item["response"]["uid"] == item["uid"]
        assert item["nickname"] == item["response"]["nickname"]
        item["outcome"] = "PLAYER_FOUND"
    else:
        explicit = next((observation.get("error") for observation in item["upstream_observations"]
                         if observation["http_status"] == 200 and observation.get("error") == "invalid_id"), None)
        item["outcome"] = "GARENA_INVALID_ID" if explicit else item.get("code", "UNCONFIRMED")
    errors = [observation.get("error") for observation in item["upstream_observations"] if observation.get("error")]
    item["garena_error"] = errors[-1] if errors else None

report["outcomes"] = dict(Counter(item["outcome"] for item in report["results"]))
report["regions"] = dict(Counter(item.get("region") for item in report["results"] if item["success"]))
report["garena_lookup_requests_made"] = sum(item["attempts"] for item in report["results"])
(OUTPUT / "uid-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


def csv_cell(value):
    value = str(value if value is not None else "")
    return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value


columns = ["uid", "success", "nickname", "region", "http_status", "upstream_status", "attempts", "outcome", "code", "garena_error", "error", "checked_at"]
with (OUTPUT / "uid-results.csv").open("w", encoding="utf-8-sig", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(columns)
    for item in report["results"]:
        writer.writerow([csv_cell(item.get(key)) for key in columns])


def cell(value):
    return html.escape(str(value if value is not None else ""), quote=False).replace("|", "\\|").replace("\n", " ")


def local_time(value):
    return datetime.fromisoformat(value).astimezone(ZoneInfo("Asia/Calcutta")).strftime("%Y-%m-%d %H:%M:%S %Z")


lines = [
    "# All 87 supplied UIDs: restored Python flow", "",
    f"Checked **87/87**. Player names confirmed: **{report['success']}**. Other responses: **{report['failed']}**.", "",
    f"Started: {local_time(report['started_at'])}. Completed: {local_time(report['completed_at'])}.", "",
    "Every lookup used the Node gateway and the exact archived Python/curl_cffi implementation with full Chromium. No historical responses were reused. No public proxy pool was used.", "",
    "| Outcome | Count |", "| --- | ---: |",
    *[f"| {cell(key)} | {count} |" for key, count in report["outcomes"].items()], "",
    "A DataDome challenge does not establish that a UID is invalid. GARENA_INVALID_ID is used only when Garena explicitly returned `error: invalid_id` with HTTP 200. The original worker's error code is preserved separately in JSON and CSV.", "",
    "Region codes are the account regions returned by Garena. Nicknames are in-game names. Raw Unicode is preserved in JSON; CSV escapes leading spreadsheet formula characters.", "",
    "Full reports: [CSV](uid-results.csv), [JSON](uid-results.json).", "",
    "| UID | Confirmed nickname | Account region | Gateway HTTP | Garena HTTP | Outcome |",
    "| --- | --- | --- | ---: | ---: | --- |",
]
for item in report["results"]:
    lines.append("| " + " | ".join(cell(item.get(key)) for key in ["uid", "nickname", "region", "http_status", "upstream_status", "outcome"]) + " |")
(OUTPUT / "summary.md").write_text("\n".join(lines) + "\n")
print(json.dumps({key: report[key] for key in ["checked", "success", "failed", "outcomes", "regions", "garena_lookup_requests_made"]}, ensure_ascii=False, indent=2))
