import asyncio
import logging
import sys
from fastapi import FastAPI, Request
from aiogram.types import Update
from .bot import get_dispatcher, Bot
from .config import settings
from .database import close_session

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    if settings.webhook_url:
        webhook_url = f"{settings.webhook_url.rstrip('/')}/webhook"
        await bot.set_webhook(webhook_url, drop_pending_updates=True)
        logging.info(f"Bot started in Webhook mode. Webhook set to: {webhook_url}")
    else:
        asyncio.create_task(dp.start_polling(bot))
        logging.info("Bot started in Polling mode.")
        
    yield
    
    # Shutdown logic
    if settings.webhook_url:
        await bot.delete_webhook()
        logging.info("Webhook deleted.")
    await bot.session.close()
    await close_session() # Закрываем общую сессию aiohttp

app = FastAPI(lifespan=lifespan)
bot = Bot(token=settings.telegram_bot_token)
dp = get_dispatcher()

@app.get("/")
async def index():
    return {"status": "ok", "message": "Chess CRM Bot is running"}

@app.post("/webhook")
async def webhook(request: Request):
    if not settings.webhook_url:
        return {"status": "error", "message": "Webhook is not configured"}
    try:
        update_json = await request.json()
        update = Update.model_validate(update_json, context={"bot": bot})
        await dp.feed_update(bot, update)
        return {"status": "ok"}
    except Exception as e:
        logging.error(f"Error processing webhook update: {e}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
