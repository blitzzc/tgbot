import re
import unicodedata

ROLES = {
    "backend": "Бэкенд-разработчик",
    "frontend": "Фронтенд-разработчик",
    "mobile": "Мобильный разработчик",
    "design": "Дизайнер",
    "analytics": "Аналитик",
    "manager": "Менеджер / презентатор",
}
EXPERIENCE = {"beginner": "Новичок", "experienced": "Есть опыт"}
YES_NO = {"yes": "Да", "no": "Нет"}
COMMON_SKILLS = ["Python", "Java", "JavaScript", "TypeScript", "HTML", "CSS", "React", "Django", "FastAPI", "SQL", "PostgreSQL", "Git", "Docker", "Figma", "Анализ данных", "Презентации", "C++", "C#"]


ALIASES = {
    "питон": "python", "пайтон": "python", "джава": "java",
    "js": "javascript", "джаваскрипт": "javascript", "ts": "typescript",
    "postgres": "postgresql", "постгрес": "postgresql", "постгресql": "postgresql",
    "джанго": "django", "реакт": "react", "фигма": "figma",
    "гит": "git", "докер": "docker", "c sharp": "c#", "csharp": "c#",
    "data analysis": "анализ данных",
}


def normalize_skill(value):
    value = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    value = re.sub(r"\s+", " ", value).strip()
    return ALIASES.get(value, value)
