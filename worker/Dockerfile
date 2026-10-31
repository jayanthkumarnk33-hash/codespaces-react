# syntax=docker/dockerfile:1
FROM python:3.12-slim-trixie
ENV PYTHONUNBUFFERED=1 FF_CHROMIUM_EXECUTABLE=/usr/bin/chromium
WORKDIR /app
COPY requirements.lock.txt requirements-deploy.txt ./
RUN --mount=type=secret,id=ca_bundle \
    task_ca_bundle=/etc/ssl/certs/ca-certificates.crt; \
    if [ -s /run/secrets/ca_bundle ]; then task_ca_bundle=/run/secrets/ca_bundle; fi; \
    apt-get -o Acquire::https::CaInfo="$task_ca_bundle" update && \
    apt-get -o Acquire::https::CaInfo="$task_ca_bundle" install -y --no-install-recommends chromium ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    PIP_CERT="$task_ca_bundle" python -m pip install --no-cache-dir -r requirements-deploy.txt
COPY . .
EXPOSE 3200
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
