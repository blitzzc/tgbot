import json
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class Config:
    name: str = "Учебный хакатон"
    max_team_size: int = 4
    timezone: str = "Asia/Almaty"
    database: str = "data/bot.db"
    max_offers_per_day: int = 10

    def __post_init__(self):
        if not self.name.strip() or len(self.name) > 100:
            raise ValueError("Название соревнования должно содержать от 1 до 100 символов.")
        if type(self.max_team_size) is not int or not 2 <= self.max_team_size <= 20:
            raise ValueError("Максимальный размер команды: целое число от 2 до 20.")
        if not isinstance(self.database, str) or not self.database.strip():
            raise ValueError("Не указан путь базы данных.")
        if type(self.max_offers_per_day) is not int or not 1 <= self.max_offers_per_day <= 100:
            raise ValueError("Лимит предложений за сутки: целое число от 1 до 100.")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            raise ValueError("Неизвестный часовой пояс. Установите зависимости проекта.") from None


def load_config(path="config.json"):
    file = Path(path)
    if not file.is_file():
        file = Path("config.example.json")
    data = json.loads(file.read_text(encoding="utf-8"))
    # Совместимость с конфигурацией прежней версии: поле больше не используется.
    data.pop("format", None)
    return Config(**data)
