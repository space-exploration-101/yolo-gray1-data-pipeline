FROM python:3.12-slim@sha256:804ddf3251a60bbf9c92e73b7566c40428d54d0e79d3428194edf40da6521286

ARG VCS_REF=uncommitted
LABEL org.opencontainers.image.title="yolo-gray1-data-pipeline" \
      org.opencontainers.image.description="Deterministic gray1 preprocessing for YOLO and FPGA camera inputs" \
      org.opencontainers.image.version="0.1.0-dev" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY docker/requirements.lock.txt /tmp/requirements.lock.txt
RUN python -m pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock.txt \
    && rm -f /tmp/requirements.lock.txt

COPY src/ /app/src/
COPY configs/ /app/configs/
COPY schemas/ /app/schemas/

# Numeric non-root identity; H200 Compose overrides this with ywang's 1012:1012.
USER 65532:65532

ENTRYPOINT ["python", "-m", "grayprep.cli"]
CMD ["list"]
