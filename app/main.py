import asyncio
import contextlib
import logging
import os

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand

from app.bot import build_dispatcher, notification_loop
from app.config import load_config
from app.services.core import Service


async def run():
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        print("Не задан BOT_TOKEN. Получите токен у @BotFather и задайте переменную окружения. Подробности в README.md.")
        return
    try:
        config = load_config(os.environ.get("BOT_CONFIG", "config.json"))
    except Exception:
        print("Ошибка конфигурации. Проверьте config.json или config.example.json.")
        return
    try:
        service = Service(config)
    except Exception:
        print("Не удалось открыть базу данных. Проверьте путь database и доступ к папке.")
        return
    try:
        bot = Bot(token)
    except Exception:
        print("Неверный формат BOT_TOKEN. Вставьте целиком токен от BotFather: цифры, двоеточие и секретная часть, без кавычек и переносов строк.")
        return
    async with bot:
        try:
            await bot.set_my_commands([
                BotCommand(command="start", description="Главное меню"),
                BotCommand(command="menu", description="Открыть меню"),
                BotCommand(command="cancel", description="Отменить заполнение"),
                BotCommand(command="help", description="Правила и помощь"),
            ])
            # Webhook и polling взаимоисключающие; очередь сообщений не очищаем.
            await bot.delete_webhook(drop_pending_updates=False)
            dispatcher = build_dispatcher(service)
            worker = asyncio.create_task(notification_loop(bot, service))
            print("Бот запущен. Для остановки нажмите Ctrl+C.")
            try:
                await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
            finally:
                worker.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker
                await dispatcher.storage.close()
                await dispatcher.fsm.events_isolation.close()
        except TelegramAPIError:
            print("Telegram недоступен или токен не принят. Проверьте токен, сеть и отсутствие второго запуска бота.")


def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    for handler in logging.getLogger().handlers:
        handler.addFilter(lambda record: record.name == "team_bot")
    # Исключаем сырые исключения транспортных библиотек из журналов.
    for name in ("aiogram", "aiohttp"):
        logging.getLogger(name).disabled = True
        logging.getLogger(name).propagate = False
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("Бот остановлен.")
    except Exception:
        print("Не удалось запустить бот. Проверьте конфигурацию и доступность базы; секреты в журнал не выведены.")


if __name__ == "__main__":
    main()
