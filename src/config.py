import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv(f"{os.path.dirname(__file__)}/.env")

class Settings(BaseSettings):
    # OpenAI 配置
    OPENAI_API_KEY: str
    OPENAI_MODEL: str
    OPENAI_PROVIDER: str
    OPENAI_BASE_URL: str

    THINKING_MODEL: str
    GEN_MODEL: str
    LITE_MODEL: str
    VISION_MODEL: str
    
    # 服务器配置
    SERVER_PORT: int = 5876
    
    # PostgreSQL 配置 (用于LangGraph checkpoint)
    # POSTGRES_HOST: str = "sh-postgres-c93lya14.sql.tencentcdb.com"
    POSTGRES_HOST: str = "postgresfb9e27de51dc.rds-pg.ivolces.com"
    # POSTGRES_PORT: int = 25561
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "aura-PostgreSQL"
    POSTGRES_USER: str = "root"
    POSTGRES_PASSWORD: str = "X1KxZeMkM#nobqKiq"
    POSTGRES_SCHEMA: str = "public"
    
    # 其他API配置
    TAVILY_API_KEY: str = ""
    JINA_API_KEY: str = ""
    BRAVE_SEARCH_API_KEY: str = ""
    SERPER_API_KEY: str = ""
    
    # 应用配置
    APP_NAME: str = "Creative Comparison Analysis Agent"
    DEBUG: bool = True
    RESPONSE_CALLBACK_URL: str = ""

    LOG_DIR: str = f"{os.path.dirname(__file__)}/../logs"
    class Config:
        env_file = ".env"

settings = Settings()
