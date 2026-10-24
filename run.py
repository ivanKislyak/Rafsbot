import asyncio
import os
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message
from rafs_errors import MissingBotTokenError

load_dotenv()
BOT_TOKEN=os.getenv('BOT_TOKEN', default=None)
if not BOT_TOKEN:
    raise MissingBotTokenError()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer('Привет')

async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        print('Exit')