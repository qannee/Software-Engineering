from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "QUAN 1 TOURISM API"
    API_V1_STR: str = "/api/v1"
    APP_ENV: str = "development"
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    POSTGRES_ENABLED: bool = False
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/quan1_tourism"
    REDIS_ENABLED: bool = False
    REDIS_URL: str = "redis://localhost:6379/0"
    JWT_SECRET: str = "local-development-secret-change-before-deployment"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    REFRESH_COOKIE_NAME: str = "q1_refresh"
    REFRESH_COOKIE_SAMESITE: str = "lax"
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "quan1-demo"
    WIKIPEDIA_LANGUAGE: str = "vi"
    AI_API_URL: str = ""
    AI_API_KEY: str = ""
    AI_MODEL: str = ""
    TRANSLATION_API_KEY: str = ""
    TTS_API_KEY: str = ""
    TTS_MODEL: str = "eleven_v3"
    TTS_VOICE_ID_VI: str = ""
    TTS_VOICE_ID_EN: str = ""
    AUDIO_DIRECTORY: str = "storage/audio"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    def validate_production(self) -> None:
        if self.APP_ENV.lower() != "production":
            return
        problems = []
        if len(self.JWT_SECRET) < 32 or self.JWT_SECRET == "local-development-secret-change-before-deployment":
            problems.append("JWT_SECRET must be a unique value with at least 32 characters")
        if len(self.ADMIN_PASSWORD) < 12 or self.ADMIN_PASSWORD == "quan1-demo":
            problems.append("ADMIN_PASSWORD must be changed to at least 12 characters")
        if not self.POSTGRES_ENABLED:
            problems.append("POSTGRES_ENABLED must be true")
        if not self.REDIS_ENABLED:
            problems.append("REDIS_ENABLED must be true for the distributed worker queue")
        if self.REDIS_ENABLED and not self.REDIS_URL.startswith("rediss://"):
            problems.append("Production REDIS_URL must use TLS (rediss://)")
        if not self.allowed_origins or "*" in self.allowed_origins:
            problems.append("CORS_ORIGINS must list the frontend origins")
        if any(not origin.startswith("https://") for origin in self.allowed_origins):
            problems.append("Production CORS_ORIGINS must use HTTPS")
        if self.REFRESH_COOKIE_SAMESITE.lower() not in {"lax", "strict", "none"}:
            problems.append("REFRESH_COOKIE_SAMESITE must be lax, strict, or none")
        if problems:
            raise RuntimeError("Invalid production configuration: " + "; ".join(problems))

    class Config:
        env_file = ".env"

settings = Settings()
