from urllib.parse import quote, unquote, urlparse

import httpx


class WikipediaAdapter:
    API = "https://{language}.wikipedia.org/w/api.php"

    @staticmethod
    def parse_article(value: str, default_language: str = "vi") -> tuple[str, str]:
        parsed = urlparse(value)
        if parsed.scheme:
            host = (parsed.hostname or "").lower()
            parts = host.split(".")
            if len(parts) < 3 or parts[-2:] != ["wikipedia", "org"] or parts[0] not in {"vi", "en"}:
                raise ValueError("Chỉ chấp nhận URL từ vi.wikipedia.org hoặc en.wikipedia.org")
            title = unquote(parsed.path.removeprefix("/wiki/")) if parsed.path.startswith("/wiki/") else ""
            if not title:
                raise ValueError("URL Wikipedia phải trỏ đến một bài viết")
            return parts[0], title.replace("_", " ")
        return default_language, value.replace("_", " ").strip()

    async def fetch_article_text(self, article: str, language: str = "vi") -> dict:
        language, title = self.parse_article(article, language)
        if not title:
            raise ValueError("Thiếu tên bài viết Wikipedia")
        params = {"action": "query", "prop": "extracts|revisions", "rvprop": "ids|timestamp", "explaintext": 1, "redirects": 1, "titles": title, "format": "json", "formatversion": 2}
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0), headers={"User-Agent": "Quan1Tourism/1.0 (educational project)"}) as client:
            response = await client.get(self.API.format(language=language), params=params)
            response.raise_for_status()
            pages = response.json().get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            raise ValueError("Không tìm thấy bài viết Wikipedia")
        page = pages[0]
        return {"title": page.get("title", title), "extract": page.get("extract", ""), "pageid": page.get("pageid"), "revision": (page.get("revisions") or [{}])[0].get("revid"), "timestamp": (page.get("revisions") or [{}])[0].get("timestamp"), "url": f"https://{language}.wikipedia.org/wiki/{quote(page.get('title', title).replace(' ', '_'))}", "language": language}
