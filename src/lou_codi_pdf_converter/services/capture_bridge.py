from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from html import unescape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..space_library import (
    CodiSpace,
    ai_conversation_kind,
    load_spaces,
    new_identifier,
    resource_from_drop,
    save_spaces,
)

CAPTURE_BRIDGE_HOST = "127.0.0.1"
CAPTURE_BRIDGE_PORT = 47632
_LIBRARY_LOCK = threading.RLock()


def google_photos_title(url: str) -> str:
    if urlparse(url).hostname != "photos.google.com":
        return ""
    try:
        request = Request(url, headers={"User-Agent": "LouCodiCapture/0.1"})
        with urlopen(request, timeout=5) as response:
            html = response.read(2_000_000).decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return ""
    patterns = (
        r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)',
        r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']og:title["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return unescape(match.group(1)).strip()
    return ""


def _generic_google_photos_title(title: str) -> bool:
    normalized = title.replace("\xa0", " ").casefold().strip()
    return not normalized or normalized in {
        "album google photos",
        "albums - google photos",
        "albums – google photos",
        "google photos",
    }


def list_capture_spaces() -> list[dict[str, str]]:
    with _LIBRARY_LOCK:
        return [
            {
                "id": space.identifier,
                "title": space.title,
                "group": space.group,
                "account": space.account_email,
            }
            for space in load_spaces()
        ]


def list_capture_accounts() -> list[str]:
    return sorted(
        {space["account"] for space in list_capture_spaces() if space["account"]},
        key=str.casefold,
    )


def create_capture_space(title: str, account_email: str = "") -> dict[str, str]:
    cleaned = title.strip()
    if not cleaned:
        raise ValueError("Le nom de l’espace est vide.")
    with _LIBRARY_LOCK:
        spaces = load_spaces()
        existing = next((space for space in spaces if space.title.casefold() == cleaned.casefold()), None)
        if existing is not None:
            return {"id": existing.identifier, "title": existing.title}
        account = account_email.strip()
        space = CodiSpace(
            identifier=new_identifier(),
            title=cleaned,
            account_email=account,
            group="Personnel" if account.casefold().endswith("@gmail.com") else "Professionnel",
        )
        spaces.append(space)
        save_spaces(spaces)
    return {"id": space.identifier, "title": space.title}


def capture_url(
    space_id: str,
    url: str,
    title: str = "",
    excerpt: str = "",
    kind: str = "",
) -> dict[str, object]:
    if not url.startswith(("http://", "https://")):
        raise ValueError("Seules les adresses HTTP et HTTPS sont acceptées.")
    value = f"{title.strip()} <{url}>" if title.strip() else url
    resource = resource_from_drop(value)
    if resource is None:
        raise ValueError("Cette adresse ne peut pas être ajoutée.")
    if resource.kind == "google_photos_album" and _generic_google_photos_title(resource.title):
        resource.title = google_photos_title(resource.target) or resource.title
    cleaned_excerpt = excerpt.strip()
    if kind == "ai_knowledge" and cleaned_excerpt:
        resource.kind = ai_conversation_kind(resource.target, knowledge=True)
        resource.details = cleaned_excerpt
        resource.title = title.strip() or cleaned_excerpt[:120]
    with _LIBRARY_LOCK:
        spaces = load_spaces()
        space = next((item for item in spaces if item.identifier == space_id), None)
        if space is None:
            raise ValueError("L’espace demandé n’existe plus.")
        duplicate = next(
            (
                item
                for item in space.resources
                if item.target == resource.target
                and (not resource.kind.endswith("_knowledge") or item.details == resource.details)
            ),
            None,
        )
        if duplicate is not None:
            if (
                resource.kind == "google_photos_album"
                and duplicate.title != resource.title
                and not _generic_google_photos_title(resource.title)
            ):
                duplicate.title = resource.title
                save_spaces(spaces)
            return {"added": False, "space": space.title, "resource": duplicate.title}
        resource.account_email = space.account_email
        space.resources.append(resource)
        save_spaces(spaces)
    return {"added": True, "space": space.title, "resource": resource.title}


class CaptureBridge:
    def __init__(self, on_open: Callable[[str], None] | None = None) -> None:
        self.on_open = on_open
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if self._server is not None:
            return True
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def do_OPTIONS(self) -> None:
                self.send_response(HTTPStatus.NO_CONTENT)
                self._cors_headers()
                self.end_headers()

            def do_GET(self) -> None:
                if self.path == "/status":
                    self._json({"ok": True, "name": "Lou Còdi Capture"})
                elif self.path == "/spaces":
                    self._json(
                        {
                            "spaces": list_capture_spaces(),
                            "accounts": list_capture_accounts(),
                        }
                    )
                else:
                    self._json({"error": "Adresse inconnue."}, HTTPStatus.NOT_FOUND)

            def do_POST(self) -> None:
                if not self._trusted_origin():
                    self._json({"error": "Origine non autorisée."}, HTTPStatus.FORBIDDEN)
                    return
                try:
                    payload = self._payload()
                    if self.path == "/capture":
                        result = capture_url(
                            str(payload.get("spaceId", "")),
                            str(payload.get("url", "")),
                            str(payload.get("title", "")),
                            str(payload.get("excerpt", "")),
                            str(payload.get("kind", "")),
                        )
                        self._json(result)
                    elif self.path == "/spaces":
                        self._json(
                            create_capture_space(
                                str(payload.get("title", "")),
                                str(payload.get("account", "")),
                            )
                        )
                    elif self.path == "/open":
                        space_id = str(payload.get("spaceId", ""))
                        if bridge.on_open is not None:
                            bridge.on_open(space_id)
                        self._json({"opened": True})
                    else:
                        self._json({"error": "Adresse inconnue."}, HTTPStatus.NOT_FOUND)
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

            def _payload(self) -> dict:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 64_000:
                    raise ValueError("La requête est trop volumineuse.")
                raw = self.rfile.read(length)
                value = json.loads(raw.decode("utf-8") or "{}")
                if not isinstance(value, dict):
                    raise TypeError("Le contenu de la requête est incorrect.")
                return value

            def _json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self._cors_headers()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _cors_headers(self) -> None:
                origin = self.headers.get("Origin", "")
                if origin.startswith(("chrome-extension://", "moz-extension://")):
                    self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

            def _trusted_origin(self) -> bool:
                origin = self.headers.get("Origin", "")
                return not origin or origin.startswith(
                    ("chrome-extension://", "moz-extension://")
                )

            def log_message(self, _format: str, *_args: object) -> None:
                return

        try:
            self._server = ThreadingHTTPServer(
                (CAPTURE_BRIDGE_HOST, CAPTURE_BRIDGE_PORT), Handler
            )
        except OSError:
            self._server = None
            return False
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None
