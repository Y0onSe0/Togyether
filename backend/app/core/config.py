from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://kdca_admin:kdca_pwd1@localhost:5555/kdca_db"
    OPENAI_API_KEY: str = ""
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 480
    HUGGINGFACE_TOKEN: str = ""
    DATA_GO_KR_API_KEY: str = ""  # 공공데이터포털 인증키 — .env 에만 설정
    DEEPGRAM_API_KEY: str = ""


settings = Settings()
