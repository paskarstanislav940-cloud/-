"""
fioritura lead parser — главный цикл.

    python main.py                 мониторинг: Telegram + Reddit + Hacker News → алерты в бота
    python main.py --dry-run       то же, но алерты печатаются в консоль (бот не нужен)
    python main.py --login         первый вход в Telegram-аккаунт (телефон + код), создаёт .session
    python main.py --list-chats    показать ваши чаты/каналы с id — для TG_CHATS
    python main.py --bot-chats     показать, кто писал боту — чтобы узнать TARGET_CHAT_ID
    python main.py --test "текст"  проверить скоринг одной фразы
"""
from __future__ import annotations

import argparse
import asyncio
import calendar
import html
import logging
import random
import re
import signal
import sys
import time
from dataclasses import dataclass

import aiohttp
import feedparser

import config
from scorer import ScoreResult, make_draft, make_snippet, score_text, strip_html
from storage import Storage

log = logging.getLogger("leads")


# ===========================================================================
# Модель
# ===========================================================================
@dataclass
class Item:
    source: str          # tg | reddit | hn — часть ключа дедупликации
    item_id: str
    text: str
    url: str = ""
    author: str = ""
    label: str = ""      # «Telegram / @chat», «Reddit / r/forhire», «Hacker News»
    created: float = 0.0


class HttpError(Exception):
    def __init__(self, status: int, retry_after: float | None = None, body: str = "") -> None:
        super().__init__(f"HTTP {status}")
        self.status, self.retry_after, self.body = status, retry_after, body


def _retry_after(headers) -> float | None:
    try:
        return float(headers.get("Retry-After")) if headers.get("Retry-After") else None
    except (TypeError, ValueError):
        return None


async def fetch(session: aiohttp.ClientSession, url: str, *, params=None, headers=None, as_json=False):
    async with session.get(url, params=params, headers=headers) as r:
        if r.status != 200:
            raise HttpError(r.status, _retry_after(r.headers), (await r.text(errors="replace"))[:200])
        return await r.json(content_type=None) if as_json else await r.read()


def esc(s: str) -> str:
    return html.escape(s or "", quote=False)


# ===========================================================================
# Алерты в Telegram (Bot API)
# ===========================================================================
def format_alert(item: Item, res: ScoreResult) -> str:
    icon = "🔥" if res.score >= 80 else "⚡" if res.score >= 65 else "👀"
    urgent = " ⏰" if res.urgent else ""
    lines = [
        f"{icon} <b>[{res.lang.upper()}] [score: {res.score}]</b>{urgent} • {esc(item.label)}",
        "",
        f"<b>Почему:</b> {esc(res.reason())}",
        "",
        f"<blockquote>{esc(make_snippet(item.text, res.first_hit))}</blockquote>",
    ]
    if item.url:
        lines.append(f'🔗 <a href="{html.escape(item.url, quote=True)}">{esc(item.url[:80])}</a>')
    if item.author:
        lines.append(f"👤 {esc(item.author)}")
    lines += ["", "✍️ <b>Черновик ответа</b> (нажмите, чтобы скопировать):", f"<code>{esc(make_draft(res))}</code>"]
    return "\n".join(lines)


def html_to_plain(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


class Notifier:
    """Очередь алертов: одно сообщение за ALERT_MIN_INTERVAL, ретраи на 429/5xx/сеть, без падений."""

    def __init__(self, session: aiohttp.ClientSession, storage: Storage, dry_run: bool) -> None:
        self.session, self.storage, self.dry_run = session, storage, dry_run
        self.queue: asyncio.Queue[tuple[str, Item]] = asyncio.Queue(maxsize=500)
        self.sent = 0

    async def put(self, text: str, item: Item) -> None:
        try:
            self.queue.put_nowait((text, item))
        except asyncio.QueueFull:
            log.error("Очередь алертов переполнена — лид пропущен: %s", item.url or item.item_id)
            self.storage.set_status(item.source, item.item_id, "failed")

    async def run(self) -> None:
        while True:
            text, item = await self.queue.get()
            try:
                ok = await self._deliver(text)
                self.storage.set_status(item.source, item.item_id, "sent" if ok else "failed")
                self.sent += ok
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Не удалось отправить алерт")
                self.storage.set_status(item.source, item.item_id, "failed")
            finally:
                self.queue.task_done()
            await asyncio.sleep(config.ALERT_MIN_INTERVAL)

    async def _deliver(self, text: str) -> bool:
        if self.dry_run:
            print("\n" + "─" * 72 + "\n" + html_to_plain(text) + "\n" + "─" * 72, flush=True)
            return True
        return await self.send(text)

    async def send(self, text: str, *, attempts: int = 6) -> bool:
        url = f"{config.BOT_API_BASE}/bot{config.BOT_TOKEN}/sendMessage"
        payload = {"chat_id": config.TARGET_CHAT_ID, "text": text[:4096], "parse_mode": "HTML",
                   "disable_web_page_preview": True}
        delay = 2.0
        for attempt in range(1, attempts + 1):
            try:
                async with self.session.post(url, json=payload) as r:
                    data = await r.json(content_type=None)
                if data.get("ok"):
                    return True
                code, desc = data.get("error_code", r.status), str(data.get("description", ""))
                if code == 429:
                    wait = float((data.get("parameters") or {}).get("retry_after", 5)) + 1
                    log.warning("Bot API: лимит, жду %.0f с", wait)
                    await asyncio.sleep(wait)
                    continue
                if code == 400 and "parse" in desc.lower() and payload.get("parse_mode"):
                    log.warning("Bot API не разобрал HTML (%s) — отправляю простым текстом", desc)
                    payload = {**payload, "text": html_to_plain(text)[:4096]}
                    payload.pop("parse_mode")
                    continue
                if code in (400, 401, 403, 404):
                    log.error("Bot API отказал (%s): %s — проверьте BOT_TOKEN/TARGET_CHAT_ID и что вы написали боту /start",
                              code, desc)
                    return False
                log.warning("Bot API %s: %s (попытка %d/%d)", code, desc, attempt, attempts)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
                log.warning("Bot API недоступен: %s (попытка %d/%d)", exc.__class__.__name__, attempt, attempts)
            await asyncio.sleep(delay + random.random())
            delay = min(delay * 2, 60)
        return False


# ===========================================================================
# Ядро: проверка → скоринг → дедуп → алерт
# ===========================================================================
class App:
    def __init__(self, session: aiohttp.ClientSession, storage: Storage, notifier: Notifier) -> None:
        self.session, self.storage, self.notifier = session, storage, notifier
        self.counters = {"seen": 0, "leads": 0, "rejected": 0, "dup": 0, "old": 0}
        self.tg_client = None

    async def handle(self, item: Item) -> None:
        try:
            if not item.item_id or not (item.text or "").strip():
                return
            if self.storage.seen(item.source, item.item_id):
                return
            self.counters["seen"] += 1
            if item.created and time.time() - item.created > config.MAX_AGE_HOURS * 3600:
                self.storage.mark(item.source, item.item_id, "old", url=item.url)
                self.counters["old"] += 1
                return
            res = score_text(item.text)
            if res.accepted and self.storage.seen_fingerprint(res.fingerprint, config.DEDUP_DAYS):
                status = "dup"
            elif res.accepted:
                status = "queued"
            else:
                status = "rejected"
            self.storage.mark(item.source, item.item_id, status, fingerprint=res.fingerprint,
                              score=res.score, lang=res.lang, url=item.url)
            self.counters["leads" if status == "queued" else status] += 1
            if status == "queued":
                log.info("ЛИД [%s] %d • %s • %s", res.lang.upper(), res.score, item.label, res.reason())
                await self.notifier.put(format_alert(item, res), item)
            else:
                log.debug("skip (%s) %s: %s", status, item.label, res.reason())
        except Exception:  # noqa: BLE001 — один кривой пост не должен ронять мониторинг
            log.exception("Ошибка обработки %s/%s", item.source, item.item_id)


# ===========================================================================
# Источник 1: Telegram (Telethon, события в реальном времени)
# ===========================================================================
def _tg_link(chat_id: int, username: str | None, msg_id: int) -> str:
    if username:
        return f"https://t.me/{username}/{msg_id}"
    sid = str(chat_id)
    return f"https://t.me/c/{sid[4:]}/{msg_id}" if sid.startswith("-100") else ""


TG_STEP_TIMEOUT = 90   # жёсткий потолок на connect/авторизацию/поиск чата: при «чёрной дыре» в сети Telethon может висеть дольше своего timeout


def make_tg_client():
    from telethon import TelegramClient
    return TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH,
                          flood_sleep_threshold=60, auto_reconnect=True, retry_delay=5, connection_retries=10)


async def _resolve_chats(client) -> dict[int, tuple[str, str | None]]:
    from telethon import errors, utils
    chats: dict[int, tuple[str, str | None]] = {}
    for ref in config.TG_CHATS:
        for attempt in (1, 2):
            try:
                ent = await asyncio.wait_for(client.get_entity(ref), TG_STEP_TIMEOUT)
                uname = getattr(ent, "username", None)
                label = f"@{uname}" if uname else utils.get_display_name(ent) or str(ref)
                chats[utils.get_peer_id(ent)] = (label, uname)
                break
            except errors.FloodWaitError as exc:
                log.warning("FloodWait %d с при поиске чата %s", exc.seconds, ref)
                await asyncio.sleep(exc.seconds + 1)
            except (ValueError, TypeError, errors.RPCError) as exc:
                log.warning("Чат %s пропущен: %s (аккаунт состоит в нём? верная ссылка/id?)", ref, exc)
                break
    return chats


async def run_telegram(app: App) -> None:
    if not config.TG_CHATS:
        log.info("Telegram: TG_CHATS пуст — пропускаю")
        return
    if not (config.API_ID and config.API_HASH):
        log.warning("Telegram: нет TG_API_ID/TG_API_HASH — пропускаю (см. README)")
        return
    from telethon import errors, events, utils

    client = make_tg_client()
    app.tg_client = client
    handler_added = False
    backoff = 5
    while True:
        try:
            if not client.is_connected():
                await asyncio.wait_for(client.connect(), TG_STEP_TIMEOUT)
            if not await asyncio.wait_for(client.is_user_authorized(), TG_STEP_TIMEOUT):
                log.error("Telegram: сессия не авторизована. Один раз запустите: python main.py --login")
                return
            chats = await _resolve_chats(client)
            if not chats:
                log.error("Telegram: ни один чат из TG_CHATS не найден — пропускаю")
                return
            if not handler_added:
                @client.on(events.NewMessage(chats=list(chats)))
                async def on_message(event):  # noqa: ANN001
                    try:
                        msg = event.message
                        text = (msg.message or "").strip()
                        if not text:
                            return
                        label, uname = chats.get(event.chat_id, (str(event.chat_id), None))
                        author = ""
                        try:
                            sender = await event.get_sender()
                            if sender is not None:
                                su = getattr(sender, "username", None)
                                author = f"@{su}" if su else f"{utils.get_display_name(sender)} (id {sender.id})"
                        except Exception:  # noqa: BLE001
                            pass
                        await app.handle(Item(
                            source="tg", item_id=f"{event.chat_id}:{msg.id}", text=text,
                            url=_tg_link(event.chat_id, uname, msg.id), author=author,
                            label=f"Telegram / {label}", created=msg.date.timestamp() if msg.date else time.time(),
                        ))
                    except Exception:  # noqa: BLE001
                        log.exception("Telegram: ошибка в обработчике")
                handler_added = True
            log.info("Telegram: слушаю %d чат(ов): %s", len(chats), ", ".join(l for l, _ in chats.values()))
            backoff = 5
            await client.run_until_disconnected()
            log.warning("Telegram: соединение закрыто, переподключаюсь")
        except asyncio.CancelledError:
            raise
        except errors.FloodWaitError as exc:
            log.warning("Telegram FloodWait: жду %d с", exc.seconds)
            await asyncio.sleep(exc.seconds + 1)
        except (ConnectionError, OSError, asyncio.TimeoutError, errors.RPCError) as exc:
            log.warning("Telegram: %s — повтор через %d с", exc.__class__.__name__ if not str(exc) else exc, backoff)
            try:                                    # сбросить полуживое соединение перед новой попыткой
                await asyncio.wait_for(client.disconnect(), 15)
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)


# ===========================================================================
# Источник 2: Reddit (RSS по всем сабреддитам одним запросом)
# ===========================================================================
def _entry_time(entry) -> float:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return float(calendar.timegm(t))
    return time.time()


def parse_reddit(data: bytes) -> list[Item]:
    feed = feedparser.parse(data)
    items = []
    for e in feed.entries:
        title = e.get("title", "")
        content = (e.get("content") or [{}])[0].get("value") or e.get("summary", "")
        body = strip_html(content)
        body = re.split(r"\n?\s*submitted by\s", body, maxsplit=1)[0].strip()   # хвост RSS «submitted by /u/…»
        sub = ""
        if e.get("tags"):
            sub = e["tags"][0].get("term", "")
        if not sub:
            m = re.search(r"/r/([^/]+)/", e.get("link", ""))
            sub = m.group(1) if m else "reddit"
        author = (e.get("author") or "").strip()
        author = author.replace("/u/", "u/") if author else ""
        items.append(Item(
            source="reddit", item_id=e.get("id") or e.get("link", ""), text=f"{title}\n{body}".strip(),
            url=e.get("link", ""), author=author, label=f"Reddit / r/{sub}", created=_entry_time(e),
        ))
    return items


async def poll_reddit(app: App) -> None:
    if not config.REDDIT_SUBREDDITS:
        log.info("Reddit: список сабреддитов пуст — пропускаю")
        return
    subs = "+".join(config.REDDIT_SUBREDDITS)
    headers = {"User-Agent": config.REDDIT_USER_AGENT}
    log.info("Reddit: опрос r/%s каждые %d с", subs, config.REDDIT_POLL_SECONDS)
    pause = config.REDDIT_POLL_SECONDS
    while True:
        pause = config.REDDIT_POLL_SECONDS
        for base in config.REDDIT_BASE_URLS:
            try:
                data = await fetch(app.session, f"{base}/r/{subs}/new/.rss", params={"limit": "100"}, headers=headers)
                items = parse_reddit(data)
                for it in sorted(items, key=lambda i: i.created):   # от старых к новым: оригинал раньше кросс-поста
                    await app.handle(it)
                log.debug("Reddit: %d записей", len(items))
                break
            except HttpError as exc:
                if exc.status == 429:
                    pause = max(pause, exc.retry_after or 120)
                log.warning("Reddit %s: HTTP %d%s", base, exc.status, " (пробую запасной адрес)" if base != config.REDDIT_BASE_URLS[-1] else "")
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                log.warning("Reddit %s: сеть: %s", base, exc.__class__.__name__)
        await asyncio.sleep(pause + random.uniform(0, 15))


# ===========================================================================
# Источник 3: Hacker News (Algolia, свежие посты и комментарии)
# ===========================================================================
def parse_hn(hits: list[dict]) -> list[Item]:
    items = []
    for h in hits:
        oid = str(h.get("objectID") or "")
        if not oid:
            continue
        title = h.get("title") or ""
        body = strip_html(h.get("story_text") or h.get("comment_text") or "")
        thread = h.get("story_title") or ""
        text = "\n".join(p for p in (title, body) if p)
        if thread and not title:
            text = f"{text}\n[thread: {thread}]"
        items.append(Item(
            source="hn", item_id=oid, text=text, url=f"https://news.ycombinator.com/item?id={oid}",
            author=h.get("author") or "", label="Hacker News" + (" / comment" if not title else ""),
            created=float(h.get("created_at_i") or time.time()),
        ))
    return items


async def poll_hn(app: App) -> None:
    if not config.HN_ENABLED or not config.HN_QUERIES:
        log.info("Hacker News: выключен")
        return
    since = {q: int(time.time() - config.MAX_AGE_HOURS * 3600) for q in config.HN_QUERIES}
    log.info("Hacker News: %d запрос(ов) каждые %d с", len(config.HN_QUERIES), config.HN_POLL_SECONDS)
    while True:
        for q in config.HN_QUERIES:
            try:
                data = await fetch(app.session, config.HN_API_URL, as_json=True, params={
                    "query": q, "tags": "(story,comment)", "numericFilters": f"created_at_i>{since[q]}",
                    "hitsPerPage": "50"})
                hits = (data.get("hits") or []) if isinstance(data, dict) else []
                for h in hits:
                    since[q] = max(since[q], int(h.get("created_at_i") or 0))
                for it in sorted(parse_hn(hits), key=lambda i: i.created):
                    await app.handle(it)
            except HttpError as exc:
                log.warning("HN «%s»: HTTP %d", q, exc.status)
                if exc.status == 429:
                    await asyncio.sleep(exc.retry_after or 60)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
                log.warning("HN «%s»: %s", q, exc.__class__.__name__)
            await asyncio.sleep(1.5)            # бережно к API между запросами
        await asyncio.sleep(config.HN_POLL_SECONDS + random.uniform(0, 20))


# ===========================================================================
# Запуск
# ===========================================================================
async def supervise(name: str, coro_factory) -> None:
    """Перезапускает упавшую задачу с нарастающей паузой; нормальное завершение — не перезапускает."""
    delay = 5
    while True:
        try:
            await coro_factory()
            return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("%s упал — перезапуск через %d с", name, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 600)


async def report(app: App) -> None:
    while True:
        await asyncio.sleep(600)
        log.info("Статистика: %s; отправлено алертов: %d; за 24 ч в базе: %s",
                 app.counters, app.notifier.sent, app.storage.stats())


async def run(dry_run: bool) -> None:
    if not dry_run and not (config.BOT_TOKEN and config.TARGET_CHAT_ID):
        log.warning("BOT_TOKEN/TARGET_CHAT_ID не заданы — работаю в режиме --dry-run (алерты в консоль)")
        dry_run = True
    storage = Storage(config.DB_PATH)
    removed = storage.cleanup(60)
    if removed:
        log.info("База: удалено %d старых записей", removed)
    timeout = aiohttp.ClientTimeout(total=config.HTTP_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        notifier = Notifier(session, storage, dry_run)
        app = App(session, storage, notifier)
        tasks = [
            asyncio.create_task(supervise("notifier", notifier.run), name="notifier"),
            asyncio.create_task(supervise("telegram", lambda: run_telegram(app)), name="telegram"),
            asyncio.create_task(supervise("reddit", lambda: poll_reddit(app)), name="reddit"),
            asyncio.create_task(supervise("hn", lambda: poll_hn(app)), name="hn"),
            asyncio.create_task(report(app), name="report"),
        ]
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except (NotImplementedError, RuntimeError):   # Windows: остаётся KeyboardInterrupt
                pass
        log.info("Запущено. Порог: %d, режим: %s. Остановка — Ctrl+C", config.MIN_SCORE,
                 "dry-run (консоль)" if dry_run else f"бот → {config.TARGET_CHAT_ID}")
        try:
            await stop.wait()
        finally:
            log.info("Останавливаюсь…")
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if app.tg_client is not None:
                try:
                    await app.tg_client.disconnect()
                except Exception:  # noqa: BLE001
                    pass
            storage.close()


# ===========================================================================
# Вспомогательные команды
# ===========================================================================
async def cmd_login() -> None:
    if not (config.API_ID and config.API_HASH):
        sys.exit("Сначала заполните TG_API_ID и TG_API_HASH (см. README).")
    client = make_tg_client()
    await client.start()                         # спросит телефон, код и пароль 2FA (если есть)
    me = await client.get_me()
    print(f"Готово: вошли как {me.first_name} (@{me.username}). Сессия сохранена в {config.SESSION_NAME}.session")
    await client.disconnect()


async def cmd_list_chats() -> None:
    from telethon import utils
    client = make_tg_client()
    await client.connect()
    if not await client.is_user_authorized():
        sys.exit("Сначала: python main.py --login")
    print(f"{'id':>16}  {'username':<28} название")
    async for d in client.iter_dialogs():
        if d.is_group or d.is_channel:
            uname = getattr(d.entity, "username", None) or ""
            print(f"{utils.get_peer_id(d.entity):>16}  {('@' + uname) if uname else '—':<28} {d.name}")
    await client.disconnect()


async def cmd_bot_chats() -> None:
    if not config.BOT_TOKEN:
        sys.exit("Сначала заполните BOT_TOKEN.")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=config.HTTP_TIMEOUT)) as s:
        async with s.get(f"{config.BOT_API_BASE}/bot{config.BOT_TOKEN}/getUpdates") as r:
            data = await r.json(content_type=None)
    if not data.get("ok"):
        sys.exit(f"Bot API: {data.get('description')}")
    found = {}
    for u in data.get("result", []):
        msg = u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}
        chat = msg.get("chat") or {}
        if chat.get("id"):
            found[chat["id"]] = chat.get("title") or chat.get("username") or chat.get("first_name") or ""
    if not found:
        print("Пусто. Напишите боту /start (или добавьте его в группу и напишите там), затем повторите.")
    for cid, name in found.items():
        print(f"TARGET_CHAT_ID={cid}    # {name}")


def cmd_test(text: str) -> None:
    res = score_text(text)
    print(f"язык: {res.lang}  score: {res.score}  принят: {res.accepted}  тип: {res.kind}")
    print(f"почему: {res.reason()}")
    if res.accepted:
        print("\nалерт:\n" + html_to_plain(format_alert(Item("test", "1", text, label="тест"), res)))


def cmd_test_interactive() -> None:
    print("Вставьте текст объявления одной строкой и нажмите Enter. Пустая строка — выход.")
    while True:
        try:
            line = input("\n> ").strip()
        except EOFError:
            break
        if not line:
            break
        cmd_test(line)


def main() -> None:
    ap = argparse.ArgumentParser(description="fioritura lead parser")
    ap.add_argument("--dry-run", action="store_true", help="алерты в консоль вместо бота")
    ap.add_argument("--login", action="store_true", help="интерактивный вход в Telegram")
    ap.add_argument("--list-chats", action="store_true", help="показать id ваших чатов/каналов")
    ap.add_argument("--bot-chats", action="store_true", help="показать chat_id тех, кто писал боту")
    ap.add_argument("--test", nargs="?", const="", metavar="TEXT",
                    help="проверить скоринг текста (без текста — спросит в консоли)")
    ap.add_argument("-v", "--verbose", action="store_true", help="подробный лог (видно отклонённые)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    for noisy in ("telethon", "aiohttp", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    try:
        if args.test is not None:
            cmd_test(args.test) if args.test else cmd_test_interactive()
        elif args.login:
            asyncio.run(cmd_login())
        elif args.list_chats:
            asyncio.run(cmd_list_chats())
        elif args.bot_chats:
            asyncio.run(cmd_bot_chats())
        else:
            asyncio.run(run(args.dry_run))
    except KeyboardInterrupt:
        log.info("Остановлено")


if __name__ == "__main__":
    main()
