from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    youtube_api_key: str = ""
    anthropic_api_key: str
    claude_model: str = "claude-sonnet-4-6"

    slack_bot_token: str = ""
    slack_channel_id: str = "#youtube-summaries"

    notion_token: str = ""
    notion_database_id: str = ""

    poll_interval_seconds: int = 300
    chat_collect_interval_seconds: int = 30
    db_path: str = "./data/agent.db"
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def slack_enabled(self) -> bool:
        return bool(self.slack_bot_token)

    @property
    def notion_enabled(self) -> bool:
        return bool(self.notion_token and self.notion_database_id)


settings = Settings()
