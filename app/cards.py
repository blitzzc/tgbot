from app.catalogs import EXPERIENCE, ROLES


def offer_reason(reason):
    text = reason or ""
    if "приостанов" in text.lower() or "закрыл место" in text.lower():
        text += " После возобновления набора и открытия места можно подать новую заявку. Старое предложение не восстановится."
    return text

OFFER_STATUS = {"pending": "Ожидает решения", "accepted": "Принято", "rejected": "Отклонено", "cancelled": "Отменено", "outdated": "Неактуально"}
PLACE_STATUS = {"open": "Открыто", "filled": "Заполнено", "closed": "Закрыто капитаном"}
TEAM_STATUS = {"open": "Набор открыт", "paused": "Набор приостановлен", "disbanded": "Расформирована"}


def names(values, catalog=None):
    return ", ".join(catalog.get(v, v) if catalog else v for v in values) or "Не указано"


def profile_card(p, timezone, short=False):
    if short:
        return f"{p['name']} · {ROLES[p['role']]}\nНавыки: {names(p['skills'])[:140]}\n{p['about'][:160]}\n{EXPERIENCE[p['experience']]}"
    return (
        f"Анкета: {p['name']}\n"
        f"Основная роль: {ROLES[p['role']]}\nДополнительные: {names(p['extra_roles'], ROLES)}\n"
        f"Навыки: {names(p['skills'])}\nО себе: {p['about']}\nОпыт: {EXPERIENCE[p['experience']]}\n"
        f"Проекты: {p.get('projects') or 'Не указаны'}\nСсылки: {p.get('links') or 'Не указаны'}\n"
        "\nНавыки и опыт указаны самим участником."
    )


def vacancy_card(v, timezone):
    return (
        f"Место №{v.get('id', 'новое')}: {ROLES[v['role']]}\n"
        f"Статус: {PLACE_STATUS.get(v.get('status', 'open'))}\nЗадачи: {v['tasks']}\n"
        f"Обязательные навыки: {names(v['required'])}\nЖелательные: {names(v['desired'])}\n"
        f"Принимаем новичка: {'Да' if v['beginner'] == 'yes' else 'Нет'}"
    )


def team_card(t, maximum, full=True):
    text = (
        f"Команда: {t['name']}\nТема: {t['idea']}\n"
        f"Статус: {TEAM_STATUS.get(t.get('status', 'open'))}"
    )
    if full:
        text += f"\nСостав: {len(t['members'])}/{maximum}\n"
        for p in t["members"]:
            captain = " · капитан" if p["user_id"] == t["captain_id"] else ""
            text += f"\n{p['name']}{captain} · {ROLES[p['team_role']]}\nНавыки: {names(p['skills'])[:180]}\nОпыт: {p['about'][:200]}\n"
        text += "\nНавыки и опыт указаны самими участниками. Контакты автоматически не раскрываются."
    return text
