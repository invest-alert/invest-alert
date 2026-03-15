from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_NAME: str = "Invest Alert API"
    APP_ENV: str = "dev"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    WATCHLIST_MAX_STOCKS: int = 15
    DAILY_CONTEXT_ARTICLE_LIMIT: int = 3
    ENABLE_CONTEXT_SCHEDULER: bool = False
    CONTEXT_HARVEST_HOUR: int = 17
    CONTEXT_HARVEST_MINUTE: int = 15
    CONTEXT_HARVEST_TIMEZONE: str = "Asia/Kolkata"
    ENABLE_SUMMARY_WORKER: bool = True
    SUMMARY_WORKER_INTERVAL_SECONDS: int = 10
    SUMMARY_WORKER_BATCH_SIZE: int = 3
    SUMMARY_CACHE_TTL_SECONDS: int = 86400
    SUMMARY_FETCH_TIMEOUT_SECONDS: int = 15
    SUMMARY_SENTENCE_COUNT: int = 3
    SUMMARY_MAX_INPUT_CHARS: int = 6000
    SUMMARY_EXCERPT_CHARS: int = 320

    CORS_ALLOW_ORIGINS: str = (
        "http://localhost:3000,"
        "http://127.0.0.1:3000,"
        "http://localhost:5173,"
        "http://127.0.0.1:5173"
    )
    CORS_ALLOW_METHODS: str = "*"
    CORS_ALLOW_HEADERS: str = "*"
    CORS_ALLOW_CREDENTIALS: bool = True
    MARKETAUX_BASE_URL: str = "https://api.marketaux.com/v1"
    MARKETAUX_API_KEY: str | None = None
    MARKETAUX_NEWS_LANGUAGE: str = "en"
    MARKETAUX_NEWS_COUNTRIES: str = "in"
    MARKETAUX_NEWS_LIMIT: int = 6
    GOOGLE_NEWS_RSS_BASE_URL: str = "https://news.google.com/rss/search"
    GOOGLE_NEWS_HL: str = "en-IN"
    GOOGLE_NEWS_GL: str = "IN"
    GOOGLE_NEWS_CEID: str = "IN:en"
    GOOGLE_NEWS_LOOKBACK_DAYS: int = 7
    GOOGLE_NEWS_REQUEST_LIMIT: int = 10
    DATABASE_URL: str
    JWT_ACCESS_SECRET: str
    JWT_REFRESH_SECRET: str

    @staticmethod
    def _parse_csv(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    @property
    def cors_allow_origins_list(self) -> list[str]:
        return self._parse_csv(self.CORS_ALLOW_ORIGINS)

    @property
    def cors_allow_methods_list(self) -> list[str]:
        if self.CORS_ALLOW_METHODS.strip() == "*":
            return ["*"]
        return self._parse_csv(self.CORS_ALLOW_METHODS)

    @property
    def cors_allow_headers_list(self) -> list[str]:
        if self.CORS_ALLOW_HEADERS.strip() == "*":
            return ["*"]
        return self._parse_csv(self.CORS_ALLOW_HEADERS)


settings = Settings()
