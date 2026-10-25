import asyncio
import logging
import math
import time

import httpx


logger = logging.getLogger(__name__)
API_URL = "https://api.open-meteo.com/v1/forecast"
CURRENT_FIELDS = "temperature_2m,apparent_temperature,weather_code,is_day"
CACHE_SECONDS = 5 * 60
UNAVAILABLE_MESSAGE = "Сейчас не удалось получить погоду. Попробуйте чуть позже."

CITIES = [
    ("Абакан", 53.71540, 91.42593),
    ("Астана", 51.18010, 71.44598),
    ("Братск", 56.13250, 101.61417),
    ("Ивантеевка", 55.97111, 37.92083),
    ("Ижевск", 56.85225, 53.19862),
    ("Каменское", 48.51716, 34.60617),
    ("Кишинёв", 47.00902, 28.85938),
    ("Koblenz", 50.35357, 7.57883),
    ("Красноярск", 56.03742, 92.93136),
    ("Мариуполь", 47.09514, 37.54131),
    ("Москва", 55.75204, 37.61781),
    ("Николаев", 46.97625, 31.99296),
    ("Новосибирск", 55.02259, 82.93175),
    ("Семей", 50.42064, 80.25025),
    ("Сыктывкар", 61.66393, 50.81630),
    ("Химки", 55.90010, 37.42848),
]

WEATHER_CODES = {
    0: ("☀️", "ясно"),
    1: ("🌤", "преимущественно ясно"),
    2: ("⛅", "переменная облачность"),
    3: ("☁️", "пасмурно"),
    45: ("🌫", "туман"),
    48: ("🌫", "туман"),
    51: ("🌦", "морось"),
    53: ("🌦", "морось"),
    55: ("🌦", "морось"),
    56: ("🧊", "ледяные осадки"),
    57: ("🧊", "ледяные осадки"),
    61: ("🌧", "дождь"),
    63: ("🌧", "дождь"),
    65: ("🌧", "дождь"),
    66: ("🧊", "ледяные осадки"),
    67: ("🧊", "ледяные осадки"),
    71: ("❄️", "снег"),
    73: ("❄️", "снег"),
    75: ("❄️", "снег"),
    77: ("❄️", "снег"),
    80: ("🌧", "ливни"),
    81: ("🌧", "ливни"),
    82: ("🌧", "ливни"),
    85: ("🌨", "снежные заряды"),
    86: ("🌨", "снежные заряды"),
    95: ("⛈", "гроза"),
    96: ("⛈", "гроза с градом"),
    97: ("⛈", "гроза"),
    99: ("⛈", "гроза с градом"),
}

_cached_message = None
_cache_expires_at = 0.0
_refresh_task = None


async def request_weather(client, latitude, longitude):
    response = await client.get(API_URL, params={
        "latitude": latitude,
        "longitude": longitude,
        "current": CURRENT_FIELDS,
        "temperature_unit": "celsius",
        "timezone": "auto",
    })
    response.raise_for_status()
    return response.json()


async def get_weather(latitude: float, longitude: float):
    """Текущая погода в одной точке (сохраняет прежний интерфейс)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        data = await request_weather(client, latitude, longitude)
    return data["current"]


def format_temperature(value):
    temperature = round(value)
    if temperature > 0:
        return f"+{temperature} °C"
    if temperature < 0:
        return f"−{abs(temperature)} °C"
    return "0 °C"


def describe_weather(code, is_day):
    if code == 0 and is_day == 0:
        return "🌙", "ясно"
    if not isinstance(code, (int, float)):
        return "🌡", "погодные условия неизвестны"
    return WEATHER_CODES.get(code, ("🌡", "погодные условия неизвестны"))


def format_city_weather(city, current):
    for field in ("temperature_2m", "apparent_temperature"):
        value = current[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"Invalid {field}: {value!r}")
    emoji, description = describe_weather(current.get("weather_code"), current.get("is_day"))
    temperature = format_temperature(current["temperature_2m"])
    apparent = format_temperature(current["apparent_temperature"])
    return f"{city}: {emoji} {temperature} (как {apparent})"


def format_weather_message(results):
    """Собирает ответ, изолируя ошибки отдельных городов."""
    if not isinstance(results, list):
        raise ValueError("Expected a list of locations from Open-Meteo")

    locations = {}
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            logger.warning("Invalid weather entry at index %s: %r", index, result)
            continue
        location_id = result.get("location_id", index)
        if type(location_id) is not int or not 0 <= location_id < len(CITIES):
            logger.warning("Invalid weather location_id: %r", location_id)
            continue
        locations[location_id] = result

    lines = ["🌤 Погода сейчас", ""]
    successful_cities = 0
    for index, (city, latitude, longitude) in enumerate(CITIES):
        try:
            current = locations[index]["current"]
            lines.append(format_city_weather(city, current))
            successful_cities += 1
        except (KeyError, TypeError, ValueError, AttributeError):
            logger.exception("Weather unavailable for %s (%s, %s)", city, latitude, longitude)
            lines.append(f"{city}: данные временно недоступны")

    if successful_cities == 0:
        return UNAVAILABLE_MESSAGE
    return "\n".join(lines)


async def refresh_weather():
    global _cached_message, _cache_expires_at

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            results = await request_weather(
                client,
                ",".join(str(city[1]) for city in CITIES),
                ",".join(str(city[2]) for city in CITIES),
            )
        message = format_weather_message(results)
    except (httpx.HTTPError, ValueError):
        logger.exception("Open-Meteo request failed")
        return UNAVAILABLE_MESSAGE

    if message != UNAVAILABLE_MESSAGE:
        _cached_message = message
        _cache_expires_at = time.monotonic() + CACHE_SECONDS
    return message


async def get_weather_message():
    """Кеш на 5 минут; все одновременные вызовы ждут одно обновление."""
    global _refresh_task

    if _cached_message is not None and time.monotonic() < _cache_expires_at:
        return _cached_message
    if _refresh_task is None or _refresh_task.done():
        _refresh_task = asyncio.create_task(refresh_weather())
    return await asyncio.shield(_refresh_task)


async def main():
    print(await get_weather_message())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
