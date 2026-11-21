"""
SQLite-хранилище обработанных сообщений/постов (leads.db).

Ключи дедупликации:
  1) (source, item_id) — одно и то же сообщение/пост никогда не обрабатывается дважды;
  2) fingerprint — нормализованный хеш текста: одинаковый текст из разных чатов/сабреддитов
     (кросс-постинг) не присылается повторно в течение DEDUP_DAYS.

Все операции синхронные и очень быстрые (локальный файл, WAL), поэтому вызываются прямо из event loop.
Ошибки SQLite логируются и не роняют процесс.
"""
from __future__ import annotations

import logging
import sqlite3
import time

log = logging.getLogger("leads.storage")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    source      TEXT    NOT NULL,
    item_id     TEXT    NOT NULL,
    fingerprint TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL,          -- queued | sent | failed | rejected | dup | old
    score       INTEGER NOT NULL DEFAULT 0,
    lang        TEXT    NOT NULL DEFAULT '',
    url         TEXT    NOT NULL DEFAULT '',
    created     REAL    NOT NULL,
    PRIMARY KEY (source, item_id)
);
CREATE INDEX IF NOT EXISTS idx_items_fp ON items (fingerprint, created);
CREATE INDEX IF NOT EXISTS idx_items_created ON items (created);
"""


class Storage:
    def __init__(self, path: str) -> None:
        self.path = path
        self.conn = sqlite3.connect(path, timeout=15, isolation_level=None, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(_SCHEMA)

    # --- чтение ---
    def seen(self, source: str, item_id: str) -> bool:
        try:
            row = self.conn.execute("SELECT 1 FROM items WHERE source=? AND item_id=?", (source, item_id)).fetchone()
            return row is not None
        except sqlite3.Error as exc:
            log.error("SQLite seen(): %s", exc)
            return False

    def seen_fingerprint(self, fp: str, days: int) -> bool:
        """Такой же текст уже был отправлен (или стоит в очереди) за последние `days` дней."""
        if not fp:
            return False
        try:
            row = self.conn.execute(
                "SELECT 1 FROM items WHERE fingerprint=? AND status IN ('queued','sent') AND created>? LIMIT 1",
                (fp, time.time() - days * 86400),
            ).fetchone()
            return row is not None
        except sqlite3.Error as exc:
            log.error("SQLite seen_fingerprint(): %s", exc)
            return False

    def stats(self, hours: int = 24) -> dict[str, int]:
        try:
            rows = self.conn.execute(
                "SELECT status, COUNT(*) FROM items WHERE created>? GROUP BY status", (time.time() - hours * 3600,)
            ).fetchall()
            return dict(rows)
        except sqlite3.Error as exc:
            log.error("SQLite stats(): %s", exc)
            return {}

    # --- запись ---
    def mark(self, source: str, item_id: str, status: str, *, fingerprint: str = "", score: int = 0,
             lang: str = "", url: str = "") -> None:
        try:
            self.conn.execute(
                "INSERT INTO items (source, item_id, fingerprint, status, score, lang, url, created) "
                "VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(source, item_id) DO UPDATE SET status=excluded.status",
                (source, item_id, fingerprint, status, score, lang, url, time.time()),
            )
        except sqlite3.Error as exc:
            log.error("SQLite mark(): %s", exc)

    def set_status(self, source: str, item_id: str, status: str) -> None:
        try:
            self.conn.execute("UPDATE items SET status=? WHERE source=? AND item_id=?", (status, source, item_id))
        except sqlite3.Error as exc:
            log.error("SQLite set_status(): %s", exc)

    def cleanup(self, keep_days: int = 60) -> int:
        try:
            cur = self.conn.execute("DELETE FROM items WHERE created<?", (time.time() - keep_days * 86400,))
            return cur.rowcount
        except sqlite3.Error as exc:
            log.error("SQLite cleanup(): %s", exc)
            return 0

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:
            pass
