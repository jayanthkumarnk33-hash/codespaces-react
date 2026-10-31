"""Hosting wrapper only. The archived Garena lookup files remain unchanged."""

import hmac
import os
from flask import jsonify, request
from ff_api import app


@app.before_request
def optional_worker_key():
    key = os.environ.get("WORKER_API_KEY")
    if key and request.path != "/health":
        submitted = request.headers.get("Authorization", "")
        if not hmac.compare_digest(submitted.encode(), f"Bearer {key}".encode()):
            return jsonify(success=False, code="WORKER_UNAUTHORIZED", error="Backend authorization failed."), 401


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "3200")))
