import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def _get_target_chat_id_from_env() -> int | None:
    raw = os.getenv("TARGET_CHAT_ID")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _load_config() -> dict[str, Any]:
    target_chat_id = _get_target_chat_id_from_env()
    if target_chat_id is not None:
        return {"target_chat_id": target_chat_id}
    if not os.path.exists(CONFIG_PATH):
        return {"target_chat_id": None}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_config(cfg: dict[str, Any]) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _parse_admin_ids(raw: str | None) -> set[int]:
    if not raw:
        return set()
    parts = [p.strip() for p in raw.split(",")]
    out: set[int] = set()
    for p in parts:
        if not p:
            continue
        try:
            out.add(int(p))
        except ValueError:
            continue
    return out


class Form(StatesGroup):
    product = State()
    game_title = State()
    device = State()
    app_version = State()
    settings = State()
    fps = State()
    issues = State()
    extra = State()
    author = State()
    media = State()
    confirm = State()


@dataclass
class MediaBucket:
    photos: list[str]
    videos: list[str]


def _kb_product() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Winlator", callback_data="product:winlator"),
                InlineKeyboardButton(text="GameHub", callback_data="product:gamehub"),
            ]
        ]
    )


def _kb_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="cancel")]]
    )


def _kb_media_done() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data="media:done")],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel")],
        ]
    )


def _kb_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отправить", callback_data="confirm:send")],
            [InlineKeyboardButton(text="Заполнить заново", callback_data="confirm:restart")],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel")],
        ]
    )


def _format_post(data: dict[str, Any]) -> str:
    product = data.get("product")
    product_title = "Winlator" if product == "winlator" else "GameHub"

    def g(key: str) -> str:
        v = (data.get(key) or "").strip()
        return v

    lines: list[str] = []
    lines.append(f"<b>Тест игры ({product_title}) от комьюнити</b>")
    lines.append("")
    lines.append(f"<b>Название игры:</b> {g('game_title')}")
    lines.append(f"<b>Устройство:</b> {g('device')}")
    lines.append(f"<b>Версия {product_title}:</b> {g('app_version')}")
    lines.append(f"<b>Настройки:</b> {g('settings')}")
    lines.append(f"<b>FPS/производительность:</b> {g('fps')}")

    issues = g("issues")
    if issues:
        lines.append(f"<b>Проблемы/баги:</b> {issues}")

    extra = g("extra")
    if extra:
        lines.append(f"<b>Дополнительно:</b> {extra}")

    author = g("author")
    if author:
        lines.append("")
        lines.append(f"<b>Автор теста:</b> {author}")

    return "\n".join(lines)


async def _ensure_media_bucket(state: FSMContext) -> MediaBucket:
    data = await state.get_data()
    bucket = data.get("media_bucket")
    if isinstance(bucket, dict):
        photos = bucket.get("photos") or []
        videos = bucket.get("videos") or []
        return MediaBucket(list(photos), list(videos))
    return MediaBucket([], [])


def _is_admin(message: Message, admin_ids: set[int]) -> bool:
    if not message.from_user:
        return False
    return message.from_user.id in admin_ids


async def main() -> None:
    load_dotenv()

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is not set")

    admin_ids = _parse_admin_ids(os.getenv("ADMIN_IDS"))

    bot = Bot(token=token, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=MemoryStorage())

    @dp.message(CommandStart())
    async def start(message: Message, state: FSMContext) -> None:
        await state.clear()
        await state.set_state(Form.product)
        await message.answer(
            "Выбери, для чего заполняем тест:",
            reply_markup=_kb_product(),
        )

    @dp.message(Command("cancel"))
    async def cancel_cmd(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Ок, отменено. Напиши /start чтобы начать заново.")

    @dp.message(Command("set_target"))
    async def set_target(message: Message) -> None:
        if admin_ids and not _is_admin(message, admin_ids):
            await message.answer("Нет доступа.")
            return
        if _get_target_chat_id_from_env() is not None:
            await message.answer(
                "TARGET_CHAT_ID задан через переменную окружения.\n"
                "На хостингах (Render) поменяй TARGET_CHAT_ID в настройках сервиса.\n"
                f"Текущий TARGET_CHAT_ID: <code>{_get_target_chat_id_from_env()}</code>"
            )
            return
        cfg = _load_config()
        cfg["target_chat_id"] = message.chat.id
        _save_config(cfg)
        await message.answer(f"Готово. Этот чат сохранён как получатель: <code>{message.chat.id}</code>")

    @dp.callback_query(F.data == "cancel")
    async def cancel_cb(call: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await call.message.answer("Ок, отменено. Напиши /start чтобы начать заново.")
        await call.answer()

    @dp.callback_query(Form.product, F.data.startswith("product:"))
    async def product_pick(call: CallbackQuery, state: FSMContext) -> None:
        product = call.data.split(":", 1)[1]
        await state.update_data(product=product)
        await state.set_state(Form.game_title)
        await call.message.answer("Название игры (текст):", reply_markup=_kb_cancel())
        await call.answer()

    @dp.message(Form.game_title)
    async def game_title(message: Message, state: FSMContext) -> None:
        await state.update_data(game_title=message.text or "")
        await state.set_state(Form.device)
        await message.answer("Устройство (модель/проц/ОЗУ), можно одной строкой:", reply_markup=_kb_cancel())

    @dp.message(Form.device)
    async def device(message: Message, state: FSMContext) -> None:
        await state.update_data(device=message.text or "")
        await state.set_state(Form.app_version)
        data = await state.get_data()
        product = data.get("product")
        product_title = "Winlator" if product == "winlator" else "GameHub"
        await message.answer(f"Версия {product_title} (например 7.1.3 / 5.3.3):", reply_markup=_kb_cancel())

    @dp.message(Form.app_version)
    async def app_version(message: Message, state: FSMContext) -> None:
        await state.update_data(app_version=message.text or "")
        await state.set_state(Form.settings)
        await message.answer(
            "Настройки (разрешение/рендер/драйвер/прочее). Можно списком в одном сообщении:",
            reply_markup=_kb_cancel(),
        )

    @dp.message(Form.settings)
    async def settings(message: Message, state: FSMContext) -> None:
        await state.update_data(settings=message.text or "")
        await state.set_state(Form.fps)
        await message.answer("FPS/производительность (например 30-60, просадки где):", reply_markup=_kb_cancel())

    @dp.message(Form.fps)
    async def fps(message: Message, state: FSMContext) -> None:
        await state.update_data(fps=message.text or "")
        await state.set_state(Form.issues)
        await message.answer("Проблемы/баги (если нет — напиши 'нет'):", reply_markup=_kb_cancel())

    @dp.message(Form.issues)
    async def issues(message: Message, state: FSMContext) -> None:
        txt = (message.text or "").strip()
        await state.update_data(issues="" if txt.lower() in {"нет", "no", "-"} else txt)
        await state.set_state(Form.extra)
        await message.answer("Дополнительно (опционально). Если нечего — напиши 'нет':", reply_markup=_kb_cancel())

    @dp.message(Form.extra)
    async def extra(message: Message, state: FSMContext) -> None:
        txt = (message.text or "").strip()
        await state.update_data(extra="" if txt.lower() in {"нет", "no", "-"} else txt)
        await state.set_state(Form.author)
        await message.answer("Автор теста (ник/ссылка). Например @nickname:", reply_markup=_kb_cancel())

    @dp.message(Form.author)
    async def author(message: Message, state: FSMContext) -> None:
        await state.update_data(author=message.text or "")
        await state.set_state(Form.media)
        await state.update_data(media_bucket={"photos": [], "videos": []})
        await message.answer(
            "Теперь отправь скриншоты и/или видео теста.\n"
            "Можно несколькими сообщениями. Когда закончишь — нажми «Готово».",
            reply_markup=_kb_media_done(),
        )

    @dp.message(Form.media, F.photo)
    async def media_photo(message: Message, state: FSMContext) -> None:
        bucket = await _ensure_media_bucket(state)
        file_id = message.photo[-1].file_id
        bucket.photos.append(file_id)
        await state.update_data(media_bucket={"photos": bucket.photos, "videos": bucket.videos})

    @dp.message(Form.media, F.video)
    async def media_video(message: Message, state: FSMContext) -> None:
        bucket = await _ensure_media_bucket(state)
        bucket.videos.append(message.video.file_id)
        await state.update_data(media_bucket={"photos": bucket.photos, "videos": bucket.videos})

    @dp.callback_query(Form.media, F.data == "media:done")
    async def media_done(call: CallbackQuery, state: FSMContext) -> None:
        data = await state.get_data()
        post = _format_post(data)
        await state.set_state(Form.confirm)
        await call.message.answer("Проверь предпросмотр поста:\n\n" + post, reply_markup=_kb_confirm())
        await call.answer()

    @dp.callback_query(Form.confirm, F.data == "confirm:restart")
    async def restart(call: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await state.set_state(Form.product)
        await call.message.answer("Ок. Выбери, для чего заполняем тест:", reply_markup=_kb_product())
        await call.answer()

    @dp.callback_query(Form.confirm, F.data == "confirm:send")
    async def send(call: CallbackQuery, state: FSMContext) -> None:
        cfg = _load_config()
        target_chat_id = cfg.get("target_chat_id")
        if not target_chat_id:
            await call.message.answer(
                "Не настроен чат-получатель.\n"
                "Добавь бота в закрытый чат и напиши там /set_target (от админа)."
            )
            await call.answer()
            return

        data = await state.get_data()
        post = _format_post(data)
        bucket = await _ensure_media_bucket(state)

        try:
            await bot.send_message(chat_id=target_chat_id, text=post)

            for fid in bucket.photos:
                await bot.send_photo(chat_id=target_chat_id, photo=fid)

            for fid in bucket.videos:
                await bot.send_video(chat_id=target_chat_id, video=fid)

        except TelegramBadRequest as e:
            await call.message.answer(f"Ошибка отправки: {e.message}")
            await call.answer()
            return

        await state.clear()
        await call.message.answer("Готово. Отправил результат. Напиши /start чтобы сделать ещё один.")
        await call.answer()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
