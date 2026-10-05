from app.catalogs import EXPERIENCE, ROLES, YES_NO


def field(key, title, kind="text", options=None, required=True, maximum=600):
    return {"key": key, "title": title, "kind": kind, "options": options, "required": required, "maximum": maximum}


def fields(kind, config, legacy=False):
    if kind == "profile":
        original = [
            field("name", "Имя или псевдоним", maximum=60),
            field("role", "Основная роль", "choice", ROLES),
            field("extra_roles", "Дополнительные роли (можно пропустить)", "multi", ROLES, False),
            field("skills", "Навыки: выберите из списка или добавьте свой", "skills"),
            field("about", "Коротко о себе и опыте"),
            field("experience", "Как вы оцениваете свой опыт?", "choice", EXPERIENCE),
            field("projects", "Проекты (необязательно)", required=False),
            field("links", "До трёх ссылок с https:// (необязательно)", required=False, maximum=500),
        ]
        if legacy:
            return original
        return [original[i] for i in (1, 3, 4, 5, 0, 2, 6, 7)]
    if kind == "team":
        return [
            field("name", "Название команды", maximum=80),
            field("idea", "Тема — рекомендуем указать, чтобы участникам было проще выбрать команду", required=False),
        ]
    if kind == "vacancy":
        return [
            field("role", "Нужная роль", "choice", ROLES),
            field("tasks", "Коротко опишите задачи", maximum=400),
            field("required", "Обязательные навыки (можно без требований)", "skills", required=False),
            field("desired", "Желательные навыки (можно пропустить)", "skills", required=False),
            field("beginner", "Готовы принять новичка?", "choice", YES_NO),
        ]
    if kind == "filters":
        return [
            field("role", "Фильтр по роли (пропустить = любая)", "choice", ROLES, False),
            field("skills", "Фильтр по навыкам: нужны все выбранные", "skills", required=False),
        ]
    if kind == "message":
        return [field("message", "Короткое сообщение получателю", maximum=300)]
    if kind == "contact":
        return [field("contact", "Введите контакт, которым хотите поделиться: например, @имя или ссылка. Телефон не обязателен.", maximum=200)]
    if kind == "role":
        return [field("role", "Роль участника в команде. Личная анкета не изменится.", "choice", ROLES)]
    raise ValueError("Unknown form")
