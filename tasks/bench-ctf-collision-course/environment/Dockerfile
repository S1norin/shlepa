FROM secureintelligent/acp:latest

WORKDIR /app
RUN /app/.venv/bin/uv pip install --python /app/.venv/bin/python pycryptodome
COPY challenge/ /app/challenge/
