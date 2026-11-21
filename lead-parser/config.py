"""
fioritura lead parser — единый конфиг.

Секреты лучше держать в переменных окружения или в файле .env рядом с этим файлом
(см. .env.example) — тогда config.py можно спокойно коммитить.
Всё остальное (чаты, сабреддиты, словари, пороги) правится прямо здесь.

Как работают словари сигналов
-----------------------------
* Сравнение без учёта регистра; «ё» = «е»; польские буквы сворачиваются (ą→a, ł→l, ż→z …),
  поэтому «potrzebuję» и «potrzebuje» — одно и то же.
* Фраза совпадает с НАЧАЛА слова, конец может быть любым: «лендинг» найдёт «лендинга»,
  «стажировк» найдёт «стажировка/стажировку». Так удобно ловить падежи и формы.
* Пробел и дефис внутри фразы взаимозаменяемы: «full-time» найдёт и «full time», и «fulltime».
* Префикс "re:" — регулярное выражение (применяется к уже нормализованному тексту:
  нижний регистр, ё→е, польские буквы без диакритики).
"""
from __future__ import annotations

import os
from pathlib import Path

try:  # .env необязателен
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:
    pass


def _int(name: str, default: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Telegram: аккаунт для чтения чатов (Telethon) и бот для алертов
# ---------------------------------------------------------------------------
API_ID: int = _int("TG_API_ID")                 # https://my.telegram.org → API development tools
API_HASH: str = os.getenv("TG_API_HASH", "")
SESSION_NAME: str = os.getenv("TG_SESSION", "fioritura_leads")   # файл fioritura_leads.session

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")      # от @BotFather
TARGET_CHAT_ID: int = _int("TARGET_CHAT_ID")     # куда слать алерты (ваш id или id группы)
BOT_API_BASE: str = os.getenv("BOT_API_BASE", "https://api.telegram.org")

# Чаты/каналы для мониторинга в реальном времени: @username, ссылка t.me/username или числовой id.
# Аккаунт должен состоять в этих чатах. Числовые id приватных чатов покажет: python main.py --list-chats
TG_CHATS: list[str | int] = [
    # "@your_freelance_chat",
    # "https://t.me/another_public_chat",
    # -1001234567890,
]

# ---------------------------------------------------------------------------
# Reddit (RSS, без API-ключей) и Hacker News (Algolia API)
# ---------------------------------------------------------------------------
REDDIT_SUBREDDITS: list[str] = ["forhire", "DesignJobs", "slavelabour", "startups", "SideProject", "Entrepreneur"]
REDDIT_POLL_SECONDS: int = 180
# Reddit режет запросы без внятного User-Agent. Впишите свой ник на Reddit.
REDDIT_USER_AGENT: str = os.getenv("REDDIT_USER_AGENT", "fioritura-leads/1.0 (lead monitor; contact via u/your_reddit_name)")
REDDIT_BASE_URLS: list[str] = ["https://www.reddit.com", "https://old.reddit.com"]  # второй — запасной

HN_ENABLED: bool = True
HN_POLL_SECONDS: int = 300
HN_API_URL: str = "https://hn.algolia.com/api/v1/search_by_date"
HN_QUERIES: list[str] = [
    "need a website", "looking for developer", "landing page", "mvp",
    "build my website", "seeking freelancer", "need a developer", "prototype",
]

# ---------------------------------------------------------------------------
# Отбор лидов
# ---------------------------------------------------------------------------
MIN_SCORE: int = 50          # ниже — не присылать
MAX_AGE_HOURS: int = 24      # посты старше не берём (важно при первом запуске)
DEDUP_DAYS: int = 14         # одинаковый текст (кросс-постинг) не присылаем повторно столько дней
SNIPPET_CHARS: int = 650     # длина фрагмента в алерте
ALERT_MIN_INTERVAL: float = 3.0   # пауза между алертами, сек (лимиты Bot API для групп ~20 сообщ./мин)
HTTP_TIMEOUT: float = 25.0
DB_PATH: str = os.getenv("LEADS_DB", str(Path(__file__).with_name("leads.db")))

# Веса скоринга
SCORE_BUY_FIRST: int = 50        # первое совпадение «это заказ»
SCORE_BUY_EXTRA: int = 8         # каждое следующее (до 3)
SCORE_BOOST_CAP: int = 35        # максимум от усилителей
SCORE_SELLER_PENALTY: int = 45   # за каждый признак «это исполнитель предлагает услуги»
MIN_LETTERS: int = 20            # короче — мусор
MAX_LINKS: int = 6               # больше ссылок — спам

# ---------------------------------------------------------------------------
# Сигналы заказа (без хотя бы одного совпадения лид не рассматривается)
# ---------------------------------------------------------------------------
BUY_SIGNALS: dict[str, list[str]] = {
    "ru": [
        "нужен сайт", "нужен лендинг", "нужна посадочн", "нужна страниц", "нужен прототип", "нужен mvp", "нужно mvp",
        "нужно сделать сайт", "нужно сделать лендинг", "нужно собрать", "нужен разработчик", "нужен веб-разработчик",
        "нужен программист", "нужен верстальщик", "ищу разработчика", "ищу веб-разработчика", "ищу программиста",
        "ищу исполнителя", "ищем исполнителя", "ищем разработчика", "ищу фрилансера", "ищу верстальщика",
        "ищу вайбкодера", "ищу того, кто", "кто может сделать", "кто сделает", "кто возьмется", "кто возьмет",
        "сделать сайт", "сделать лендинг", "создать сайт", "разработать сайт", "заказать сайт", "закажу сайт",
        "закажу лендинг", "требуется разработчик", "требуется сделать", "нужна помощь с сайтом",
        "собрать прототип", "собрать лендинг",
    ],
    "uk": [
        "потрібен сайт", "потрібен лендинг", "потрібна сторінк", "потрібен прототип", "потрібен mvp",
        "потрібно зробити сайт", "потрібно зробити лендинг", "потрібен розробник", "потрібен програміст",
        "шукаю розробника", "шукаю програміста", "шукаю виконавця", "шукаємо виконавця", "шукаємо розробника",
        "шукаю фрилансера", "хто може зробити", "хто зробить", "хто візьметься", "зробити сайт", "зробити лендинг",
        "створити сайт", "розробити сайт", "замовити сайт", "замовлю сайт", "замовлю лендинг",
        "треба сайт", "треба лендинг", "треба зробити",
    ],
    "pl": [
        "szukam wykonawcy", "szukam programisty", "szukam developera", "szukam kogoś", "szukam osoby",
        "szukamy wykonawcy", "szukamy programisty", "szukam freelancera", "zlecę", "zlecimy", "zlecenie na stron",
        "potrzebuję stron", "potrzebujemy stron", "potrzebuję landing", "potrzebuję prototyp", "potrzebuję mvp",
        "kto zrobi", "kto mógłby zrobić", "ktoś zrobi", "zrobienie strony", "stworzenie strony", "wykonanie strony",
        "budowa strony",
    ],
    "en": [
        "need a website", "need a landing page", "need a site", "need a web developer", "need a developer",
        "need someone to build", "need someone to make", "need someone to create", "need help building",
        "looking for a developer", "looking for a web developer", "looking for someone to build",
        "looking for someone to create", "looking for a freelancer", "looking to hire", "who can build",
        "can anyone build", "hire a developer", "hiring a developer", "want to hire", "[hiring]", "[task]",
        "build me a", "build my website", "build a landing page", "build an mvp", "need an mvp", "mvp developer",
        "seeking a developer", "seeking developer", "seeking freelancer", "web developer needed", "developer needed",
    ],
}

# ---------------------------------------------------------------------------
# Усилители: категория → вес и фразы по языкам
# ---------------------------------------------------------------------------
BOOST_WEIGHTS: dict[str, int] = {"deadline": 10, "budget": 12, "launch": 8, "prototype": 8, "redesign": 8, "promo": 6}
BOOST_LABELS: dict[str, str] = {
    "deadline": "сроки/срочность", "budget": "бюджет", "launch": "запуск",
    "prototype": "прототип/MVP", "redesign": "редизайн", "promo": "лендинг/промо",
}
BOOST_SIGNALS: dict[str, dict[str, list[str]]] = {
    "deadline": {
        "ru": ["срочно", "до конца недели", "к понедельнику", "за неделю", "в течение недели", "сроки", "дедлайн", "горит", "как можно скорее"],
        "uk": ["терміново", "до кінця тижня", "за тиждень", "терміни", "дедлайн", "якнайшвидше"],
        "pl": ["pilne", "pilnie", "na wczoraj", "do końca tygodnia", "w ciągu tygodnia", "termin", "jak najszybciej"],
        "en": ["asap", "urgent", "deadline", "by next week", "this week", "within a week", "quick turnaround", "timeline"],
    },
    "budget": {
        "ru": ["бюджет", "оплата", "оплачу", "заплачу", "стоимость", "руб", "₽", "$", "usd", "eur", "€", "грн"],
        "uk": ["бюджет", "оплата", "оплачу", "заплачу", "вартість", "грн", "₴"],
        "pl": ["budżet", "stawka", "zapłacę", "płatne", "wynagrodzenie", "zł", "pln"],
        "en": ["budget", "paid", "pay ", "will pay", "compensation", "usd"],
    },
    "launch": {
        "ru": ["запуск", "запустить", "старт продаж", "предзаказ", "релиз"],
        "uk": ["запуск", "запустити", "передзамовлення", "реліз"],
        "pl": ["uruchom", "premier", "przedsprzedaż", "wdrożeni"],
        "en": ["launch", "go live", "pre-order", "preorder", "waitlist"],
    },
    "prototype": {
        "ru": ["прототип", "mvp", "мвп", "no-code", "нокод", "figma", "фигм"],
        "uk": ["прототип", "mvp", "no-code", "figma"],
        "pl": ["prototyp", "mvp", "no-code", "figma"],
        "en": ["prototype", "mvp", "no-code", "nocode", "figma", "proof of concept"],
    },
    "redesign": {
        "ru": ["редизайн", "переделать сайт", "обновить сайт", "переделка"],
        "uk": ["редизайн", "переробити сайт", "оновити сайт"],
        "pl": ["redesign", "przebudowa strony", "odświeżenie strony", "nowa wersja strony"],
        "en": ["redesign", "revamp", "rebuild", "refresh my website"],
    },
    "promo": {
        "ru": ["промо", "лендинг", "посадочн", "одностраничн", "landing"],
        "uk": ["промо", "лендинг", "односторінков"],
        "pl": ["landing", "strona promocyjna", "one page", "onepage", "wizytówk"],
        "en": ["landing page", "promo page", "one-page", "single page", "portfolio site"],
    },
}

# ---------------------------------------------------------------------------
# Жёсткий отказ: найм в штат/офис и явные теги «исполнитель ищет работу»
# (совпадение → лид отбрасывается сразу, независимо от остального)
# ---------------------------------------------------------------------------
HARD_REJECT: dict[str, list[str]] = {
    "ru": [
        "в офис", "работа в офисе", "re:опыт (работы )?от \\d", "re:\\d\\+? (лет|года) опыта", "полный рабочий день",
        "полная занятость", "фуллтайм", "стажировк", "резюме", "оформление по тк", "трудоустройств", "соцпакет",
        "зарплата от", "зп от", "мидл", "сеньор",
    ],
    "uk": [
        "в офіс", "робота в офісі", "re:досвід (роботи )?від \\d", "повна зайнятість", "стажуванн", "резюме",
        "офіційне працевлаштування", "зарплата від", "соцпакет",
    ],
    "pl": [
        "praca stacjonarna", "umowa o pracę", "pełny etat", "b2b na wyłączność", "re:doswiadczenie (min\\.? ?)?\\d",
        "re:min\\.? ?\\d+ lat", "staż", "praktyki", "wyślij cv", "prześlij cv", "aplikuj",
    ],
    "en": [
        "full-time", "full time position", "on-site", "onsite", "in-office", "office-based", "internship",
        "send your cv", "send your resume", "salary", "benefits package", "401k",
        "re:\\d+\\+? ?(years|yrs)( of)? (professional )?experience",
        "re:\\b(senior|middle|mid-level|lead)[\\s-]+(front|back|full|web|php|js|react|python|developer|engineer)",
        "[for hire]", "[offer]", "who wants to be hired", "who is hiring",
    ],
}

# ---------------------------------------------------------------------------
# Признаки «это исполнитель рекламирует себя» — сильный штраф за каждое совпадение
# ---------------------------------------------------------------------------
SELLER_PENALTY: dict[str, list[str]] = {
    "ru": [
        "сделаю сайт", "сделаю лендинг", "сделаю вам", "создам сайт", "создам лендинг", "разработаю", "выполню",
        "возьмусь за", "беру заказы", "принимаю заказы", "ищу заказ", "ищу заказчиков", "ищу клиентов",
        "мое портфолио", "мои работы", "портфолио в профиле", "опыт верстки", "предлагаю услуги", "наши услуги",
        "делаем сайты", "мы делаем", "под ключ", "могу сделать", "недорого",
    ],
    "uk": [
        "зроблю сайт", "зроблю лендинг", "створю сайт", "розроблю", "виконаю", "беру замовлення", "приймаю замовлення",
        "шукаю замовлення", "шукаю замовників", "моє портфоліо", "мої роботи", "пропоную послуги", "робимо сайти",
        "під ключ", "можу зробити", "недорого",
    ],
    "pl": [
        "wykonam", "oferuję", "oferujemy", "stworzę dla", "stworzę stron", "zrobię stronę", "zaprojektuję",
        "moje portfolio", "przyjmę zlecenie", "szukam zleceń", "szukam klientów", "tworzymy strony", "robimy strony",
        "mogę zrobić",
    ],
    "en": [
        "i will build", "i will create", "i'll build", "i can build", "i can create", "i can make",
        "i'm a web developer", "i am a web developer", "my portfolio", "check my portfolio", "hire me",
        "available for work", "open for work", "seeking work", "we build websites", "our agency", "dm me for",
        "looking for clients", "looking for work", "looking for projects", "looking for gigs", "[for hire]",
    ],
}

# ---------------------------------------------------------------------------
# Что именно нужно (для черновика ответа): проверяется по порядку, первое совпадение побеждает
# ---------------------------------------------------------------------------
KIND_SIGNALS: dict[str, list[str]] = {
    "mvp": ["mvp", "мвп"],
    "prototype": ["прототип", "prototyp", "prototype"],
    "landing": ["лендинг", "landing", "посадочн", "промо", "одностранич", "односторінк", "strona promocyjna", "one page", "one-page"],
    # всё остальное → "site"
}

# ---------------------------------------------------------------------------
# Бренд и черновики первого сообщения
# ---------------------------------------------------------------------------
BRAND_NAME: str = "fioritura"
PORTFOLIO_URL: str = os.getenv("PORTFOLIO_URL", "https://fioritura.example.com")

TOPICS: dict[str, dict[str, str]] = {
    "ru": {"site": "сайт", "landing": "лендинг", "prototype": "прототип", "mvp": "MVP"},
    "uk": {"site": "сайт", "landing": "лендинг", "prototype": "прототип", "mvp": "MVP"},
    "pl": {"site": "strony", "landing": "landing page’a", "prototype": "prototypu", "mvp": "MVP"},
    "en": {"site": "a website", "landing": "a landing page", "prototype": "a prototype", "mvp": "an MVP"},
}
DRAFTS: dict[str, str] = {
    "ru": ("Здравствуйте! Вижу, вам нужен {topic}. Я {brand} — делаю сайты и прототипы сам, напрямую, без студии; "
           "живую ссылку показываю с первых дней. Как работаю: {url}. Расскажете чуть подробнее о задаче и сроках?"),
    "uk": ("Вітаю! Бачу, вам потрібен {topic}. Я {brand} — роблю сайти й прототипи сам, напряму, без студії; "
           "живе посилання показую з перших днів. Як працюю: {url}. Розкажете трохи більше про задачу й терміни?"),
    "pl": ("Dzień dobry! Widzę, że potrzebujesz {topic}. Jestem {brand} — sam robię strony i prototypy, bezpośrednio, "
           "bez agencji; działający link pokazuję od pierwszych dni. Jak pracuję: {url}. Opowiesz trochę więcej o zadaniu i terminach?"),
    "en": ("Hi! Saw you're looking for {topic}. I'm {brand} — I build websites and prototypes solo, directly, no agency; "
           "you get a live link in the first days. How I work: {url}. Could you share a bit more about the task and timeline?"),
}
