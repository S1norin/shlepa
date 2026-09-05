FROM secureintelligent/acp:latest
RUN apt-get update && apt-get install -y --no-install-recommends golang-go && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY app/ /app/
