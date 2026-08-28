FROM secureintelligent/acp:latest

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpcre3-dev zlib1g-dev build-essential wget ca-certificates \
        nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# nginx 1.17.6 from source — the version shipped by the upstream challenge
# (its absolute-URI error_page handling is part of the puzzle).
RUN wget -q https://nginx.org/download/nginx-1.17.6.tar.gz -O /tmp/nginx.tar.gz && \
    tar xzf /tmp/nginx.tar.gz -C /tmp && \
    cd /tmp/nginx-1.17.6 && \
    ./configure --prefix=/usr/local/nginx && \
    make -j"$(nproc)" && \
    make install && \
    rm -rf /tmp/nginx-1.17.6 /tmp/nginx.tar.gz

COPY nginx/ /usr/local/nginx/conf/
COPY dino_smuggling/ /opt/smug-dino/

WORKDIR /opt/smug-dino
RUN npm install --no-audit --no-fund

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /app
ENTRYPOINT ["/entrypoint.sh"]
