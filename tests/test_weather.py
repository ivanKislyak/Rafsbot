import asyncio
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
from aiogram.types import Chat, Message

import weather


def make_results():
    return [
        {
            "location_id": index,
            "current": {
                "temperature_2m": index + 0.2,
                "apparent_temperature": -3.2,
                "weather_code": 0,
                "is_day": 1,
            },
        }
        for index in range(len(weather.CITIES))
    ]


class FormattingTests(unittest.TestCase):
    def test_temperature_signs_and_rounding(self):
        for value, expected in [
            (8.2, "+8 °C"), (-3.2, "−3 °C"),
            (0, "0 °C"), (-0.0, "0 °C"), (-0.4, "0 °C"), (0.4, "0 °C"),
        ]:
            with self.subTest(value=value):
                self.assertEqual(weather.format_temperature(value), expected)

    def test_all_documented_codes_and_unknown(self):
        codes = {
            0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65,
            66, 67, 71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 97, 99,
        }
        for code in codes:
            self.assertNotIn("неизвестны", weather.describe_weather(code, 1)[1])
        self.assertEqual(weather.describe_weather(0, 0), ("🌙", "ясно"))
        self.assertEqual(weather.describe_weather(0, 1), ("☀️", "ясно"))
        for code in (1234, None, [], {}):
            self.assertIn("неизвестны", weather.describe_weather(code, 1)[1])

    def test_city_order_and_location_ids(self):
        # Явные ID сохраняют соответствие даже при перестановке JSON-объектов.
        message = weather.format_weather_message(list(reversed(make_results())))
        lines = message.splitlines()
        self.assertEqual(lines[0], "🌤 Погода сейчас")
        for index, (city, _, _) in enumerate(weather.CITIES):
            self.assertTrue(lines[index + 2].startswith(f"{city}: ☀️ "))
            expected = "0 °C" if index == 0 else f"+{index} °C"
            self.assertIn(expected, lines[index + 2])
        self.assertEqual(lines[-1], "Данные: Open-Meteo")
        self.assertLess(len(message), 4096)

    def test_response_without_location_ids(self):
        results = make_results()
        for result in results:
            del result["location_id"]
        self.assertEqual(
            weather.format_weather_message(results),
            weather.format_weather_message(make_results()),
        )

    def test_partial_failure_and_missing_location(self):
        for bad_value in (None, float("nan"), float("inf"), "cold"):
            results = make_results()
            results[2]["current"]["temperature_2m"] = bad_value
            del results[4]
            with self.assertLogs("weather", level="ERROR"):
                message = weather.format_weather_message(results)
            self.assertIn("Ижевск: данные временно недоступны", message)
            self.assertIn("Химки: данные временно недоступны", message)
            self.assertIn("Сыктывкар: ☀️ +5 °C", message)
            self.assertIn("Мариуполь: ☀️ +15 °C", message)

    def test_total_failure(self):
        with self.assertLogs("weather", level="ERROR"):
            self.assertEqual(weather.format_weather_message([]), weather.UNAVAILABLE_MESSAGE)


class AsyncWeatherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        weather._cached_message = None
        weather._cache_expires_at = 0.0
        weather._refresh_task = None

    async def test_concurrent_requests_cache_and_expiration(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def request(*args):
            started.set()
            await release.wait()
            return make_results()

        with patch.object(weather, "request_weather", side_effect=request) as fetch:
            callers = [asyncio.create_task(weather.get_weather_message()) for _ in range(10)]
            await started.wait()
            release.set()
            messages = await asyncio.gather(*callers)
            self.assertEqual(fetch.call_count, 1)
            self.assertTrue(all(message == messages[0] for message in messages))
            self.assertEqual(await weather.get_weather_message(), messages[0])
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(weather.CACHE_SECONDS, 300)
            weather._cache_expires_at = weather.time.monotonic() - 1
            await weather.get_weather_message()
            self.assertEqual(fetch.call_count, 2)

    async def test_total_failure_is_not_cached_and_recovers(self):
        with patch.object(weather, "request_weather", new_callable=AsyncMock) as fetch:
            fetch.side_effect = [httpx.ConnectError("offline"), make_results()]
            with self.assertLogs("weather", level="ERROR"):
                self.assertEqual(await weather.get_weather_message(), weather.UNAVAILABLE_MESSAGE)
            self.assertIsNone(weather._cached_message)
            self.assertIn("Астана: ☀️", await weather.get_weather_message())
            self.assertEqual(fetch.call_count, 2)

    async def test_partial_failure_is_cached(self):
        results = make_results()
        results[0]["current"] = None
        with patch.object(weather, "request_weather", new_callable=AsyncMock, return_value=results) as fetch:
            with self.assertLogs("weather", level="ERROR"):
                first = await weather.get_weather_message()
            self.assertEqual(await weather.get_weather_message(), first)
            self.assertEqual(fetch.call_count, 1)

    async def test_single_city_interface_and_http_parameters(self):
        def respond(request):
            self.assertEqual(request.url.params["current"], weather.CURRENT_FIELDS)
            self.assertEqual(request.url.params["temperature_unit"], "celsius")
            self.assertEqual(request.extensions["timeout"]["read"], 10.0)
            return httpx.Response(200, json=make_results()[0])

        original_client = httpx.AsyncClient
        with patch.object(weather.httpx, "AsyncClient", side_effect=lambda **kwargs: original_client(
            transport=httpx.MockTransport(respond), **kwargs
        )):
            current = await weather.get_weather(51.1801, 71.44598)
        self.assertEqual(current, make_results()[0]["current"])

    async def test_bad_status_and_invalid_json(self):
        original_client = httpx.AsyncClient
        for response in (httpx.Response(503), httpx.Response(200, text="not JSON")):
            with patch.object(weather.httpx, "AsyncClient", side_effect=lambda **kwargs: original_client(
                transport=httpx.MockTransport(lambda request: response), **kwargs
            )):
                with self.assertLogs("weather", level="ERROR"):
                    self.assertEqual(await weather.get_weather_message(), weather.UNAVAILABLE_MESSAGE)
            self.assertIsNone(weather._cached_message)

    async def test_handlers_without_polling_or_telegram_requests(self):
        # Заведомо фиктивный токен: тест не зависит от .env и не обращается в Telegram.
        with patch.dict(os.environ, {"BOT_TOKEN": "123456:TEST_TOKEN_FOR_OFFLINE_TESTS"}):
            import run

        for text in ("/weather", "погода", "  ПоГоДа  ", "\nПОГОДА\t"):
            message = Message(
                message_id=1, date=datetime.now(timezone.utc),
                chat=Chat(id=1, type="private"), text=text,
            )
            with patch.object(run, "get_weather_message", new_callable=AsyncMock, return_value="weather") as fetch:
                with patch.object(Message, "answer", new_callable=AsyncMock) as answer:
                    await run.dp.propagate_event("message", message, bot=run.bot)
            fetch.assert_awaited_once()
            answer.assert_awaited_once_with("weather")
        await run.bot.session.close()


if __name__ == "__main__":
    unittest.main()
