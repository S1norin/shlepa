FROM secureintelligent/acp:latest
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY app/ /app/
RUN npm ci --ignore-scripts
