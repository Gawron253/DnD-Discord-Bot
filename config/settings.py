import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    discord_bot_token: str = os.getenv("DISCORD_BOT_TOKEN", "")
    discord_guild_id: str = os.getenv("DISCORD_GUILD_ID", "")
    
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    
    ai_provider: str = os.getenv("AI_PROVIDER", "gemini")
    default_ai_model: str = os.getenv("DEFAULT_AI_MODEL", "gemini-3.7-flash")
    gemini_thinking_budget: Optional[int] = int(os.getenv("GEMINI_THINKING_BUDGET", "0")) if os.getenv("GEMINI_THINKING_BUDGET") is not None else 0
    gemini_include_thoughts: bool = os.getenv("GEMINI_INCLUDE_THOUGHTS", "false").lower() in ("true", "1", "yes")
    gemini_temperature: float = float(os.getenv("GEMINI_TEMPERATURE", "0.70"))
    
    database_url: str = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{BASE_DIR}/data/dnd_campaign.db")
    chroma_persist_dir: str = os.getenv("CHROMA_PERSIST_DIR", str(BASE_DIR / "data" / "chroma_db"))
    
    auto_sync_channels: bool = True
    enable_scene_images: bool = False

settings = Settings()
