# Local package index. Stdlib-only server; no third-party deps, no build step.
FROM python:3.12-slim
WORKDIR /srv
COPY server.py /srv/server.py
ENV PACKAGES_DIR=/packages PORT=8080 HOST=0.0.0.0
EXPOSE 8080
CMD ["python", "/srv/server.py"]
