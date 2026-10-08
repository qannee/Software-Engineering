from pydantic import BaseModel, Field, HttpUrl, field_validator


class AdminLogin(BaseModel):
    username: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=1, max_length=200)


class UserRegister(BaseModel):
    username: str = Field(min_length=3, max_length=160, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=200)

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Mật khẩu không được vượt quá 72 byte")
        return value


class POIUpsert(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    title_en: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=80)
    address: str | None = Field(default=None, max_length=300)
    opening_hours: str | None = Field(default=None, max_length=300)
    slug: str = Field(min_length=2, max_length=220, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    geofence_radius: float = Field(default=30, gt=0, le=1000)
    summary_vi: str | None = None
    summary_en: str | None = None
    wikipedia_url: HttpUrl | None = None


class POIPatch(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    title_en: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=80)
    address: str | None = Field(default=None, max_length=300)
    opening_hours: str | None = Field(default=None, max_length=300)
    slug: str | None = Field(default=None, min_length=2, max_length=220, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    geofence_radius: float | None = Field(default=None, gt=0, le=1000)
    summary_vi: str | None = None
    summary_en: str | None = None
    wikipedia_url: HttpUrl | None = None


class SourceRequest(BaseModel):
    wikipedia_url: HttpUrl


class DraftReview(BaseModel):
    script_vi: str = Field(min_length=20, max_length=10000)
    review_note: str | None = Field(default=None, max_length=2000)


class LocalizationInput(BaseModel):
    locale: str = Field(pattern=r"^(vi-VN|en-US)$")
    script: str = Field(min_length=20, max_length=10000)


class ConsentInput(BaseModel):
    accepted: bool
    token: str | None = None


class AnalyticsInput(BaseModel):
    consent_token: str
    session_id: str = Field(min_length=8, max_length=80)
    event_type: str = Field(pattern=r"^(poi_view|narration_started|narration_completed|language_changed|offline_downloaded)$")
    poi_id: str | None = None
    metadata: dict = Field(default_factory=dict)


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=160)
    password: str = Field(min_length=12, max_length=200)
    role: str = Field(pattern=r"^(ADMIN|REVIEWER)$")
