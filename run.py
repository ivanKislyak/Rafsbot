import asyncio
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from rafs_errors import MissingBotTokenError

load_dotenv()
BOT_TOKEN=os.getenv('BOT_TOKEN', default=None)
if not BOT_TOKEN:
    raise MissingBotTokenError()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())