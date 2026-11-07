# The "target" container: a clean environment that executes the agent's install
# commands. Its pip is pointed at the LOCAL index only (see docker-compose.yml),
# so it can never reach public PyPI. The als-shim is installed so the same
# container demonstrates both the unguarded install and the blocked install.
FROM python:3.12-slim
WORKDIR /work
COPY dist/ /tmp/als_dist/
# Install the shim from the locally-built wheel (offline). If no wheel is mounted,
# the image still builds; the demo script installs it at run time.
RUN pip install --no-index --find-links=/tmp/als_dist agentloop-sec 2>/dev/null || true
ENV PIP_INDEX_URL=http://registry:8080/simple \
    PIP_TRUSTED_HOST=registry \
    ALS_PYPI_BASE=http://registry:8080 \
    ALS_SHIM_DB=/work/shim.sqlite
CMD ["sleep", "infinity"]
