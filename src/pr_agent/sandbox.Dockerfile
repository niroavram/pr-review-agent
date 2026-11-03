# pr-agent sandbox: the analyzers + pytest, run as uid 1000 with no network at runtime.
# Built by pr_agent.sandbox.ensure_image() with no build context (Dockerfile on stdin).
# Tool versions match the pr-agent venv (uv.lock) so local and Docker results agree.
FROM python:3.12-slim

ARG TARGETARCH
ARG GITLEAKS_VERSION=8.28.0

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SEMGREP_SEND_METRICS=off

RUN pip install \
        ruff==0.17.3 \
        bandit==1.9.4 \
        semgrep==1.183.0 \
        pytest==9.2.0

# gitleaks release binary; Docker's TARGETARCH (amd64/arm64) -> gitleaks' asset names (x64/arm64).
# (python:slim has no curl/wget, so the interpreter downloads it.)
RUN case "${TARGETARCH:-amd64}" in \
        amd64) arch=x64 ;; \
        arm64) arch=arm64 ;; \
        *) echo "unsupported arch ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && url="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_${arch}.tar.gz" \
    && python -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], '/tmp/gitleaks.tgz')" "$url" \
    && tar -xzf /tmp/gitleaks.tgz -C /usr/local/bin gitleaks \
    && rm /tmp/gitleaks.tgz \
    && gitleaks version

RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin sandbox
USER 1000:1000
WORKDIR /work
