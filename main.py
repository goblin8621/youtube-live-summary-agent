"""YouTube Live Summary Agent 진입점."""
import asyncio
import sys
import uvicorn
from pathlib import Path
from src.storage import store
from src.storage.database import init_db
from src.storage import summary_store
from src.scheduler.poller import run_polling_loop, set_broadcast
from src.server.app import app, broadcast
from src.pipeline.ai_client import update_config
from src.watcher.youtube_client import set_key as set_yt_key
from src.utils.logger import get_logger
from src.config import settings

logger = get_logger("main")


async def main():
    logger.info("YouTube Live Summary Agent 시작")

    # DB 파일 존재 여부로 스토리지 모드 결정
    use_db = Path(settings.db_path).exists()
    store.init(use_db)

    if use_db:
        await init_db()
    else:
        summary_store.cleanup_old_summaries()

    # 설정 복원 (DB 또는 config.json)
    provider = await store.get_setting("ai.provider")
    model    = await store.get_setting("ai.model")
    api_key  = await store.get_setting("ai.api_key")
    base_url = await store.get_setting("ai.base_url")
    if provider:
        update_config(provider=provider, model=model, api_key=api_key, base_url=base_url)
        logger.info("AI 설정 로드: provider=%s model=%s", provider, model)

    yt_key = await store.get_setting("youtube.api_key") or await store.get_setting("yt.api_key")
    if yt_key:
        set_yt_key(yt_key)
        logger.info("YouTube API 키 로드 완료")

    set_broadcast(broadcast)

    # FastAPI 서버와 폴링 루프를 동시에 실행
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="warning")
    server = uvicorn.Server(config)

    await asyncio.gather(
        server.serve(),
        run_polling_loop(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("에이전트 종료")
        sys.exit(0)
