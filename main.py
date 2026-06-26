"""YouTube Live Summary Agent 진입점."""
import asyncio
import sys
import uvicorn
from src.storage.database import init_db, get_setting
from src.scheduler.poller import run_polling_loop, set_broadcast
from src.server.app import app, broadcast
from src.pipeline.ai_client import update_config
from src.watcher.youtube_client import set_key as set_yt_key
from src.utils.logger import get_logger

logger = get_logger("main")


async def main():
    logger.info("YouTube Live Summary Agent 시작")
    await init_db()

    # DB에서 AI 설정 복원
    provider = await get_setting("ai.provider")
    model    = await get_setting("ai.model")
    api_key  = await get_setting("ai.api_key") or ""
    base_url = await get_setting("ai.base_url") or ""
    if provider:
        update_config(provider=provider, model=model, api_key=api_key, base_url=base_url)
        logger.info("AI 설정 로드: provider=%s model=%s", provider, model)

    yt_key = await get_setting("yt.api_key") or ""
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
