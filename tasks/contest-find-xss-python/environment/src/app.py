"""Tiny framework-free sketch of the synthetic note-preview endpoint."""

from urllib.parse import parse_qs


def preview_note(query_string: str) -> tuple[int, dict[str, str], bytes]:
    note = parse_qs(query_string).get("note", [""])[0]
    page = f"<main><h1>Preview</h1><p>{note}</p></main>"
    return 200, {"Content-Type": "text/html; charset=utf-8"}, page.encode()


ROUTES = {"GET /preview": preview_note}
