# Restored original Free Fire lookup flow

This restores the exact Python implementation from the archived successful
`11111119` lookup. That successful run used Python, Flask, curl_cffi and
Patchright with full system Chromium. It was not a Cloudflare Worker.

The latest control test through this project's gateway returned **HTTP 200**,
nickname **`╰‿╯аɢuѕтıп`**, region **US**, for UID **11111119**. It made one
new Garena player lookup POST. See `reports/restored-control-11111119.json`.
Historical evidence is separately labeled `reports/historical-*` and is never
used as a response fallback. This result confirms the control UID in this run;
it does not guarantee that other UIDs or subsequent requests avoid challenges.

## What runs where

```text
Client -> Node.js/Vercel gateway -> Python backend -> Garena
                                  full Chromium
                                  Patchright + curl_cffi
```

- `worker/ff_api.py`: exact archived lookup and Flask routes.
- `worker/data_dome.py`: exact archived browser session helper.
- `worker/requirements.lock.txt`: exact archived Python dependency lock.
- `worker/app.py`: hosting wrapper with optional backend API-key protection.
- `worker/Dockerfile`: Python backend with full Chromium and Gunicorn.
- `api/ff/[uid].js`: Vercel handler that forwards to the Python backend.

The Node gateway does not implement its own Garena lookup. Public proxy pools,
the serverless headless-shell port, and Node browser-fetch experiments are not
part of this project. Original HTTPS_PROXY handling inside the Python helper
remains unchanged.

The original Python files are checked against SHA-256 values in
`worker/restore-manifest.json`. Run `python scripts/check-restoration.py` to
verify they remain byte-for-byte identical to the archived successful version.
Hosting wrappers do not change those lookup files.

## Run the Python API locally

Requires Python 3.12 and an installed full Chrome/Chromium executable:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r worker/requirements.lock.txt
FF_CHROMIUM_EXECUTABLE=/usr/bin/chromium PORT=3200 .venv/bin/python worker/app.py
```

Adapt the executable path to your machine. In another terminal:

```bash
curl http://127.0.0.1:3200/health
curl http://127.0.0.1:3200/api/ff/11111119
```

This directly calls the original Python lookup. It requires no Node gateway.
The inherited environment proxy is used when configured. No residential or
public proxy account was supplied for the successful recorded control test.

## Run the Node gateway locally

Requires Node.js 24. Keep the Python backend running, then:

```bash
npm ci
FF_WORKER_URL=http://127.0.0.1:3200 NO_PROXY=localhost,127.0.0.1,::1 npm start
```

```bash
curl http://127.0.0.1:3000/api/ff/11111119
```

`npm start` loads `.env` when present and enables Node's environment proxy
support. Preserve existing environment proxy settings. The loopback NO_PROXY
entries above are for a local backend; retain any other entries your network
requires. Do not set a loopback FF_WORKER_URL on a deployed Vercel function.

## Run the Python backend with Docker

On a normal Docker host with working internet and CA trust:

```bash
docker build -t freefire-python-worker ./worker
docker run --rm -p 3200:3200 freefire-python-worker
```

The image includes full Chromium and the archived Python dependencies.
Gunicorn uses one process and one request thread, with the original session
pool inside that process. The worker binds to `PORT` (default 3200).

For builds behind a TLS-inspecting proxy, the Dockerfile accepts an optional
BuildKit secret `ca_bundle` for the installation steps. Supply your trusted
combined CA bundle without disabling verification. For example in the managed
workspace:

```bash
docker build --secret id=ca_bundle,src=/etc/ssl/certs/ca-certificates.crt \
  -t freefire-python-worker ./worker
```

Runtime proxy/CA trust must also be configured for the worker host when needed;
the build-only CA mount is not copied into the image. This workspace's Docker
build and a container Chromium/about:blank check passed. The live UID control
test used the restored Python process and full system Chromium on the host,
not the container or a public deployment.

## GitHub and Vercel

1. Upload this project's contents to the intended GitHub repository. Include
   `worker`, `api`, `lib`, package/lock files, `vercel.json` and `.github`.
2. Run the Python backend on a host/process that supports full Chromium. The
   supplied Dockerfile is one way to do that. Obtain its reachable base URL.
3. Import the repository into Vercel as **Other**, using Node.js **24.x** and
   this directory as Root Directory. Leave Build Command and Output Directory
   unset.
4. Set `FF_WORKER_URL` in Vercel to the reachable Python backend base URL.
5. Optionally set the same `WORKER_API_KEY` on the gateway and Python backend.
   The gateway sends it as a bearer header; the worker validates it. Keep real
   values in environment settings, not in Git.
6. Deploy and test `/api/health`, then `/api/ff/11111119`.

Vercel hosts the lightweight gateway. The Python backend must also be running;
the Vercel gateway cannot launch the backend's Dockerfile itself. Without
FF_WORKER_URL it returns `WORKER_NOT_CONFIGURED`. This work does not create
a GitHub repository, host a backend, or deploy to a Vercel account.

## Verification

```bash
npm test
npm run check
python scripts/check-restoration.py
.venv/bin/python -m unittest discover -s worker -p test_browser_patch.py
```

Five gateway tests and six archived Python tests pass. GitHub Actions runs
these offline checks and the restoration hash check. They do not perform
live Garena requests.

To reproduce the single control test on a Linux machine with full Chromium:

```bash
FF_TEST_PYTHON="$PWD/.venv/bin/python" python scripts/test-control.py
```

This starts a local worker and gateway, requests only UID 11111119, records the
new response and sanitized upstream status, then stops both processes. The
original retry limit is retained. Cookie values, session keys and challenge
query tokens are excluded from the structured report.

## Check the complete supplied UID list

The original list of 87 unique UIDs is in `scripts/uids.txt`:

```bash
FF_TEST_PYTHON="$PWD/.venv/bin/python" python scripts/test-all-uids.py
python scripts/summarize-all-uids.py
```

The checker first verifies the archived source hashes, then starts the same
worker/gateway stack used by the successful control test. It sends requests
sequentially, preserves the original retry behavior, waits 2.5 seconds between
UIDs, and honors observed rate-limit delays. Every result is checkpointed in
`reports/restored-batch/uid-results.json` and `.csv`. The summary command verifies
all 87 inputs appear exactly once and produces `reports/restored-batch/summary.md`.
That table distinguishes confirmed names, explicit Garena `invalid_id` errors,
and verification challenges. Historical responses are not reused.
