from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # .env 파일을 찾아 UTF-8 인코딩으로 읽도록 설정
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

    # Qdrant 설정 변수들
    # .env 파일에 있는 변수 일므과 정확히 일치해야함
    QDRANT_URL: str
    QDRANT_API_KEY: str
    QDRANT_COLLECTION: str = "feedback_current" # .env에 값이 없으면 이 기본값을 사용

     # 앞으로 추가될 다른 설정들...
    # PG_URL: str
    # REDIS_URL: str
    # ANTHROPIC_API_KEY: str

# 다른 파일에서 import해서 사용할 설정 객체(인스턴스)
settings = Settings()

# 로드되었는지 간단히 확인
print("Settings loaded successfully!")
print(f"Qdrant URL: {settings.QDRANT_URL}")

PG_URL = "postgresql+psycopg2://user:pass@localhost:5432/app"  # 임시
REDIS_URL = "redis://localhost:6379/0"


