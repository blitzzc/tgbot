CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS fsm_sessions (
    key TEXT PRIMARY KEY,
    state TEXT,
    data TEXT NOT NULL DEFAULT '{}',
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    data TEXT NOT NULL,
    visible INTEGER NOT NULL DEFAULT 1 CHECK(visible IN (0,1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    normalized TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS profile_skills (
    user_id INTEGER NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id),
    PRIMARY KEY(user_id, skill_id)
);
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY,
    captain_id INTEGER NOT NULL REFERENCES users(id),
    data TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','paused','disbanded'))
);
CREATE TABLE IF NOT EXISTS memberships (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    role TEXT NOT NULL,
    shared_contact TEXT,
    joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    generation TEXT NOT NULL DEFAULT (lower(hex(randomblob(8))))
);
CREATE TABLE IF NOT EXISTS vacancies (
    id INTEGER PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES teams(id),
    data TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','filled','closed')),
    filled_by INTEGER REFERENCES users(id),
    version INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS vacancy_skills (
    vacancy_id INTEGER NOT NULL REFERENCES vacancies(id),
    skill_id INTEGER NOT NULL REFERENCES skills(id),
    kind TEXT NOT NULL CHECK(kind IN ('required','desired')),
    PRIMARY KEY(vacancy_id, skill_id, kind)
);
CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('application','invitation')),
    user_id INTEGER NOT NULL REFERENCES users(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    vacancy_id INTEGER REFERENCES vacancies(id),
    sender_id INTEGER NOT NULL REFERENCES users(id),
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','rejected','cancelled','outdated')),
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT,
    sent_at REAL NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_offer
    ON offers(user_id, vacancy_id) WHERE status='pending';
CREATE INDEX IF NOT EXISTS vacancies_team ON vacancies(team_id);
CREATE INDEX IF NOT EXISTS members_team ON memberships(team_id);
CREATE INDEX IF NOT EXISTS offers_place ON offers(vacancy_id, status);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sent','failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt REAL NOT NULL DEFAULT 0,
    sending_at REAL,
    claim_token TEXT,
    uncertain INTEGER NOT NULL DEFAULT 0,
    subjects TEXT NOT NULL DEFAULT '[]'
);
