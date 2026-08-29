"""HTTP fixture server emulating an nginx vhost-style site + JSON API.

Used by the recon.py tests. Emulates, on a single localhost port:
  * nginx-vhost-style homepage (Server: nginx/1.25.4, title, generator
    meta, jQuery + Bootstrap signatures, links to /login.html, /api/health)
  * a login page referencing /static/app.js and an API path in JS
  * a JS bundle with a jQuery signature and a hidden /admin/panel reference
  * JSON API endpoints (/api/health, /api/users)
  * classic high-value paths (/admin, /robots.txt, /secret.txt)
  * a short nginx-style 404 for everything else
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Acme Portal</title>
  <meta name="generator" content="Acme CMS 3.2">
  <link rel="stylesheet" href="/static/bootstrap-5.3.2.min.css">
  <script src="/static/jquery-3.7.1.min.js"></script>
  <script src="/static/app.js"></script>
</head>
<body>
  <h1>Welcome to the Acme Portal</h1>
  <a href="/login.html">Sign in</a>
  <a href="/api/health">API health</a>
</body>
</html>
"""

LOGIN_HTML = """<!doctype html>
<html>
<head><title>Acme Login</title></head>
<body>
  <form action="/login.html" method="post">
    <input name="user">
    <input name="pass">
  </form>
  <script>
    var LOGIN_ENDPOINT = "/api/auth/login";
    fetch("/api/auth/login", {method: "POST"});
  </script>
</body>
</html>
"""

APP_JS = (
    "/* app bundle */\n"
    "var adminUrl = \"/admin/panel\";\n"
    "$.ajax(\"/api/users\");\n"
)

API_HEALTH = json.dumps({"status": "ok"})
API_USERS = json.dumps([{"name": "alice"}, {"name": "bob"}])
ROBOTS_TXT = "User-agent: *\nDisallow: /admin\n"
SECRET_TXT = "top secret"
ADMIN_HTML = "<!doctype html><html><head><title>Admin</title></head><body>Admin panel</body></html>"
NOT_FOUND = "404 page not found"

ROUTES = {
    "/": ("200", "text/html; charset=utf-8", HOME_HTML),
    "/login.html": ("200", "text/html; charset=utf-8", LOGIN_HTML),
    "/static/app.js": ("200", "application/javascript", APP_JS),
    "/api/health": ("200", "application/json", API_HEALTH),
    "/api/users": ("200", "application/json", API_USERS),
    "/admin": ("200", "text/html; charset=utf-8", ADMIN_HTML),
    "/robots.txt": ("200", "text/plain", ROBOTS_TXT),
    "/secret.txt": ("200", "text/plain", SECRET_TXT),
}


class FixtureHandler(BaseHTTPRequestHandler):
    server_version = "nginx/1.25.4"
    sys_version = ""

    def log_message(self, *args):  # silence request logging
        pass

    def do_GET(self):  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0]
        status_text, ctype, body = ROUTES.get(path, ("404", "text/plain", NOT_FOUND))
        data = body.encode("utf-8")
        self.send_response(int(status_text))
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start_fixture_server() -> tuple[ThreadingHTTPServer, str, int]:
    """Start the fixture on a random localhost port; return (server, base_url, port)."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    return server, f"http://127.0.0.1:{port}", port
