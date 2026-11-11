import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("FOODIE_DATA", Path(__file__).resolve().parent.parent / "data"))
DB_PATH = DATA_DIR / "foodie.db"


def _database_url():
    url = os.environ.get("DATABASE_URL", "").strip()
    if url.startswith("postgres://") or url.startswith("postgresql://"):
        return url
    return ""


class _PgResult:
    def __init__(self, cursor, lastrowid):
        self._cursor = cursor
        self.lastrowid = lastrowid
        self.rowcount = cursor.rowcount

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class _PgConnection:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type:
                self._conn.rollback()
            else:
                self._conn.commit()
        finally:
            self._conn.close()

    def execute(self, sql, params=()):
        translated = sql.replace("?", "%s")
        if translated.lstrip().upper().startswith("INSERT OR IGNORE"):
            translated = "INSERT" + translated.lstrip()[len("INSERT OR IGNORE"):]
            translated = translated.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        returning = translated.lstrip().upper().startswith("INSERT") and "RETURNING" not in translated.upper()
        if returning:
            translated = translated.rstrip().rstrip(";") + " RETURNING id"
        cursor = self._conn.execute(translated, params)
        lastrowid = None
        if returning:
            row = cursor.fetchone()
            if row:
                lastrowid = row["id"]
        return _PgResult(cursor, lastrowid)

    def executemany(self, sql, seq):
        translated = sql.replace("?", "%s")
        with self._conn.cursor() as cursor:
            cursor.executemany(translated, list(seq))
        return cursor

    def executescript(self, script):
        for statement in script.split(";"):
            statement = statement.strip()
            if statement:
                self._conn.execute(statement)


def _sqlite_path():
    directory = DATA_DIR
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".write-test"
        probe.write_text("ok")
        probe.unlink()
    except OSError:
        directory = Path("/tmp/foodie")
        directory.mkdir(parents=True, exist_ok=True)
    return directory / "foodie.db"


def connect():
    url = _database_url()
    if url:
        from psycopg import connect as pg_connect
        from psycopg.rows import dict_row

        return _PgConnection(pg_connect(url, row_factory=dict_row))
    conn = sqlite3.connect(_sqlite_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  foods TEXT NOT NULL,
  pref TEXT NOT NULL DEFAULT '',
  unsubscribe_token TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  session_token TEXT
);

CREATE TABLE IF NOT EXISTS dishes (
  id BIGSERIAL PRIMARY KEY,
  menu_date TEXT NOT NULL,
  meal TEXT NOT NULL,
  hall TEXT NOT NULL,
  station TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL,
  recipe_id TEXT NOT NULL DEFAULT '',
  tags TEXT NOT NULL DEFAULT '',
  UNIQUE(menu_date, meal, hall, station, name)
);

CREATE TABLE IF NOT EXISTS interactions (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  menu_date TEXT NOT NULL,
  dish_name TEXT NOT NULL,
  signal TEXT NOT NULL CHECK(signal IN ('up', 'down')),
  created_at TEXT NOT NULL,
  UNIQUE(user_id, menu_date, dish_name)
);

CREATE TABLE IF NOT EXISTS outbox (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  menu_date TEXT NOT NULL,
  subject TEXT NOT NULL,
  body_html TEXT NOT NULL,
  body_text TEXT NOT NULL,
  sent_at TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(user_id, menu_date)
);

CREATE TABLE IF NOT EXISTS saved_preferences (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  preference TEXT NOT NULL,
  label TEXT NOT NULL,
  words TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(user_id, preference)
);

CREATE TABLE IF NOT EXISTS day_plans (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  menu_date TEXT NOT NULL,
  meal TEXT NOT NULL,
  hall TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(user_id, menu_date, meal, hall)
);

CREATE TABLE IF NOT EXISTS favorites (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  dish_name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(user_id, dish_name)
);

CREATE TABLE IF NOT EXISTS menu_days (
  id BIGSERIAL PRIMARY KEY,
  menu_date TEXT NOT NULL UNIQUE,
  boutique INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_restrictions (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  kind TEXT NOT NULL,
  value TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(user_id, kind, value)
);

CREATE TABLE IF NOT EXISTS never_preferences (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  preference TEXT NOT NULL,
  label TEXT NOT NULL,
  words TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(user_id, preference)
);

CREATE TABLE IF NOT EXISTS concept_scores (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  preference TEXT NOT NULL,
  like_n INTEGER NOT NULL DEFAULT 0,
  pass_n INTEGER NOT NULL DEFAULT 0,
  never_n INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  UNIQUE(user_id, preference)
);
"""


def _allow_several_places_per_meal(conn):
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'day_plans'"
    ).fetchone()
    if not row:
        return
    compact = "".join((row["sql"] or "").split())
    if "UNIQUE(user_id,menu_date,meal,hall)" in compact:
        return
    conn.executescript(
        """
        CREATE TABLE day_plans_next (
          id INTEGER PRIMARY KEY,
          user_id INTEGER NOT NULL REFERENCES users(id),
          menu_date TEXT NOT NULL,
          meal TEXT NOT NULL,
          hall TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(user_id, menu_date, meal, hall)
        );
        INSERT INTO day_plans_next (id, user_id, menu_date, meal, hall, created_at)
          SELECT id, user_id, menu_date, meal, hall, created_at FROM day_plans;
        DROP TABLE day_plans;
        ALTER TABLE day_plans_next RENAME TO day_plans;
        """
    )


_ready_for = None


def init_db():
    global _ready_for
    key = _database_url() or str(_sqlite_path())
    if _ready_for == key:
        return
    _init_db_once()
    _ready_for = key


def _init_db_once():
    if _database_url():
        with connect() as conn:
            conn.executescript(POSTGRES_SCHEMA)
            conn.execute(
                "ALTER TABLE day_plans DROP CONSTRAINT IF EXISTS day_plans_user_id_menu_date_meal_key"
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS day_plans_user_date_meal_hall
                ON day_plans (user_id, menu_date, meal, hall)
                """
            )
        return
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY,
              email TEXT NOT NULL UNIQUE COLLATE NOCASE,
              foods TEXT NOT NULL,
              pref TEXT NOT NULL DEFAULT '',
              unsubscribe_token TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS dishes (
              id INTEGER PRIMARY KEY,
              menu_date TEXT NOT NULL,
              meal TEXT NOT NULL,
              hall TEXT NOT NULL,
              station TEXT NOT NULL DEFAULT '',
              name TEXT NOT NULL,
              recipe_id TEXT NOT NULL DEFAULT '',
              tags TEXT NOT NULL DEFAULT '',
              UNIQUE(menu_date, meal, hall, station, name)
            );

            CREATE TABLE IF NOT EXISTS interactions (
              id INTEGER PRIMARY KEY,
              user_id INTEGER NOT NULL REFERENCES users(id),
              menu_date TEXT NOT NULL,
              dish_name TEXT NOT NULL,
              signal TEXT NOT NULL CHECK(signal IN ('up', 'down')),
              created_at TEXT NOT NULL,
              UNIQUE(user_id, menu_date, dish_name)
            );

            CREATE TABLE IF NOT EXISTS outbox (
              id INTEGER PRIMARY KEY,
              user_id INTEGER NOT NULL REFERENCES users(id),
              menu_date TEXT NOT NULL,
              subject TEXT NOT NULL,
              body_html TEXT NOT NULL,
              body_text TEXT NOT NULL,
              sent_at TEXT,
              created_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS outbox_user_date ON outbox(user_id, menu_date);

            CREATE TABLE IF NOT EXISTS saved_preferences (
              id INTEGER PRIMARY KEY,
              user_id INTEGER NOT NULL REFERENCES users(id),
              preference TEXT NOT NULL,
              label TEXT NOT NULL,
              words TEXT NOT NULL,
              created_at TEXT NOT NULL,
              UNIQUE(user_id, preference)
            );

            CREATE TABLE IF NOT EXISTS day_plans (
              id INTEGER PRIMARY KEY,
              user_id INTEGER NOT NULL REFERENCES users(id),
              menu_date TEXT NOT NULL,
              meal TEXT NOT NULL,
              hall TEXT NOT NULL,
              created_at TEXT NOT NULL,
              UNIQUE(user_id, menu_date, meal, hall)
            );

            CREATE TABLE IF NOT EXISTS favorites (
              id INTEGER PRIMARY KEY,
              user_id INTEGER NOT NULL REFERENCES users(id),
              dish_name TEXT NOT NULL,
              created_at TEXT NOT NULL,
              UNIQUE(user_id, dish_name)
            );

            CREATE TABLE IF NOT EXISTS menu_days (
              id INTEGER PRIMARY KEY,
              menu_date TEXT NOT NULL UNIQUE,
              boutique INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS user_restrictions (
              id INTEGER PRIMARY KEY,
              user_id INTEGER NOT NULL REFERENCES users(id),
              kind TEXT NOT NULL,
              value TEXT NOT NULL,
              created_at TEXT NOT NULL,
              UNIQUE(user_id, kind, value)
            );

            CREATE TABLE IF NOT EXISTS never_preferences (
              id INTEGER PRIMARY KEY,
              user_id INTEGER NOT NULL REFERENCES users(id),
              preference TEXT NOT NULL,
              label TEXT NOT NULL,
              words TEXT NOT NULL,
              created_at TEXT NOT NULL,
              UNIQUE(user_id, preference)
            );

            CREATE TABLE IF NOT EXISTS concept_scores (
              id INTEGER PRIMARY KEY,
              user_id INTEGER NOT NULL REFERENCES users(id),
              preference TEXT NOT NULL,
              like_n INTEGER NOT NULL DEFAULT 0,
              pass_n INTEGER NOT NULL DEFAULT 0,
              never_n INTEGER NOT NULL DEFAULT 0,
              updated_at TEXT NOT NULL,
              UNIQUE(user_id, preference)
            );
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        if "session_token" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN session_token TEXT")
        _allow_several_places_per_meal(conn)


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
