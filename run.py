import asyncio
import os
import logging
import constants
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command, or_f
from aiogram.types import Message
from rafs_errors import MissingBotTokenError
from weather import get_weather_message

load_dotenv()
BOT_TOKEN=os.getenv('BOT_TOKEN', default=None)
if not BOT_TOKEN:
    raise MissingBotTokenError()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer('Привет')

@dp.message(or_f(Command('weather'), F.text.lower().strip().in_(constants.WEATHER_COMMANDS)))
async def cmd_weather(message: Message):
    await message.answer(await get_weather_message())

@dp.message(or_f(Command('help'), F.text.lower().strip().in_(constants.HELP_COMMANDS)))
async def get_help(message: Message):
    await message.answer('Привет, я бот RAFS. Сейчас у меня мало команд. Скоро добавим показ погоды')

@dp.message(F.photo)
async def get_photo(message: Message):
    await message.reply_dice()

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