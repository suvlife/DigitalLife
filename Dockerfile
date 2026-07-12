# DigitalLife multi-stage image.
# Both web apps are built here: V2 is served at / and the classic console at /v1/.

FROM ubuntu:24.04 AS frontend-builder

RUN apt-get update && apt-get install -y curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci
COPY frontend/ ./frontend/
RUN cd frontend && npm run build

COPY frontend-v2/package.json frontend-v2/package-lock.json ./frontend-v2/
RUN cd frontend-v2 && npm ci
COPY frontend-v2/ ./frontend-v2/
RUN cd frontend-v2 && npm run build

FROM ubuntu:24.04

LABEL maintainer="DigitalLife Team"
LABEL description="DigitalLife multi-agent collaboration platform"
ARG APP_VERSION=0.6.1
LABEL version=${APP_VERSION}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DIGITALLIFE_HOME=/opt/digitallife \
    STORAGE_ROOT=/storage \
    DIGITALLIFE_RUN_ENV=docker

RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv curl wget ca-certificates git \
    tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim tesseract-ocr-chi-tra \
    file zip unzip sqlite3 iputils-ping tini \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p ${DIGITALLIFE_HOME} ${STORAGE_ROOT}
WORKDIR ${DIGITALLIFE_HOME}

COPY requirements.txt ${DIGITALLIFE_HOME}/requirements.txt
RUN python3 -m venv .venv \
    && .venv/bin/pip install --upgrade pip \
    && .venv/bin/pip install -r requirements.txt \
    && .venv/bin/pip install "markitdown[all]" \
    && rm -rf /root/.cache/pip

COPY src/ ${DIGITALLIFE_HOME}/src/
COPY assets/ ${DIGITALLIFE_HOME}/assets/
COPY --from=frontend-builder /build/frontend/dist ${DIGITALLIFE_HOME}/assets/frontend
COPY --from=frontend-builder /build/frontend-v2/dist ${DIGITALLIFE_HOME}/assets/frontend-v2

RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 digitallife \
    && mkdir -p ${STORAGE_ROOT} \
    && if [ ! -f ${STORAGE_ROOT}/setting.json ]; then \
        cp ${DIGITALLIFE_HOME}/assets/config_template.json ${STORAGE_ROOT}/setting.json; \
    fi \
    && chown -R digitallife:digitallife ${DIGITALLIFE_HOME} ${STORAGE_ROOT}

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/system/status.json || exit 1

USER digitallife
WORKDIR ${DIGITALLIFE_HOME}/src
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["../.venv/bin/python3", "backend_main.py", "--config-dir", "/storage"]
