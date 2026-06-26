FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY pyproject.toml README.md LICENSE constraints-verified.txt ./
COPY src ./src
RUN python -m pip install --upgrade pip wheel \
 && python -m pip wheel --constraint constraints-verified.txt --wheel-dir /wheels ".[full]"

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --create-home app
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-index --find-links=/wheels heavy-bulky-delivery-reliability \
 && rm -rf /wheels
COPY --chown=app:app configs ./configs
RUN mkdir -p /app/outputs && chown -R app:app /app/outputs
USER app
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -m heavy_bulky.cli capabilities >/dev/null || exit 1
CMD ["python", "-m", "heavy_bulky.cli", "full-pipeline", "--config", "configs/smoke.yaml", "--output-dir", "outputs/smoke"]
