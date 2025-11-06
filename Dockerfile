FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# copy metadata and source BEFORE editable install
COPY pyproject.toml ./
COPY src ./src

RUN pip install --upgrade pip && pip install -e ".[dev]"

# bring the rest (alembic, config, etc.)
COPY . .

# Create media directory structure
RUN mkdir -p /app/media/videos /app/media/clips

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
