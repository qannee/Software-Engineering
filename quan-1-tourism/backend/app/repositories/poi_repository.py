from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.poi import POIRecord
from app.repositories.demo_pois import extra_demo_data


class POIRepository:
    def __init__(self, session: AsyncSession | None):
        self.session = session

    @staticmethod
    def demo_data():
        return [
            {"id": "demo-cho-ben-thanh", "title": "Chợ Bến Thành", "title_en": "Ben Thanh Market", "slug": "cho-ben-thanh", "category": "Chợ & ẩm thực", "location": {"type": "Point", "coordinates": [106.698, 10.772]}, "geofence_radius": 80, "summary_vi": "Chợ Bến Thành là một trong những biểu tượng lâu đời của Thành phố Hồ Chí Minh. Ngôi chợ nổi bật với tháp đồng hồ ở cửa Nam và các gian hàng ẩm thực, quà lưu niệm, đặc sản địa phương.", "summary_en": "Ben Thanh Market is one of Ho Chi Minh City’s best-known landmarks, with its south entrance clock tower and lively stalls for local food, souvenirs and specialties.", "status": "PUBLISHED", "source_ref": {"name": "Wikipedia", "url": "https://vi.wikipedia.org/wiki/Ch%E1%BB%A3_B%E1%BA%BFn_Th%C3%A0nh"}},
            {"id": "demo-nha-tho-duc-ba", "title": "Nhà thờ Đức Bà", "title_en": "Notre-Dame Cathedral Basilica", "slug": "nha-tho-duc-ba", "category": "Kiến trúc", "location": {"type": "Point", "coordinates": [106.699, 10.7797]}, "geofence_radius": 80, "summary_vi": "Nhà thờ chính tòa Đức Bà Sài Gòn là công trình kiến trúc tiêu biểu tại trung tâm thành phố, được xây dựng vào cuối thế kỷ 19. Hai tháp chuông và mặt tiền gạch đỏ tạo nên dấu ấn đặc biệt.", "summary_en": "Notre-Dame Cathedral Basilica of Saigon is a landmark in the city centre. Built in the late nineteenth century, its twin bell towers and red-brick façade are distinctive.", "status": "PUBLISHED", "source_ref": {"name": "Wikipedia", "url": "https://vi.wikipedia.org/wiki/Nh%C3%A0_th%E1%BB%9D_Ch%C3%ADnh_t%C3%B2a_%C4%90%E1%BB%A9c_B%C3%A0_S%C3%A0i_G%C3%B2n"}},
            {"id": "demo-buu-dien", "title": "Bưu điện Trung tâm Sài Gòn", "title_en": "Saigon Central Post Office", "slug": "buu-dien-trung-tam", "category": "Kiến trúc", "location": {"type": "Point", "coordinates": [106.7009, 10.7798]}, "geofence_radius": 60, "summary_vi": "Bưu điện Trung tâm Sài Gòn là công trình kiến trúc nổi bật gần Nhà thờ Đức Bà. Không gian bên trong gây ấn tượng với mái vòm cao và các bản đồ lịch sử.", "summary_en": "Saigon Central Post Office is a striking historic building near the cathedral, with a high vaulted ceiling and old maps inside.", "status": "PUBLISHED", "source_ref": {"name": "Wikipedia", "url": "https://vi.wikipedia.org/wiki/B%C6%B0u_%C4%91i%E1%BB%87n_Trung_t%C3%A2m_S%C3%A0i_G%C3%B2n"}},
            {"id": "demo-dinh-doc-lap", "title": "Dinh Độc Lập", "title_en": "Independence Palace", "slug": "dinh-doc-lap", "category": "Di tích lịch sử", "location": {"type": "Point", "coordinates": [106.6953, 10.777]}, "geofence_radius": 90, "summary_vi": "Dinh Độc Lập là di tích lịch sử và kiến trúc nằm giữa khuôn viên nhiều cây xanh, lưu giữ nhiều không gian nguyên bản gắn với lịch sử Việt Nam hiện đại.", "summary_en": "Independence Palace is a historic and architectural landmark set among leafy grounds, with preserved rooms tied to modern Vietnamese history.", "status": "PUBLISHED", "source_ref": {"name": "Wikipedia", "url": "https://vi.wikipedia.org/wiki/Dinh_%C4%90%E1%BB%99c_L%E1%BA%ADp"}},
            {"id": "demo-pho-di-bo", "title": "Phố đi bộ Nguyễn Huệ", "title_en": "Nguyen Hue Walking Street", "slug": "pho-di-bo-nguyen-hue", "category": "Không gian công cộng", "location": {"type": "Point", "coordinates": [106.7022, 10.7745]}, "geofence_radius": 100, "summary_vi": "Phố đi bộ Nguyễn Huệ nối khu vực trụ sở Ủy ban Nhân dân Thành phố với bến Bạch Đằng. Đây là không gian công cộng sôi động, thường diễn ra các hoạt động văn hóa.", "summary_en": "Nguyen Hue Walking Street connects City Hall with Bach Dang Wharf and hosts cultural activities along a lively public boulevard.", "status": "PUBLISHED", "source_ref": {"name": "Wikipedia", "url": "https://vi.wikipedia.org/wiki/Ph%E1%BB%91_%C4%91i_b%E1%BB%99_Nguy%E1%BB%85n_Hu%E1%BB%87"}},
        ] + extra_demo_data()

    @staticmethod
    def serialize(record: POIRecord) -> dict:
        return {
            "id": record.id,
            "title": record.title,
            "title_en": record.title_en,
            "slug": record.slug,
            "category": record.category,
            "address": record.address,
            "opening_hours": record.opening_hours,
            "location": {"type": "Point", "coordinates": [record.longitude, record.latitude]},
            "geofence_radius": record.geofence_radius,
            "summary_vi": record.summary_vi,
            "summary_en": record.summary_en,
            "status": record.status,
            "source_ref": record.source_ref,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }

    async def get_by_id(self, poi_id: str):
        if self.session is None:
            from app.services.runtime_store import store

            return store.pois.get(poi_id)
        record = await self.session.get(POIRecord, poi_id)
        return self.serialize(record) if record else None

    async def list_published(self):
        if self.session is None:
            from app.services.runtime_store import store

            return [poi for poi in store.pois.values() if poi.get("status") == "PUBLISHED"]
        result = await self.session.scalars(select(POIRecord).where(POIRecord.status == "PUBLISHED").order_by(POIRecord.title))
        return [self.serialize(record) for record in result.all()]

    async def create(self, poi_data: dict):
        if self.session is None:
            from app.services.runtime_store import store

            record = {"id": str(uuid4()), "title": poi_data["title"], "title_en": poi_data.get("title_en"), "slug": poi_data["slug"], "category": poi_data.get("category"), "address": poi_data.get("address"), "opening_hours": poi_data.get("opening_hours"), "location": {"type": "Point", "coordinates": [poi_data["longitude"], poi_data["latitude"]]}, "geofence_radius": poi_data.get("geofence_radius", 30), "summary_vi": poi_data.get("summary_vi"), "summary_en": poi_data.get("summary_en"), "status": "DRAFT", "source_ref": {"name": "Wikipedia", "url": str(poi_data["wikipedia_url"])} if poi_data.get("wikipedia_url") else None}
            store.pois[record["id"]] = record
            return record["id"]
        record = POIRecord(
            id=str(uuid4()),
            title=poi_data["title"],
            category=poi_data.get("category"),
            address=poi_data.get("address"),
            opening_hours=poi_data.get("opening_hours"),
            slug=poi_data.get("slug") or f"poi-{uuid4().hex[:12]}",
            latitude=poi_data["latitude"],
            longitude=poi_data["longitude"],
            geofence_radius=poi_data.get("geofence_radius") or 30,
            source_ref=poi_data.get("source_ref"),
        )
        if poi_data.get("title_en"):
            record.title_en = poi_data["title_en"]
        if poi_data.get("summary_vi"):
            record.summary_vi = poi_data["summary_vi"]
        if poi_data.get("summary_en"):
            record.summary_en = poi_data["summary_en"]
        if poi_data.get("wikipedia_url"):
            record.source_ref = {"name": "Wikipedia", "url": str(poi_data["wikipedia_url"])}
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record.id

    async def list_all(self):
        if self.session is None:
            from app.services.runtime_store import store

            return list(store.pois.values())
        records = await self.session.scalars(select(POIRecord).order_by(POIRecord.created_at.desc()))
        return [self.serialize(record) for record in records.all()]

    async def update(self, poi_id: str, changes: dict):
        if self.session is None:
            from app.services.runtime_store import store

            record = store.pois.get(poi_id)
            if record is None:
                return None
            for key, value in changes.items():
                if key in {"latitude", "longitude"}:
                    index = 1 if key == "latitude" else 0
                    record["location"]["coordinates"][index] = value
                elif key == "wikipedia_url":
                    record["source_ref"] = {"name": "Wikipedia", "url": str(value)} if value else None
                else:
                    record[key] = value
            return record
        record = await self.session.get(POIRecord, poi_id)
        if record is None:
            return None
        for key, value in changes.items():
            if key in {"latitude", "longitude"}:
                setattr(record, key, value)
            elif key == "wikipedia_url":
                record.source_ref = {"name": "Wikipedia", "url": str(value)} if value else None
            elif hasattr(record, key):
                setattr(record, key, value)
        await self.session.commit()
        await self.session.refresh(record)
        return self.serialize(record)

    async def delete(self, poi_id: str) -> bool:
        if self.session is None:
            from app.services.runtime_store import store

            return store.pois.pop(poi_id, None) is not None
        record = await self.session.get(POIRecord, poi_id)
        if record is None:
            return False
        await self.session.delete(record)
        await self.session.commit()
        return True
