FROM secureintelligent/acp:latest

WORKDIR /app
RUN /app/.venv/bin/uv pip install --python /app/.venv/bin/python xdis
COPY challenge/sourcery.zip /app/sourcery.zip
