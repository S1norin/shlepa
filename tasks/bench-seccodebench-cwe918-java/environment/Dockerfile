FROM secureintelligent/acp:latest
RUN apt-get update && apt-get install -y --no-install-recommends default-jdk maven && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY app/ /app/
RUN mvn -q -DskipTests dependency:go-offline
RUN mvn -q test && rm -rf /app/src/test /app/target
