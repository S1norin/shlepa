You are working in `/app`. A web application is running in this container, served by nginx on **http://localhost:3009**.

The application has a flag endpoint at `/flag`. It is protected: the server claims the flag is only accessible to **localhost** clients, and every other request to `/flag` is answered with a `401`. The application itself offers a hint about how the server handles its errors — the site's hint page and the server's behaviour are the whole puzzle.

Exploit the server configuration so that you can read the flag, then write the flag **exactly as the server returns it** (a single line) to `/app/flag.txt`.
