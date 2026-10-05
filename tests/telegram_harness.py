from datetime import datetime, timezone

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, SendMessage
from aiogram.types import CallbackQuery, Chat, InlineKeyboardMarkup, Message, Update, User

from app.bot import build_dispatcher


class RecordingSession(BaseSession):
    """Подменяет только транспорт Telegram. Обработчики и SQLite настоящие."""

    def __init__(self):
        super().__init__()
        self.sent = []
        self.answers = []

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, AnswerCallbackQuery):
            self.answers.append(method)
            return True
        if not isinstance(method, SendMessage):
            raise AssertionError(f"Unexpected Telegram method: {type(method).__name__}")
        message = Message(
            message_id=len(self.sent) + 1,
            date=datetime.now(timezone.utc),
            chat=Chat(id=int(method.chat_id), type="private"),
            from_user=User(id=bot.id, is_bot=True, first_name="Тестовый бот"),
            text=method.text,
            reply_markup=method.reply_markup if isinstance(method.reply_markup, InlineKeyboardMarkup) else None,
        )
        self.sent.append(message)
        return message

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        if False:
            yield b""


class TelegramHarness:
    def __init__(self, service):
        self.session = RecordingSession()
        self.bot = Bot("123456:TEST_TRANSPORT_ONLY_NO_REAL_TOKEN", session=self.session)
        self.dispatcher = build_dispatcher(service)
        self.counter = 0

    def last(self, actor):
        return next(message for message in reversed(self.session.sent) if message.chat.id == actor)

    def text(self, actor):
        return "\n".join(message.text for message in self.session.sent if message.chat.id == actor)

    async def send(self, actor, text):
        self.counter += 1
        message = Message(message_id=self.counter, date=datetime.now(timezone.utc), chat=Chat(id=actor, type="private"), from_user=User(id=actor, is_bot=False, first_name=f"Тест {actor}"), text=text)
        await self.dispatcher.feed_update(self.bot, Update(update_id=self.counter, message=message))
        self.check_messages()

    async def callback(self, actor, data, source=None):
        self.counter += 1
        query = CallbackQuery(id=str(self.counter), from_user=User(id=actor, is_bot=False, first_name=f"Тест {actor}"), chat_instance=str(actor), message=source or self.last(actor), data=data)
        await self.dispatcher.feed_update(self.bot, Update(update_id=self.counter, callback_query=query))
        self.check_messages()

    async def click(self, actor, label):
        message = self.last(actor)
        assert message.reply_markup, (label, message.text)
        button = next((button for row in message.reply_markup.inline_keyboard for button in row if button.text == label), None)
        assert button, (label, [b.text for row in message.reply_markup.inline_keyboard for b in row], message.text)
        await self.callback(actor, button.callback_data, message)

    def check_messages(self):
        for message in self.session.sent:
            assert len(message.text) <= 4096
            assert "Не удалось выполнить действие" not in message.text, message.text
            if message.reply_markup:
                for row in message.reply_markup.inline_keyboard:
                    for button in row:
                        assert len(button.callback_data.encode("utf-8")) <= 64

    async def close(self):
        await self.dispatcher.storage.close()
        await self.dispatcher.fsm.events_isolation.close()
        await self.bot.session.close()


async def fill_profile(harness, actor, name):
    await harness.send(actor, "/start")
    await harness.send(actor, "Моя анкета")
    await harness.click(actor, "Заполнить анкету")
    await harness.send(actor, name)
    await harness.click(actor, "Бэкенд-разработчик")
    await harness.click(actor, "Пропустить")
    await harness.click(actor, "Python")
    await harness.click(actor, "PostgreSQL")
    await harness.click(actor, "Готово")
    await harness.send(actor, "Учусь, хочу сделать рабочий API")
    await harness.click(actor, "Новичок")
    for _ in range(2):
        await harness.click(actor, "Пропустить")
    assert "Предпросмотр" in harness.last(actor).text
    await harness.click(actor, "Сохранить")


async def create_team_and_place(harness, captain):
    await harness.send(captain, "Моя команда / Создать команду")
    await harness.click(captain, "Создать команду")
    await harness.send(captain, "[ТЕСТ] Команда прототипа")
    await harness.click(captain, "Пропустить")
    await harness.click(captain, "Сохранить")
    await harness.click(captain, "Добавить место")
    await harness.click(captain, "Бэкенд-разработчик")
    await harness.send(captain, "Разработать API для учебного проекта")
    await harness.click(captain, "Python")
    await harness.click(captain, "Готово")
    await harness.click(captain, "PostgreSQL")
    await harness.click(captain, "Готово")
    await harness.click(captain, "Да")
    await harness.click(captain, "Сохранить")
