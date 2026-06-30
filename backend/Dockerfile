FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Pango and friends are WeasyPrint's native dependencies for invoice PDFs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b fonts-inter \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# Dependencies get their own layer, keyed on pyproject.toml only, so a source change
# reinstalls just the meterly package instead of every wheel.
COPY pyproject.toml ./
RUN pip install hatchling \
    && mkdir -p src/meterly && touch src/meterly/__init__.py \
    && pip install --no-build-isolation ".[pdf]"
COPY src ./src
RUN pip install --no-deps --no-build-isolation --force-reinstall .

COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts

RUN useradd --create-home --uid 10001 meterly
USER meterly

EXPOSE 8107
CMD ["uvicorn", "meterly.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8107"]
