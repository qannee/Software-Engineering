from datetime import datetime

from app.repositories.poi_repository import POIRepository


class RuntimeStore:
    def __init__(self):
        self.pois = {poi["id"]: poi for poi in POIRepository.demo_data()}
        self.contents: dict[str, dict] = {}
        self.tasks: dict[str, dict] = {}
        self.active_tasks: set[str] = set()
        self.localizations: dict[str, dict[str, str]] = {}
        self.audio: dict[str, dict[str, dict]] = {}
        self.consents: dict[str, bool] = {}
        self.analytics: list[dict] = []
        self.audit: list[dict] = []
        self.users: dict[str, dict] = {}
        self.user_favorites: dict[str, set[str]] = {}
        self.revoked_tokens: dict[str, datetime] = {}
        self.refresh_tokens: dict[str, dict] = {}


store = RuntimeStore()
