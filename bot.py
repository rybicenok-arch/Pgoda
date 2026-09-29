import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Optional

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    KeyboardButton,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery,
)

logging.basicConfig(level=logging.INFO)

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@your_channel")

if not TG_BOT_TOKEN:
    raise RuntimeError("TG_BOT_TOKEN is not set")


# =========================================================
# СОСТОЯНИЯ
# =========================================================

class SearchState(StatesGroup):
    waiting_city = State()


# =========================================================
# ГОРОД
# =========================================================

@dataclass
class Place:
    name: str
    admin1: str
    country: str
    latitude: float
    longitude: float


# =========================================================
# КЛАВИАТУРЫ
# =========================================================

def subscription_keyboard():
    channel_username = REQUIRED_CHANNEL.replace("@", "")

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Подписаться на канал",
                    url=f"https://t.me/{channel_username}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Проверить подписку",
                    callback_data="check_subscription",
                )
            ],
        ]
    )


def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🌤 Погода сейчас"),
                KeyboardButton(text="📅 7 дней"),
            ],
            [
                KeyboardButton(text="🏙 Выбрать город"),
                KeyboardButton(
                    text="📍 Моя геолокация",
                    request_location=True,
                ),
            ],
        ],
        resize_keyboard=True,
    )


# =========================================================
# ПРОВЕРКА ПОДПИСКИ
# =========================================================

async def is_subscribed(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(
            chat_id=REQUIRED_CHANNEL,
            user_id=user_id,
        )

        return member.status in {
            "creator",
            "administrator",
            "member",
        }

    except Exception as e:
        logging.error(f"Subscription check error: {e}")
        return False


async def subscription_required(
    message: Message,
    bot: Bot,
) -> bool:

    if await is_subscribed(bot, message.from_user.id):
        return True

    await message.answer(
        "🔒 <b>Доступ закрыт</b>\n\n"
        "Чтобы пользоваться ботом, сначала подпишись "
        "на наш Telegram-канал.\n\n"
        "После подписки нажми «Проверить подписку».",
        reply_markup=subscription_keyboard(),
    )

    return False


# =========================================================
# OPEN-METEO
# =========================================================

GEOCODING_URL = (
    "https://geocoding-api.open-meteo.com/v1/search"
)

FORECAST_URL = (
    "https://api.open-meteo.com/v1/forecast"
)


async def geocode(city: str) -> Optional[Place]:

    params = {
        "name": city,
        "count": 5,
        "language": "ru",
        "format": "json",
    }

    async with aiohttp.ClientSession() as session:

        async with session.get(
            GEOCODING_URL,
            params=params,
            timeout=15,
        ) as response:

            response.raise_for_status()

            data = await response.json()

    results = data.get("results") or []

    if not results:
        return None

    result = results[0]

    return Place(
        name=result.get("name", city),
        admin1=result.get("admin1", ""),
        country=result.get("country", ""),
        latitude=result["latitude"],
        longitude=result["longitude"],
    )


async def get_weather(
    latitude: float,
    longitude: float,
    days: int = 7,
):

    params = {
        "latitude": latitude,
        "longitude": longitude,

        "timezone": "auto",

        "forecast_days": days,

        "current": ",".join(
            [
                "temperature_2m",
                "apparent_temperature",
                "precipitation",
                "weather_code",
                "wind_speed_10m",
                "relative_humidity_2m",
            ]
        ),

        "daily": ",".join(
            [
                "weather_code",
                "temperature_2m_max",
                "temperature_2m_min",
                "apparent_temperature_max",
                "apparent_temperature_min",
                "precipitation_probability_max",
                "precipitation_sum",
                "wind_speed_10m_max",
                "sunrise",
                "sunset",
            ]
        ),
    }

    async with aiohttp.ClientSession() as session:

        async with session.get(
            FORECAST_URL,
            params=params,
            timeout=15,
        ) as response:

            response.raise_for_status()

            return await response.json()


# =========================================================
# ОПИСАНИЕ ПОГОДЫ
# =========================================================

def weather_text(code: int) -> str:

    weather = {
        0: "☀️ Ясно",
        1: "🌤 Преимущественно ясно",
        2: "⛅ Переменная облачность",
        3: "☁️ Пасмурно",

        45: "🌫 Туман",
        48: "🌫 Изморозь / туман",

        51: "🌦 Лёгкая морось",
        53: "🌦 Морось",
        55: "🌧 Сильная морось",

        56: "🌧 Ледяная морось",
        57: "🌧 Сильная ледяная морось",

        61: "🌧 Небольшой дождь",
        63: "🌧 Дождь",
        65: "🌧 Сильный дождь",

        66: "🌧 Ледяной дождь",
        67: "🌧 Сильный ледяной дождь",

        71: "🌨 Небольшой снег",
        73: "❄️ Снег",
        75: "❄️ Сильный снег",

        77: "🌨 Снежные зёрна",

        80: "🌦 Ливни",
        81: "🌧 Ливни",
        82: "⛈ Сильные ливни",

        85: "🌨 Снегопад",
        86: "❄️ Сильный снегопад",

        95: "⛈ Гроза",
        96: "⛈ Гроза с градом",
        99: "⛈ Сильная гроза с градом",
    }

    return weather.get(
        code,
        "🌡 Переменная погода",
    )


# =========================================================
# СОВЕТ ПО ОДЕЖДЕ
# =========================================================

def clothing(
    temperature: float,
    apparent: float,
    rain_probability: float,
    wind: float,
    weather_code: int,
) -> str:

    t = apparent

    if t < -15:

        outfit = (
            "термобельё + тёплый свитер/флис + "
            "очень тёплая зимняя куртка"
        )

    elif t < -5:

        outfit = (
            "термобельё + свитер/худи + "
            "зимняя куртка"
        )

    elif t < 5:

        outfit = (
            "лонгслив/свитер + "
            "тёплая куртка"
        )

    elif t < 12:

        outfit = (
            "лонгслив или худи + "
            "лёгкая куртка"
        )

    elif t < 18:

        outfit = (
            "лонгслив/тонкий свитер + "
            "лёгкая верхняя одежда"
        )

    elif t < 23:

        outfit = (
            "футболка; на вечер лучше "
            "взять лёгкий лонгслив"
        )

    elif t < 28:

        outfit = (
            "футболка и лёгкие брюки/шорты"
        )

    else:

        outfit = (
            "лёгкая футболка и шорты"
        )

    extras = []

    if (
        rain_probability >= 40
        or weather_code in {
            51, 53, 55,
            61, 63, 65,
            66, 67,
            80, 81, 82,
            95, 96, 99,
        }
    ):

        extras.append(
            "возьми зонт или дождевик"
        )

    if wind >= 30:

        extras.append(
            "из-за ветра лучше добавить ветровку"
        )

    if t >= 25:

        extras.append(
            "не забудь воду"
        )

    result = outfit

    if extras:

        result += "; " + "; ".join(extras)

    return result + "."


# =========================================================
# НАЗВАНИЕ ГОРОДА
# =========================================================

def place_title(place: Place) -> str:

    parts = [place.name]

    if (
        place.admin1
        and place.admin1 != place.name
    ):
        parts.append(place.admin1)

    if place.country:
        parts.append(place.country)

    return ", ".join(parts)


# =========================================================
# ТЕКУЩАЯ ПОГОДА
# =========================================================

def current_message(
    place: Place,
    data: dict,
) -> str:

    current = data["current"]

    return (
        f"🌤 <b>{place_title(place)}</b>\n\n"

        f"{weather_text(current['weather_code'])}\n"

        f"🌡 Температура: "
        f"<b>{current['temperature_2m']:.0f}°C</b>\n"

        f"🤔 Ощущается: "
        f"<b>{current['apparent_temperature']:.0f}°C</b>\n"

        f"💧 Влажность: "
        f"{current['relative_humidity_2m']}%\n"

        f"🌧 Осадки сейчас: "
        f"{current['precipitation']} мм\n"

        f"💨 Ветер: "
        f"{current['wind_speed_10m']:.0f} км/ч\n\n"

        f"👕 <b>Что надеть:</b>\n"
        f"{clothing("
        f"current['temperature_2m'], "
        f"current['apparent_temperature'], "
        f"0, "
        f"current['wind_speed_10m'], "
        f"current['weather_code']"
        f")}\n\n"

        f"📡 Источник: Open-Meteo"
    )


# =========================================================
# 7 ДНЕЙ
# =========================================================

def week_message(
    place: Place,
    data: dict,
) -> str:

    daily = data["daily"]

    result = [
        f"📅 <b>Прогноз на 7 дней</b>",
        f"🏙 {place_title(place)}",
        "",
    ]

    for i, date in enumerate(daily["time"]):

        rain = daily[
            "precipitation_probability_max"
        ][i]

        precipitation = daily[
            "precipitation_sum"
        ][i]

        wind = daily[
            "wind_speed_10m_max"
        ][i]

        temp_min = daily[
            "temperature_2m_min"
        ][i]

        temp_max = daily[
            "temperature_2m_max"
        ][i]

        apparent_max = daily[
            "apparent_temperature_max"
        ][i]

        code = daily[
            "weather_code"
        ][i]

        outfit = clothing(
            temp_max,
            apparent_max,
            rain,
            wind,
            code,
        )

        result.append(
            f"<b>{date}</b>\n"
            f"{weather_text(code)}\n"
            f"🌡 {temp_min:.0f}…{temp_max:.0f}°C\n"
            f"🤔 Ощущается до {apparent_max:.0f}°C\n"
            f"🌧 Дождь: {rain}%\n"
            f"💧 Осадки: {precipitation:.1f} мм\n"
            f"💨 Ветер: {wind:.0f} км/ч\n"
            f"👕 {outfit}\n"
        )

    result.append(
        "📡 Источник: Open-Meteo"
    )

    return "\n".join(result)


# =========================================================
# СОХРАНЁННЫЙ ГОРОД
# =========================================================

async def get_saved_place(
    state: FSMContext,
):

    data = await state.get_data()

    if "place" not in data:
        return None

    return Place(
        **data["place"]
    )


# =========================================================
# ОТПРАВКА ПОГОДЫ
# =========================================================

async def send_weather(
    message: Message,
    place: Place,
    days: int,
):

    try:

        data = await get_weather(
            place.latitude,
            place.longitude,
            days,
        )

        if days == 1:

            await message.answer(
                current_message(
                    place,
                    data,
                ),
                reply_markup=main_keyboard(),
            )

        else:

            await message.answer(
                week_message(
                    place,
                    data,
                ),
                reply_markup=main_keyboard(),
            )

    except Exception:

        logging.exception(
            "Weather request failed"
        )

        await message.answer(
            "❌ Не удалось получить прогноз. "
            "Попробуй ещё раз."
        )


# =========================================================
# START
# =========================================================

async def start(
    message: Message,
    state: FSMContext,
    bot: Bot,
):

    if not await subscription_required(
        message,
        bot,
    ):
        return

    await message.answer(
        "🌦 <b>Weather & Outfit</b>\n\n"
        "Я покажу погоду и подскажу, "
        "что лучше надеть.\n\n"
        "Можно посмотреть погоду сейчас "
        "или прогноз на 7 дней.",
        reply_markup=main_keyboard(),
    )


# =========================================================
# ПРОВЕРКА ПОДПИСКИ
# =========================================================

async def check_subscription(
    callback: CallbackQuery,
    bot: Bot,
):

    if await is_subscribed(
        bot,
        callback.from_user.id,
    ):

        await callback.message.edit_text(
            "✅ <b>Подписка подтверждена!</b>\n\n"
            "Теперь тебе доступен бот.\n"
            "Нажми /start."
        )

    else:

        await callback.answer(
            "❌ Ты ещё не подписан на канал.",
            show_alert=True,
        )


# =========================================================
# ВЫБОР ГОРОДА
# =========================================================

async def choose_city(
    message: Message,
    state: FSMContext,
    bot: Bot,
):

    if not await subscription_required(
        message,
        bot,
    ):
        return

    await state.set_state(
        SearchState.waiting_city
    )

    await message.answer(
        "🏙 <b>Напиши город</b>\n\n"
        "Например:\n"
        "Сочи\n"
        "Краснодар\n"
        "Москва\n"
        "Осло"
    )


async def city_input(
    message: Message,
    state: FSMContext,
    bot: Bot,
):

    if not await subscription_required(
        message,
        bot,
    ):
        return

    city = message.text.strip()

    place = await geocode(city)

    if not place:

        await message.answer(
            "❌ Город не найден.\n"
            "Попробуй написать название ещё раз."
        )

        return

    await state.update_data(
        place=place.__dict__
    )

    await state.set_state(None)

    await message.answer(
        f"✅ Город выбран:\n"
        f"<b>{place_title(place)}</b>\n\n"
        "Теперь выбери:\n"
        "🌤 Погода сейчас\n"
        "📅 7 дней",
        reply_markup=main_keyboard(),
    )


# =========================================================
# ТЕКУЩАЯ ПОГОДА
# =========================================================

async def current(
    message: Message,
    state: FSMContext,
    bot: Bot,
):

    if not await subscription_required(
        message,
        bot,
    ):
        return

    place = await get_saved_place(state)

    if not place:

        await choose_city(
            message,
            state,
            bot,
        )

        return

    await send_weather(
        message,
        place,
        1,
    )


# =========================================================
# 7 ДНЕЙ
# =========================================================

async def week(
    message: Message,
    state: FSMContext,
    bot: Bot,
):

    if not await subscription_required(
        message,
        bot,
    ):
        return

    place = await get_saved_place(state)

    if not place:

        await choose_city(
            message,
            state,
            bot,
        )

        return

    await send_weather(
        message,
        place,
        7,
    )


# =========================================================
# ГЕОЛОКАЦИЯ
# =========================================================

async def received_location(
    message: Message,
    state: FSMContext,
    bot: Bot,
):

    if not await subscription_required(
        message,
        bot,
    ):
        return

    latitude = message.location.latitude
    longitude = message.location.longitude

    place = Place(
        name="Текущая геолокация",
        admin1="",
        country="",
        latitude=latitude,
        longitude=longitude,
    )

    await state.update_data(
        place=place.__dict__
    )

    await message.answer(
        "📍 Геолокация получена.\n"
        "Сейчас покажу погоду.",
        reply_markup=main_keyboard(),
    )

    await send_weather(
        message,
        place,
        1,
    )


# =========================================================
# MAIN
# =========================================================

async def main():

    bot = Bot(
        TG_BOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML
        ),
    )

    dp = Dispatcher()

    dp.callback_query.register(
        check_subscription,
        F.data == "check_subscription",
    )

    dp.message.register(
        start,
        CommandStart(),
    )

    dp.message.register(
        received_location,
        F.location,
    )

    dp.message.register(
        choose_city,
        F.text == "🏙 Выбрать город",
    )

    dp.message.register(
        current,
        F.text == "🌤 Погода сейчас",
    )

    dp.message.register(
        week,
        F.text == "📅 7 дней",
    )

    dp.message.register(
        city_input,
        SearchState.waiting_city,
    )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
