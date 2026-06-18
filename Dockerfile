FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git nodejs npm openssh-client postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ARG CODEX_CLI_VERSION=0.136.0
RUN npm install -g "@openai/codex@${CODEX_CLI_VERSION}"

COPY requirements.txt pyproject.toml ./
COPY scripts ./scripts
COPY src ./src
COPY tests ./tests
RUN pip install --default-timeout=120 --retries=8 --no-cache-dir -r requirements.txt \
    && pip install --default-timeout=120 --retries=8 --no-cache-dir -e .

ENTRYPOINT ["llm-wiki"]
CMD ["api"]
