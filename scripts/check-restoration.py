import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "worker"
manifest = json.loads((root / "restore-manifest.json").read_text())
for name, expected in manifest["files"].items():
    assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, f"Archived file changed: {name}"
print("Verified: original lookup, browser helper and dependency lock match the archived successful run byte for byte.")
