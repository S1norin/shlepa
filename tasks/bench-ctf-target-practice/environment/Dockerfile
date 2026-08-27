FROM secureintelligent/acp:latest

WORKDIR /app

COPY target_practice /app/target_practice
COPY flag.txt /flag.txt

RUN chmod 755 /app/target_practice && chown root:root /flag.txt && chmod 600 /flag.txt
