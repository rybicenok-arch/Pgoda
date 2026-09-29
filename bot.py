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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# =========================================================
# CONFIG
# =========================================================

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@your_channel")

if not TG_BOT_TOKEN:
    raise RuntimeError("TG_BOT_TOKEN is not set")

if not REQUIRED_CHANNEL:
    raise RuntimeError("REQUIRED_CHANNEL is not set")


# =========================================================
# STATES
# =========================================================

class SearchState(StatesGroup):
    waiting_city = State()


# =========================================================
# PLACE
# =========================================================

@dataclass
class Place:
    name: str
    admin1: str
    country: str
    latitude: float
    longitude: float


# =========================================================
# KEYBOARDS
# =========================================================

def subscription_keyboard() -> InlineKeyboardMarkup:
    channel_username = REQUIRED_CHANNEL.lstrip("@")

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


def main_keyboard() -> ReplyKeyboardMarkup:
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
# SUBSCRIPTION
# =========================================================

async def is_subscribed(
    bot: Bot,
    user_id: int,
) -> bool:

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

    except Exception as error:
        logging.error(
            "Subscription check error: %s",
            error,
        )
        return False


async def subscription_required(
    message: Message,
    bot: Bot,
) -> bool:

    if not message.from_user:
        return False

    if await is_subscribed(
        bot,
        message.from_user.id,
    ):
        return True

    await message.answer(
        "🔒 <b>Доступ закрыт</b>\n\n"
        "Чтобы пользоваться ботом, сначала "
        "подпишись на наш Telegram-канал.\n\n"
        "После подписки нажми "
        "«✅ Проверить подписку».",
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


async def geocode(
    city: str,
) -> Optional[Place]:

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
        latitude=float(result["latitude"]),
        longitude=float(result["longitude"]),
    )


async def get_weather(
    latitude: float,
    longitude: float,
    days: int = 7,
) -> dict:

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
# WEATHER DESCRIPTION
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
# CLOTHING
# =========================================================

def clothing(
    temperature: float,
    apparent: float,
    rain_probability: float,
    wind: float,
    weather_code: int,
) -> str:

    # Для одежды ориентируемся прежде всего
    # на ощущаемую температуру.
    t = apparent

    if t < -20:
        outfit = (
            "очень тёплое термобельё, "
            "флис/свитер, зимняя куртка, "
            "тёплые штаны, шапка и перчатки"
        )

    elif t < -10:
        outfit = (
            "термобельё, тёплый свитер "
            "и зимняя куртка; шапка и перчатки"
        )

    elif t < 0:
        outfit = (
            "тёплый свитер или худи + "
            "зимняя/утеплённая куртка"
        )

    elif t < 7:
        outfit = (
            "лонгслив или свитер + "
            "тёплая куртка"
        )

    elif t < 12:
        outfit = (
            "лонгслив/худи + "
            "лёгкая куртка"
        )

    elif t < 17:
        outfit = (
            "лонгслив или тонкий свитер + "
            "лёгкая куртка"
        )

    elif t < 22:
        outfit = (
            "футболка или лонгслив; "
            "на вечер лучше взять лёгкую куртку"
        )

    elif t < 27:
        outfit = (
            "футболка + лёгкие брюки "
            "или шорты"
        )

    else:
        outfit = (
            "лёгкая футболка + шорты; "
            "избегай лишних слоёв"
        )

    extras = []

    rain_codes = {
        51, 53, 55,
        56, 57,
        61, 63, 65,
        66, 67,
        80, 81, 82,
        95, 96, 99,
    }

    if (
        rain_probability >= 40
        or weather_code in rain_codes
    ):
        extras.append(
            "возьми зонт или дождевик"
        )

    if wind >= 30:
        extras.append(
            "из-за сильного ветра лучше "
            "добавить ветровку"
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
# PLACE TITLE
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
# CURRENT WEATHER MESSAGE
# =========================================================

def current_message(
    place: Place,
    data: dict,
) -> str:

    current = data["current"]

    # Сначала вычисляем совет отдельно.
    # Это предотвращает ошибки f-string.
    outfit = clothing(
        temperature=current["temperature_2m"],
        apparent=current["apparent_temperature"],
        rain_probability=0,
        wind=current["wind_speed_10m"],
        weather_code=current["weather_code"],
    )

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
        f"{outfit}\n\n"
        f"📡 Источник: Open-Meteo"
    )


# =========================================================
# 7-DAY MESSAGE
# =========================================================

def week_message(
    place: Place,
    data: dict,
) -> str:

    daily = data["daily"]

    result = [
        "📅 <b>Прогноз на 7 дней</b>",
        f"🏙 <b>{place_title(place)}</b>",
        "",
    ]

    for i, date in enumerate(
        daily["time"]
    ):

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

        apparent_min = daily[
            "apparent_temperature_min"
        ][i]

        apparent_max = daily[
            "apparent_temperature_max"
        ][i]

        code = daily[
            "weather_code"
        ][i]

        outfit = clothing(
            temperature=temp_max,
            apparent=apparent_max,
            rain_probability=rain,
            wind=wind,
            weather_code=code,
        )

        result.append(
            f"<b>{date}</b>\n"
            f"{weather_text(code)}\n"
            f"🌡 Температура: "
            f"{temp_min:.0f}…{temp_max:.0f}°C\n"
            f"🤔 Ощущается: "
            f"{apparent_min:.0f}…{apparent_max:.0f}°C\n"
            f"🌧 Вероятность осадков: "
            f"{rain}%\n"
            f"💧 Осадки: "
            f"{precipitation:.1f} мм\n"
            f"💨 Максимальный ветер: "
            f"{wind:.0f} км/ч\n"
            f"👕 <b>Что надеть:</b> "
            f"{outfit}\n"
        )

    result.append(
        "📡 Источник: Open-Meteo"
    )

    return "\n".join(result)


# =========================================================
# SAVED PLACE
# =========================================================

async def get_saved_place(
    state: FSMContext,
) -> Optional[Place]:

    data = await state.get_data()

    place_data = data.get("place")

    if not place_data:
        return None

    return Place(
        **place_data
    )


# =========================================================
# SEND WEATHER
# =========================================================

async def send_weather(
    message: Message,
    place: Place,
    days: int,
) -> None:

    try:

        data = await get_weather(
            latitude=place.latitude,
            longitude=place.longitude,
            days=days,
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
            "❌ Не удалось получить прогноз.\n"
            "Попробуй ещё раз через несколько секунд.",
            reply_markup=main_keyboard(),
        )


# =========================================================
# START
# =========================================================

async def start(
    message: Message,
    state: FSMContext,
    bot: Bot,
) -> None:

    if not await subscription_required(
        message,
        bot,
    ):
        return

    await message.answer(
        "🌦 <b>Weather & Outfit</b>\n\n"
        "Я покажу погоду и подскажу, "
        "что лучше надеть.\n\n"
        "Выбери город и получи прогноз "
        "с рекомендацией по одежде.",
        reply_markup=main_keyboard(),
    )


# =========================================================
# CHECK SUBSCRIPTION
# =========================================================

async def check_subscription(
    callback: CallbackQuery,
    bot: Bot,
) -> None:

    if await is_subscribed(
        bot,
        callback.from_user.id,
    ):

        await callback.message.edit_text(
            "✅ <b>Подписка подтверждена!</b>\n\n"
            "Теперь тебе доступен бот.\n\n"
            "Нажми /start."
        )

        await callback.answer(
            "Подписка подтверждена!"
        )

    else:

        await callback.answer(
            "❌ Ты ещё не подписан на канал.",
            show_alert=True,
        )


# =========================================================
# CHOOSE CITY
# =========================================================

async def choose_city(
    message: Message,
    state: FSMContext,
    bot: Bot,
) -> None:

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


# =========================================================
# CITY INPUT
# =========================================================

async def city_input(
    message: Message,
    state: FSMContext,
    bot: Bot,
) -> None:

    if not await subscription_required(
        message,
        bot,
    ):
        return

    if not message.text:
        return

    city = message.text.strip()

    if len(city) < 2:
        await message.answer(
            "❌ Напиши название города."
        )
        return

    await message.answer(
        "🔎 Ищу город..."
    )

    try:

        place = await geocode(city)

    except Exception:

        logging.exception(
            "Geocoding failed"
        )

        await message.answer(
            "❌ Не удалось найти город.\n"
            "Попробуй ещё раз."
        )

        return

    if not place:

        await message.answer(
            "❌ Город не найден.\n\n"
            "Попробуй, например:\n"
            "Сочи\n"
            "Москва\n"
            "Краснодар"
        )

        return

    await state.update_data(
        place=place.__dict__
    )

    await state.set_state(None)

    await message.answer(
        "✅ <b>Город выбран</b>\n\n"
        f"🏙 {place_title(place)}\n\n"
        "Теперь выбери нужный прогноз.",
        reply_markup=main_keyboard(),
    )


# =========================================================
# CURRENT WEATHER
# =========================================================

async def current(
    message: Message,
    state: FSMContext,
    bot: Bot,
) -> None:

    if not await subscription_required(
        message,
        bot,
    ):
        return

    place = await get_saved_place(
        state
    )

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
# WEEK WEATHER
# =========================================================

async def week(
    message: Message,
    state: FSMContext,
    bot: Bot,
) -> None:

    if not await subscription_required(
        message,
        bot,
    ):
        return

    place = await get_saved_place(
        state
    )

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
# LOCATION
# =========================================================

async def received_location(
    message: Message,
    state: FSMContext,
    bot: Bot,
) -> None:

    if not await subscription_required(
        message,
        bot,
    ):
        return

    if not message.location:
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
        "📍 <b>Геолокация получена!</b>\n\n"
        "Сейчас получу прогноз.",
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
        token=TG_BOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML
        ),
    )

    dispatcher = Dispatcher()

    # Проверка подписки
    dispatcher.callback_query.register(
        check_subscription,
        F.data == "check_subscription",
    )

    # /start
    dispatcher.message.register(
        start,
        CommandStart(),
    )

    # Геолокация
    dispatcher.message.register(
        received_location,
        F.location,
    )

    # Основные кнопки
    dispatcher.message.register(
        choose_city,
        F.text == "🏙 Выбрать город",
    )

    dispatcher.message.register(
        current,
        F.text == "🌤 Погода сейчас",
    )

    dispatcher.message.register(
        week,
        F.text == "📅 7 дней",
    )

    # Ввод города
    dispatcher.message.register(
        city_input,
        SearchState.waiting_city,
    )

    logging.info(
        "Weather & Outfit Bot started"
    )

    await dispatcher.start_polling(
        bot
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot stopped")
