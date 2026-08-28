FROM secureintelligent/acp:latest

WORKDIR /app
COPY app/ .
RUN /app/.venv/bin/uv pip install --python /app/.venv/bin/python \
    pytest pytest-mock jinja2
