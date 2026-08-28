#!/usr/bin/env bash
# Start the smug-dino services (Node app + nginx), then keep the container
# alive even if the agent kills one of them.
set -e

cd /opt/smug-dino
node app.js &
/usr/local/nginx/sbin/nginx

tail -f /dev/null
