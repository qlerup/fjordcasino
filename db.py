from contextlib import contextmanager
import sqlite3


@contextmanager
def connect(path):
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=15000')
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def initialize(path):
    with connect(path) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, identity TEXT UNIQUE NOT NULL,
          username TEXT NOT NULL, password TEXT,
          balance INTEGER NOT NULL DEFAULT 0 CHECK(balance>=0), created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ledger (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
          kind TEXT NOT NULL, amount INTEGER NOT NULL, balance INTEGER NOT NULL,
          description TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ledger_user ON ledger(user_id,id DESC);
        CREATE TABLE IF NOT EXISTS daily_rewards (
          user_id INTEGER NOT NULL REFERENCES users(id), day TEXT NOT NULL,
          PRIMARY KEY(user_id,day)
        );
        CREATE TABLE IF NOT EXISTS actions (
          user_id INTEGER NOT NULL REFERENCES users(id), request_id TEXT NOT NULL,
          fingerprint TEXT NOT NULL, response TEXT NOT NULL, created_at TEXT NOT NULL,
          PRIMARY KEY(user_id,request_id)
        );
        CREATE TABLE IF NOT EXISTS blackjack (
          user_id INTEGER PRIMARY KEY REFERENCES users(id), state TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS login_attempts (address TEXT NOT NULL, at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS login_attempt_time ON login_attempts(at);
        PRAGMA user_version=1;
        ''')
