You are working in `/app`. A synthetic site's nginx configuration and deployed
filesystem are preserved under `/app/site/`. No service needs to be started.

Trace the include and location rules to determine which supposedly private
backup becomes web-readable because of a misconfigured `alias`. Recover the
planted `flag{...}` string and write it as one line to `/app/flag.txt`. Ignore
decoy public files. The puzzle is completely offline.
