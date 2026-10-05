"""Демонстрация без токена: реальные диалоги и база, тестовый Telegram-транспорт."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from app.config import Config
from app.services.core import Service
from tests.test_bot_scenarios import application_flow, invitation_flow
from tests.test_team_applications import general_application_flow


async def demonstrate():
    data_root = Path("data").resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    lines = [
        "ЛОКАЛЬНАЯ ТЕСТОВАЯ ДЕМОНСТРАЦИЯ — отправка в Telegram подменена.",
        "Два отдельных пользователя: 101 — капитан, 202 — участник.",
        "Базы демонстрации отдельные и временные; настоящая база не используется.",
        "Это не подтверждение работы с настоящими аккаунтами Telegram.",
        "",
    ]
    # TemporaryDirectory удаляет только собственный созданный каталог внутри data/.
    with TemporaryDirectory(prefix="demo-", dir=data_root) as directory:
        demo_root = Path(directory).resolve()
        if not demo_root.is_relative_to(data_root):
            raise RuntimeError("Каталог демонстрации вне data/.")
        for title, filename, flow in (
            ("КОМАНДЫ: состав и общая заявка без позиции", "general.db", general_application_flow),
            ("ЗАЯВКА: полный основной сценарий", "application.db", application_flow),
            ("ПРИГЛАШЕНИЕ: обратный сценарий, контакт и выход", "invitation.db", invitation_flow),
        ):
            service = Service(Config(database=str(demo_root / filename)))
            messages = await flow(service)
            lines.append("=" * 60 + "\n" + title + "\n")
            for message in messages:
                who = "капитан" if message.chat.id == 101 else "участник"
                lines.append(f"Бот → {who} ({message.chat.id})\n{message.text}")
                if message.reply_markup:
                    labels = [button.text for row in message.reply_markup.inline_keyboard for button in row]
                    lines.append("Кнопки: " + " | ".join(labels))
                lines.append("")
            lines.append("Проверки сценария: ПРОЙДЕНЫ.\n")
    destination = Path("docs/demo-transcript.txt")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines), encoding="utf-8")
    print("Три локальных сценария пройдены. Протокол: docs/demo-transcript.txt")


if __name__ == "__main__":
    asyncio.run(demonstrate())
