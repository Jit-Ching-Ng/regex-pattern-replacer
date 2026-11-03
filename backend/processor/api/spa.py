"""Serves the built React single-page app for any non-API route."""
from functools import lru_cache

from django.conf import settings
from django.http import HttpRequest, HttpResponse


@lru_cache(maxsize=1)
def _read_index() -> str | None:
    index = settings.FRONTEND_DIST_DIR / "index.html"
    return index.read_text(encoding="utf-8") if index.exists() else None


def spa_index(request: HttpRequest) -> HttpResponse:
    html = _read_index()
    if html is None:
        return HttpResponse(
            "The frontend build was not found. In development run the Vite dev server "
            "(cd frontend && npm run dev) and open http://localhost:5173.",
            content_type="text/plain",
            status=404,
        )
    return HttpResponse(html)
