FROM python:3.12.10-slim
WORKDIR /app
COPY requirements.lock pyproject.toml ./
RUN --mount=type=bind,from=crm_wheels,target=/wheels \
    cd /wheels && sha256sum -c SHA256SUMS && \
    pip install --no-cache-dir --no-index --find-links=/wheels -r /app/requirements.lock
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
COPY fixtures ./fixtures
RUN pip install --no-cache-dir --no-deps --no-build-isolation . \
    && chmod -R a+rX /app \
    && useradd --uid 10002 --create-home crm
USER crm
CMD ["uvicorn", "personal_crm.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
