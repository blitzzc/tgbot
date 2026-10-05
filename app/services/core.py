import json
import time
from urllib.parse import urlparse

from app.catalogs import (
    COMMON_SKILLS, EXPERIENCE, ROLES, normalize_skill,
)
from app.db import Database


class DomainError(Exception):
    """Понятная пользователю ошибка без личных данных и секретов."""


def dump(data):
    return json.dumps(data, ensure_ascii=False)


class Service:
    def __init__(self, config):
        self.config = config
        self.db = Database(config.database)

    def register(self, user_id, chat_id):
        with self.db.connect(write=True) as c:
            c.execute("INSERT INTO users(id,chat_id) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET chat_id=excluded.chat_id", (user_id, chat_id))

    @staticmethod
    def _text(data, key, maximum, required=True):
        value = str(data.get(key, "")).strip()
        if (required and not value) or len(value) > maximum:
            raise DomainError(f"Поле нужно заполнить; максимум {maximum} символов." if required else f"Максимум {maximum} символов.")
        data[key] = value

    @staticmethod
    def _choice(data, key, options):
        if data.get(key) not in options:
            raise DomainError("Выберите вариант кнопкой из списка.")

    @staticmethod
    def _many(data, key, options, required=False):
        values = data.get(key, [])
        if not isinstance(values, list) or any(value not in options for value in values):
            raise DomainError("Выберите значения из списка.")
        values = list(dict.fromkeys(values))
        if required and not values:
            raise DomainError("Выберите хотя бы одно значение.")
        data[key] = values

    @staticmethod
    def _skills(values, required=False):
        if not isinstance(values, list) or len(values) > 12:
            raise DomainError("Выберите не больше 12 навыков.")
        result = {}
        for value in values:
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= 40:
                raise DomainError("Название навыка: от 1 до 40 символов.")
            normal = normalize_skill(value)
            if not normal:
                raise DomainError("Укажите название навыка.")
            result[normal] = value.strip()
        if required and not result:
            raise DomainError("Нужен хотя бы один навык. Можно добавить свой.")
        return list(result.values())

    def validate_profile(self, data):
        data = dict(data)
        self._text(data, "name", 60)
        self._text(data, "about", 600)
        self._text(data, "projects", 600, False)
        self._text(data, "links", 500, False)
        self._choice(data, "role", ROLES)
        self._choice(data, "experience", EXPERIENCE)
        self._many(data, "extra_roles", ROLES)
        data["skills"] = self._skills(data.get("skills", []), True)
        if data["links"]:
            links = data["links"].split()
            if len(links) > 3 or any(urlparse(link).scheme not in {"http", "https"} or not urlparse(link).hostname for link in links):
                raise DomainError("Укажите до трёх ссылок с http:// или https:// либо пропустите поле.")
        keys = ("name", "role", "extra_roles", "skills", "about", "experience", "projects", "links")
        return {key: data[key] for key in keys}

    def validate_team(self, data):
        data = dict(data)
        self._text(data, "name", 80)
        self._text(data, "idea", 600, False)
        data["idea"] = data["idea"] or "Тему выберем вместе"
        if data["idea"] == "Идею выберем вместе":
            data["idea"] = "Тему выберем вместе"
        return {key: data[key] for key in ("name", "idea")}

    def validate_vacancy(self, data):
        data = dict(data)
        self._choice(data, "role", ROLES)
        self._text(data, "tasks", 400)
        self._choice(data, "beginner", {"yes", "no"})
        data["required"] = self._skills(data.get("required", []))
        data["desired"] = self._skills(data.get("desired", []))
        required = {normalize_skill(s) for s in data["required"]}
        data["desired"] = [s for s in data["desired"] if normalize_skill(s) not in required]
        return {key: data[key] for key in ("role", "tasks", "required", "desired", "beginner")}

    @staticmethod
    def _profile(c, user_id):
        row = c.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            raise DomainError("Сначала заполните и сохраните анкету.")
        return dict(json.loads(row["data"]), user_id=user_id, visible=bool(row["visible"]))

    def profile(self, user_id):
        with self.db.connect() as c:
            return self._profile(c, user_id)

    @staticmethod
    def _membership(c, user_id):
        row = c.execute("SELECT * FROM memberships WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    def membership(self, user_id):
        with self.db.connect() as c:
            return self._membership(c, user_id)

    @staticmethod
    def _team(c, team_id):
        row = c.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
        if not row:
            raise DomainError("Команда не найдена.")
        data = json.loads(row["data"])
        if data.get("idea") == "Идею выберем вместе":
            data["idea"] = "Тему выберем вместе"
        return dict(data, id=row["id"], captain_id=row["captain_id"], status=row["status"])

    @staticmethod
    def _vacancy(c, vacancy_id):
        row = c.execute("SELECT * FROM vacancies WHERE id=?", (vacancy_id,)).fetchone()
        if not row:
            raise DomainError("Место не найдено.")
        return dict(json.loads(row["data"]), id=row["id"], team_id=row["team_id"], status=row["status"], filled_by=row["filled_by"])

    def vacancy(self, vacancy_id):
        with self.db.connect() as c:
            return self._vacancy(c, vacancy_id)

    @classmethod
    def _captain(cls, c, actor, team_id):
        team = cls._team(c, team_id)
        member = cls._membership(c, actor)
        if team["status"] == "disbanded" or team["captain_id"] != actor or not member or member["team_id"] != team_id:
            raise DomainError("Это действие доступно только текущему капитану команды.")
        return team

    @staticmethod
    def _notify(c, user_id, body):
        c.execute("INSERT INTO notifications(user_id,body) VALUES(?,?)", (user_id, body))

    @classmethod
    def _finish_pending(cls, c, where, params, reason):
        rows = c.execute(
            "SELECT o.*,t.captain_id FROM offers o LEFT JOIN vacancies v ON v.id=o.vacancy_id JOIN teams t ON t.id=o.team_id WHERE o.status='pending' AND " + where,
            params,
        ).fetchall()
        for row in rows:
            c.execute("UPDATE offers SET status='outdated',reason=?,resolved_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'", (reason, row["id"]))
            for recipient in {row["user_id"], row["captain_id"]}:
                cls._notify(c, recipient, f"Предложение №{row['id']} стало неактуальным: {reason}")

    @staticmethod
    def _save_skills(c, values):
        ids = []
        for value in values:
            normal = normalize_skill(value)
            c.execute("INSERT INTO skills(name,normalized) VALUES(?,?) ON CONFLICT(normalized) DO NOTHING", (value, normal))
            ids.append(c.execute("SELECT id FROM skills WHERE normalized=?", (normal,)).fetchone()["id"])
        return ids

    def save_profile(self, user_id, data):
        data = self.validate_profile(data)
        with self.db.connect(write=True) as c:
            c.execute("INSERT INTO profiles(user_id,data) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data,updated_at=CURRENT_TIMESTAMP", (user_id, dump(data)))
            c.execute("DELETE FROM profile_skills WHERE user_id=?", (user_id,))
            for skill_id in self._save_skills(c, data["skills"]):
                c.execute("INSERT INTO profile_skills VALUES(?,?)", (user_id, skill_id))
            pending = c.execute("SELECT id,vacancy_id FROM offers WHERE user_id=? AND status='pending'", (user_id,)).fetchall()
            for offer in pending:
                if offer["vacancy_id"] is None:
                    continue
                place = self._vacancy(c, offer["vacancy_id"])
                team = self._team(c, place["team_id"])
                if self.incompatibilities(data, place, team):
                    self._finish_pending(c, "o.id=?", (offer["id"],), "Анкета больше не соответствует обязательным требованиям.")

    def set_visibility(self, user_id, visible):
        with self.db.connect(write=True) as c:
            self._profile(c, user_id)
            c.execute("UPDATE profiles SET visible=? WHERE user_id=?", (int(bool(visible)), user_id))

    def skill_names(self):
        with self.db.connect() as c:
            # Ограничиваем меню; свой навык можно ввести независимо от списка.
            rows = c.execute("SELECT name FROM skills ORDER BY id DESC LIMIT 30").fetchall()
            names = COMMON_SKILLS + [r["name"] for r in rows]
            unique = {}
            for name in names:
                unique.setdefault(normalize_skill(name), name)
            return list(unique.values())

    def create_team(self, actor, data):
        data = self.validate_team(data)
        with self.db.connect(write=True) as c:
            profile = self._profile(c, actor)
            if self._membership(c, actor):
                raise DomainError("Вы уже в команде. Сначала выйдите или передайте управление.")
            team_id = c.execute("INSERT INTO teams(captain_id,data) VALUES(?,?)", (actor, dump(data))).lastrowid
            c.execute("INSERT INTO memberships(user_id,team_id,role) VALUES(?,?,?)", (actor, team_id, profile["role"]))
            self._finish_pending(c, "o.user_id=?", (actor,), "Участник создал собственную команду.")
            return team_id

    def update_team(self, actor, team_id, data):
        data = self.validate_team(data)
        with self.db.connect(write=True) as c:
            self._captain(c, actor, team_id)
            c.execute("UPDATE teams SET data=? WHERE id=?", (dump(data), team_id))

    def team(self, team_id):
        with self.db.connect() as c:
            team = self._team(c, team_id)
            if team["status"] == "disbanded":
                raise DomainError("Команда расформирована.")
            rows = c.execute("SELECT * FROM memberships WHERE team_id=? ORDER BY joined_at,user_id", (team_id,)).fetchall()
            team["members"] = [dict(self._profile(c, row["user_id"]), team_role=row["role"]) for row in rows]
            rows = c.execute("SELECT id FROM vacancies WHERE team_id=? ORDER BY id", (team_id,)).fetchall()
            team["vacancies"] = [self._vacancy(c, row["id"]) for row in rows]
            return team

    def create_vacancy(self, actor, team_id, data):
        data = self.validate_vacancy(data)
        with self.db.connect(write=True) as c:
            team = self._captain(c, actor, team_id)
            if team["status"] != "open":
                raise DomainError("Сначала возобновите набор команды.")
            occupied = c.execute("SELECT COUNT(*) FROM memberships WHERE team_id=?", (team_id,)).fetchone()[0]
            opened = c.execute("SELECT COUNT(*) FROM vacancies WHERE team_id=? AND status='open'", (team_id,)).fetchone()[0]
            if occupied + opened >= self.config.max_team_size:
                raise DomainError("Лимит участников и открытых мест достигнут. Закройте лишнее место.")
            place_id = c.execute("INSERT INTO vacancies(team_id,data) VALUES(?,?)", (team_id, dump(data))).lastrowid
            self._write_vacancy_skills(c, place_id, data)
            return place_id

    def _write_vacancy_skills(self, c, place_id, data):
        c.execute("DELETE FROM vacancy_skills WHERE vacancy_id=?", (place_id,))
        for kind in ("required", "desired"):
            for skill_id in self._save_skills(c, data[kind]):
                c.execute("INSERT INTO vacancy_skills VALUES(?,?,?)", (place_id, skill_id, kind))

    def update_vacancy(self, actor, place_id, data):
        data = self.validate_vacancy(data)
        with self.db.connect(write=True) as c:
            place = self._vacancy(c, place_id)
            self._captain(c, actor, place["team_id"])
            if place["status"] != "open":
                raise DomainError("Редактировать можно только открытое место.")
            old_data = {key: place[key] for key in data}
            if old_data == data:
                return
            c.execute("UPDATE vacancies SET data=? WHERE id=?", (dump(data), place_id))
            self._write_vacancy_skills(c, place_id, data)
            self._finish_pending(c, "o.vacancy_id=?", (place_id,), "Капитан изменил описание или требования места.")

    def close_vacancy(self, actor, place_id):
        with self.db.connect(write=True) as c:
            place = self._vacancy(c, place_id)
            self._captain(c, actor, place["team_id"])
            if place["status"] != "open":
                raise DomainError("Это место уже закрыто или заполнено.")
            c.execute("UPDATE vacancies SET status='closed' WHERE id=?", (place_id,))
            self._finish_pending(c, "o.vacancy_id=?", (place_id,), "Капитан закрыл место.")

    def set_recruitment(self, actor, team_id, opened):
        with self.db.connect(write=True) as c:
            self._captain(c, actor, team_id)
            c.execute("UPDATE teams SET status=? WHERE id=?", ("open" if opened else "paused", team_id))
            if not opened:
                self._finish_pending(c, "t.id=?", (team_id,), "Набор команды приостановлен.")

    @staticmethod
    def incompatibilities(profile, place, team):
        reasons = []
        have = {normalize_skill(s) for s in profile["skills"]}
        missing = [s for s in place["required"] if normalize_skill(s) not in have]
        if missing:
            reasons.append("нет обязательных навыков: " + ", ".join(missing))
        if place["beginner"] == "no" and profile["experience"] == "beginner":
            reasons.append("для этого места нужен опыт")
        return reasons

    @staticmethod
    def ranking(profile, place, team):
        role = 2 if profile["role"] == place["role"] else (1 if place["role"] in profile["extra_roles"] else 0)
        have = {normalize_skill(s) for s in profile["skills"]}
        desired = [s for s in place["desired"] if normalize_skill(s) in have]
        explanations = []
        if role:
            explanations.append("Совпадает " + ("основная" if role == 2 else "дополнительная") + " роль: " + ROLES[place["role"]])
        if desired:
            explanations.append(f"Желательных навыков: {len(desired)} (" + ", ".join(desired) + ")")
        explanations.append("Выполнены обязательные требования")
        return (role, len(desired)), explanations

    @staticmethod
    def _filter(profile, place, team, filters, searching_people=False):
        if filters.get("role"):
            roles = {profile["role"], *profile["extra_roles"]} if searching_people else {place["role"]}
            if filters["role"] not in roles:
                return False
        if filters.get("skills"):
            skills = profile["skills"] if searching_people else place["required"] + place["desired"]
            if not {normalize_skill(s) for s in filters["skills"]} <= {normalize_skill(s) for s in skills}:
                return False
        return True

    def _application_status(self, c, actor, team, count):
        if team["status"] != "open":
            return False, "Набор приостановлен" if team["status"] == "paused" else "Команда расформирована"
        if count >= self.config.max_team_size:
            return False, "Команда заполнена"
        if self._membership(c, actor):
            return False, "Вы уже состоите в команде"
        if not c.execute("SELECT 1 FROM profiles WHERE user_id=?", (actor,)).fetchone():
            return False, "Сначала заполните анкету"
        if c.execute("SELECT 1 FROM offers WHERE user_id=? AND team_id=? AND vacancy_id IS NULL AND status='pending'", (actor, team["id"])).fetchone():
            return False, "Заявка уже отправлена"
        return True, "Можно отправить заявку"

    def team_application_status(self, actor, team_id):
        with self.db.connect() as c:
            team = self._team(c, team_id)
            count = c.execute("SELECT COUNT(*) FROM memberships WHERE team_id=?", (team_id,)).fetchone()[0]
            return self._application_status(c, actor, team, count)

    def search_teams(self, actor, recommended=False, filters=None):
        filters = filters or {}
        with self.db.connect() as c:
            try:
                profile = self._profile(c, actor)
            except DomainError:
                if recommended:
                    raise
                profile = None
            if recommended and self._membership(c, actor):
                raise DomainError("Вы уже в команде. Все составы можно посмотреть в разделе «Команды».")
            if recommended and not profile["visible"]:
                raise DomainError("Для рекомендаций покажите анкету в поиске через «Моя анкета». Самостоятельный просмотр и уже отправленные предложения доступны.")
            rows = c.execute("SELECT id FROM teams WHERE status<>'disbanded' ORDER BY id").fetchall()
            result = []
            for row in rows:
                team = self._team(c, row["id"])
                count = c.execute("SELECT COUNT(*) FROM memberships WHERE team_id=?", (team["id"],)).fetchone()[0]
                if recommended and (team["status"] != "open" or count >= self.config.max_team_size):
                    continue
                places = [self._vacancy(c, r["id"]) for r in c.execute("SELECT id FROM vacancies WHERE team_id=? AND status='open' ORDER BY id", (team["id"],))]
                members = [self._profile(c, r["user_id"]) for r in c.execute("SELECT user_id FROM memberships WHERE team_id=?", (team["id"],))]
                roles = {p["role"] for p in places} | {p["role"] for p in members}
                skills = {normalize_skill(s) for p in places for s in p["required"] + p["desired"]} | {normalize_skill(s) for p in members for s in p["skills"]}
                if filters.get("role") and filters["role"] not in roles:
                    continue
                if not {normalize_skill(s) for s in filters.get("skills", [])} <= skills:
                    continue
                compatible = [p for p in places if profile and not self.incompatibilities(profile, p, team)]
                place = max(compatible, key=lambda p: self.ranking(profile, p, team)[0]) if compatible else (places[0] if places and not recommended else None)
                score, why = self.ranking(profile, place, team) if profile and place and not self.incompatibilities(profile, place, team) else ((0, 0), ["Набор открыт; общая заявка не требует выбора позиции"])
                can_apply, status = self._application_status(c, actor, team, count)
                result.append({"team": team, "vacancy": place, "score": score, "why": why, "count": count, "can_apply": can_apply, "application_status": status})
            return sorted(result, key=lambda item: (*(-v for v in item["score"]), item["team"]["id"])) if recommended else sorted(result, key=lambda item: item["team"]["id"])

    def search_people(self, actor, place_id, recommended=False, filters=None):
        with self.db.connect() as c:
            place = self._vacancy(c, place_id)
            team = self._captain(c, actor, place["team_id"])
            if place["status"] != "open" or team["status"] != "open":
                raise DomainError("Поиск доступен для открытого места при открытом наборе.")
            rows = c.execute("SELECT p.user_id FROM profiles p LEFT JOIN memberships m ON m.user_id=p.user_id WHERE p.visible=1 AND m.user_id IS NULL ORDER BY p.user_id").fetchall()
            result = []
            for row in rows:
                profile = self._profile(c, row["user_id"])
                if self.incompatibilities(profile, place, team) or not self._filter(profile, place, team, filters or {}, True):
                    continue
                score, why = self.ranking(profile, place, team)
                result.append({"profile": profile, "score": score, "why": why})
            return sorted(result, key=lambda item: (*(-v for v in item["score"]), item["profile"]["user_id"])) if recommended else result

    def candidate(self, actor, place_id, user_id):
        # Повторно проверяем видимость и свободу участника по старой кнопке.
        candidates = self.search_people(actor, place_id)
        match = next((item["profile"] for item in candidates if item["profile"]["user_id"] == user_id), None)
        if not match:
            raise DomainError("Участник больше не доступен для этого места.")
        return match

    def create_offer(self, actor, kind, user_id, place_id, message, team_id=None):
        if kind not in {"application", "invitation"}:
            raise DomainError("Неизвестный тип предложения.")
        message = str(message).strip()
        if not 1 <= len(message) <= 300:
            raise DomainError("Сообщение должно содержать от 1 до 300 символов.")
        with self.db.connect(write=True) as c:
            place = self._vacancy(c, place_id) if place_id is not None else None
            if place is None and (kind != "application" or team_id is None):
                raise DomainError("Для приглашения выберите конкретное место.")
            team = self._team(c, place["team_id"] if place else team_id)
            if kind == "application" and actor != user_id:
                raise DomainError("Заявку можно отправить только от своего имени.")
            if kind == "invitation":
                self._captain(c, actor, team["id"])
            profile = self._profile(c, user_id)
            if self._membership(c, user_id):
                raise DomainError("Участник уже в команде.")
            if kind == "invitation" and not profile["visible"]:
                raise DomainError("Участник скрыл анкету.")
            if (place and place["status"] != "open") or team["status"] != "open":
                raise DomainError("Это место или набор команды уже закрыты.")
            count = c.execute("SELECT COUNT(*) FROM memberships WHERE team_id=?", (team["id"],)).fetchone()[0]
            if count >= self.config.max_team_size:
                raise DomainError("Команда заполнена. Отправить заявку сейчас нельзя.")
            reasons = self.incompatibilities(profile, place, team) if place else []
            if reasons:
                raise DomainError("Не выполнены обязательные требования: " + "; ".join(reasons) + ".")
            existing = c.execute("SELECT id FROM offers WHERE user_id=? AND vacancy_id IS ? AND team_id=? AND status='pending'", (user_id, place_id, team["id"])).fetchone()
            if existing:
                raise DomainError(f"Уже есть активное предложение №{existing['id']}. Откройте «Заявки и приглашения».")
            offer_id = c.execute("INSERT INTO offers(kind,user_id,team_id,vacancy_id,sender_id,message) VALUES(?,?,?,?,?,?)", (kind, user_id, team["id"], place_id, actor, message)).lastrowid
            recipient = team["captain_id"] if kind == "application" else user_id
            self._notify(c, recipient, f"Новое предложение №{offer_id}. Откройте «Заявки и приглашения», чтобы посмотреть команду, анкету и сообщение.")
            return offer_id

    @classmethod
    def _offer(cls, c, offer_id):
        row = c.execute("SELECT * FROM offers WHERE id=?", (offer_id,)).fetchone()
        if not row:
            raise DomainError("Предложение не найдено.")
        offer = dict(row)
        place = cls._vacancy(c, offer["vacancy_id"]) if offer["vacancy_id"] is not None else None
        team = cls._team(c, offer["team_id"])
        return offer, place, team

    @staticmethod
    def _offer_access(actor, offer, team):
        if actor not in {offer["user_id"], offer["sender_id"], team["captain_id"]}:
            raise DomainError("У вас нет доступа к этому предложению.")

    def offer(self, actor, offer_id):
        with self.db.connect() as c:
            offer, place, team = self._offer(c, offer_id)
            self._offer_access(actor, offer, team)
            offer.update(vacancy=place, team=team, profile=self._profile(c, offer["user_id"]))
            return offer

    def offers(self, actor):
        with self.db.connect() as c:
            rows = c.execute("SELECT o.id FROM offers o JOIN teams t ON t.id=o.team_id WHERE o.user_id=? OR o.sender_id=? OR t.captain_id=? ORDER BY (o.status='pending') DESC,o.id DESC", (actor, actor, actor)).fetchall()
            result = []
            for row in rows:
                offer, place, team = self._offer(c, row["id"])
                result.append(dict(offer, vacancy=place, team=team))
            return result

    def resolve_offer(self, actor, offer_id, action):
        if action not in {"accept", "reject", "cancel"}:
            raise DomainError("Неизвестное действие.")
        with self.db.connect(write=True) as c:
            offer, place, team = self._offer(c, offer_id)
            self._offer_access(actor, offer, team)
            recipient = team["captain_id"] if offer["kind"] == "application" else offer["user_id"]
            if action == "cancel":
                if actor != offer["sender_id"]:
                    raise DomainError("Отменить предложение может только отправитель.")
            elif actor != recipient:
                raise DomainError("Решение может принять только получатель предложения.")
            if offer["status"] != "pending":
                return offer["status"]
            if action != "cancel" and offer["kind"] == "application":
                self._captain(c, actor, team["id"])
            if action == "accept":
                profile = self._profile(c, offer["user_id"])
                if self._membership(c, offer["user_id"]):
                    raise DomainError("Участник уже вступил в другую команду.")
                if (place and place["status"] != "open") or team["status"] != "open":
                    raise DomainError("Место или набор команды закрыты.")
                count = c.execute("SELECT COUNT(*) FROM memberships WHERE team_id=?", (team["id"],)).fetchone()[0]
                if count >= self.config.max_team_size:
                    raise DomainError("В команде нет свободных мест.")
                if place and self.incompatibilities(profile, place, team):
                    raise DomainError("Анкета больше не соответствует обязательным требованиям места.")
                role = place["role"] if place else profile["role"]
                c.execute("INSERT INTO memberships(user_id,team_id,role) VALUES(?,?,?)", (offer["user_id"], team["id"], role))
                if place:
                    c.execute("UPDATE vacancies SET status='filled',filled_by=? WHERE id=? AND status='open'", (offer["user_id"], place["id"]))
                status = "accepted"
            else:
                status = "cancelled" if action == "cancel" else "rejected"
            c.execute("UPDATE offers SET status=?,resolved_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'", (status, offer_id))
            if status == "accepted":
                self._finish_pending(c, "(o.user_id=? OR o.vacancy_id=?)", (offer["user_id"], place["id"] if place else None), "Участник вступил в команду или место занято.")
                if count + 1 >= self.config.max_team_size:
                    self._finish_pending(c, "t.id=?", (team["id"],), "Команда заполнена.")
                    c.execute("UPDATE vacancies SET status='closed' WHERE team_id=? AND status='open'", (team["id"],))
            labels = {"accepted": "принято — состав обновлён", "rejected": "отклонено", "cancelled": "отменено"}
            for person in {offer["user_id"], team["captain_id"]}:
                self._notify(c, person, f"Предложение №{offer_id} {labels[status]}." + (" Контакт можно добровольно передать через «Моя команда»." if status == "accepted" else ""))
            return status

    def leave_team(self, actor, team_id):
        with self.db.connect(write=True) as c:
            member = self._membership(c, actor)
            if not member or member["team_id"] != team_id:
                raise DomainError("Вы уже вышли или не состоите в этой команде.")
            team = self._team(c, team_id)
            if team["captain_id"] == actor:
                raise DomainError("Сначала передайте управление участнику или расформируйте команду.")
            name = self._profile(c, actor)["name"]
            c.execute("DELETE FROM memberships WHERE user_id=?", (actor,))
            self._notify(c, team["captain_id"], f"{name} вышел(а) из команды. Старое место не открыто: при необходимости создайте новое.")
            self._notify(c, actor, "Вы вышли из команды. Теперь можно искать другую или создать свою.")

    def transfer_captain(self, actor, team_id, new_captain):
        with self.db.connect(write=True) as c:
            self._captain(c, actor, team_id)
            member = self._membership(c, new_captain)
            if new_captain == actor or not member or member["team_id"] != team_id:
                raise DomainError("Выберите другого действующего участника команды.")
            c.execute("UPDATE teams SET captain_id=? WHERE id=?", (new_captain, team_id))
            for row in c.execute("SELECT user_id FROM memberships WHERE team_id=?", (team_id,)).fetchall():
                self._notify(c, row["user_id"], "Управление командой передано участнику: " + self._profile(c, new_captain)["name"])

    def change_role(self, actor, team_id, user_id, role):
        if role not in ROLES:
            raise DomainError("Выберите роль из списка.")
        with self.db.connect(write=True) as c:
            self._captain(c, actor, team_id)
            member = self._membership(c, user_id)
            if not member or member["team_id"] != team_id:
                raise DomainError("Участник уже не состоит в этой команде.")
            c.execute("UPDATE memberships SET role=? WHERE user_id=?", (role, user_id))
            self._notify(c, user_id, "Ваша роль в команде изменена: " + ROLES[role] + ". Личная анкета не изменена.")

    def disband_team(self, actor, team_id):
        with self.db.connect(write=True) as c:
            self._captain(c, actor, team_id)
            for row in c.execute("SELECT user_id FROM memberships WHERE team_id=?", (team_id,)).fetchall():
                self._notify(c, row["user_id"], "Капитан расформировал команду. Теперь можно искать другую или создать свою.")
            self._finish_pending(c, "t.id=?", (team_id,), "Команда расформирована.")
            c.execute("UPDATE vacancies SET status='closed' WHERE team_id=? AND status='open'", (team_id,))
            c.execute("DELETE FROM memberships WHERE team_id=?", (team_id,))
            c.execute("UPDATE teams SET status='disbanded' WHERE id=?", (team_id,))

    def share_contact(self, actor, team_id, contact, expected_recipients):
        contact = str(contact).strip()
        if not 1 <= len(contact) <= 200:
            raise DomainError("Контакт: от 1 до 200 символов.")
        with self.db.connect(write=True) as c:
            member = self._membership(c, actor)
            if not member or member["team_id"] != team_id:
                raise DomainError("Вы уже не состоите в этой команде.")
            recipients = [r["user_id"] for r in c.execute("SELECT user_id FROM memberships WHERE team_id=? AND user_id<>? ORDER BY user_id", (team_id, actor))]
            if not recipients or recipients != sorted(expected_recipients):
                raise DomainError("Состав изменился. Начните передачу контакта заново, чтобы подтвердить получателей.")
            c.execute("UPDATE memberships SET shared_contact=? WHERE user_id=?", (contact, actor))
            name = self._profile(c, actor)["name"]
            for recipient in recipients:
                self._notify(c, recipient, f"{name} добровольно поделился(ась) контактом с командой:\n{contact}")

    def pending_notifications(self):
        with self.db.connect() as c:
            return [dict(row) for row in c.execute("SELECT n.*,u.chat_id FROM notifications n JOIN users u ON u.id=n.user_id WHERE status='pending' AND next_attempt<=? ORDER BY id LIMIT 20", (time.time(),))]

    def notification_result(self, notification_id, success, permanent=False, retry_after=None):
        with self.db.connect(write=True) as c:
            row = c.execute("SELECT attempts FROM notifications WHERE id=?", (notification_id,)).fetchone()
            if not row:
                return
            attempts = row["attempts"] + 1
            status = "sent" if success else ("failed" if permanent or attempts >= 5 else "pending")
            delay = retry_after if retry_after is not None else min(300, 2 ** attempts)
            c.execute("UPDATE notifications SET status=?,attempts=?,next_attempt=? WHERE id=?", (status, attempts, time.time() + delay, notification_id))
