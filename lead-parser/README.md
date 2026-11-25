# fioritura lead parser

Асинхронный монитор заказов на сайты, лендинги, прототипы и MVP на **EN / RU / UK / PL**.
Слушает Telegram-чаты в реальном времени, опрашивает Reddit (RSS) и Hacker News, отсекает
самопиар исполнителей и вакансии в штат и присылает в вашего бота готовые алерты:

```
🔥 [PL] [score: 86] ⏰ • Telegram / @freelance_pl
Почему: заказ: «szukam wykonawcy», «potrzebuję landing» · сроки/срочность (pilne) · бюджет (budżet, zł)
❝ Szukam wykonawcy: potrzebuję landing page pod premierę aplikacji, budżet 3000 zł, pilne ❞
🔗 https://t.me/freelance_pl/4821
👤 @anna_k
✍️ Черновик ответа:  Dzień dobry! Widzę, że potrzebujesz landing page’a. Jestem fioritura — …
```

Черновик приходит в блоке `<code>` — нажмите на него в Telegram, и он скопируется. **Отвечаете вы сами, вручную**:
парсер ничего не пишет людям от вашего имени.

## Файлы

| файл | что внутри |
|---|---|
| `config.py` | ключи, чаты, сабреддиты, пороги, все словари сигналов и черновики ответов |
| `scorer.py` | определение языка, скоринг, причина попадания, отпечаток текста для дублей |
| `storage.py` | SQLite `leads.db`: что уже обработано, чтобы лид не пришёл дважды |
| `main.py` | asyncio-цикл: Telegram + Reddit + HN → скоринг → алерты через Bot API |

## Запуск по шагам

> **Windows 11:** проще всего — дважды щёлкнуть `START.bat` в корне папки и идти по меню, инструкция простыми словами — `README-WINDOWS.txt`. Ниже — то же самое вручную, для любой ОС.

Нужен Python 3.10+.

### 1. Установка

```bash
cd lead-parser
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -U pip setuptools wheel
pip install -r requirements.txt
cp .env.example .env                 # Windows: copy .env.example .env
```

### 2. `api_id` и `api_hash` (чтение Telegram-чатов)

1. Откройте <https://my.telegram.org>, войдите по номеру телефона.
2. **API development tools** → заполните название приложения (любое, например `leads`) → **Create application**.
3. Скопируйте `App api_id` и `App api_hash` в `.env` (`TG_API_ID`, `TG_API_HASH`).

Это ключи **вашего аккаунта**: никому их не передавайте и не коммитьте `.env` и `*.session` (они уже в `.gitignore`).

### 3. Бот для алертов

1. В Telegram напишите [@BotFather](https://t.me/BotFather) → `/newbot` → имя и username бота.
2. Токен вида `123456789:AA…` положите в `.env` → `BOT_TOKEN`.
3. Напишите своему боту `/start` (без этого бот не сможет вам писать).
   Хотите алерты в группу — добавьте бота в группу и напишите там любое сообщение.
4. Узнайте id чата: `python main.py --bot-chats` → скопируйте строку `TARGET_CHAT_ID=…` в `.env`.

### 4. Первый вход в Telethon

```bash
python main.py --login
```

Введите номер телефона, код из Telegram и пароль двухфакторной защиты, если он есть.
Появится файл `fioritura_leads.session` — дальше вход не нужен.

### 5. Какие чаты слушать

Аккаунт должен **состоять** в чатах, которые вы мониторите. Посмотреть свои группы и каналы с id:

```bash
python main.py --list-chats
```

Впишите нужные в `TG_CHATS` в `config.py`: `@username`, ссылку `https://t.me/username` или числовой id
(для приватных чатов — только id).

### 6. Проверка и запуск

```bash
python main.py --test "Нужен лендинг для запуска курса, бюджет 40к, срочно"   # проверить скоринг фразы
python main.py --dry-run          # всё работает, но алерты печатаются в консоль
python main.py                    # боевой режим: алерты в бота
python main.py -v                 # плюс в логе видно, что и почему отклонено
```

При первом запуске посты старше `MAX_AGE_HOURS` (24 ч) не присылаются, чтобы не завалить вас старым.
Остановка — `Ctrl+C`.

## Запуск на VPS (24/7)

```bash
# на сервере (Ubuntu/Debian)
sudo apt install -y python3-venv git
git clone <ваш репозиторий> && cd <репозиторий>/lead-parser
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env && nano .env
python main.py --login             # один раз, интерактивно
```

Чтобы не входить на сервере, можно сделать `--login` у себя на ПК и скопировать файл `fioritura_leads.session` на VPS
(`scp fioritura_leads.session user@server:~/…/lead-parser/`).

systemd-сервис `/etc/systemd/system/fioritura-leads.service`:

```ini
[Unit]
Description=fioritura lead parser
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/home/USER/REPO/lead-parser
ExecStart=/home/USER/REPO/lead-parser/.venv/bin/python main.py
Restart=always
RestartSec=10
User=USER

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now fioritura-leads
journalctl -u fioritura-leads -f        # логи
```

## Как устроен отбор

1. **Мусор** — слишком короткий текст, почти нет букв, больше `MAX_LINKS` ссылок → отказ.
2. **`HARD_REJECT`** — найм в штат/офис (опыт от N лет, full-time, резюме, umowa o pracę…) и теги
   `[For Hire]` / `[Offer]` → отказ сразу.
3. **`BUY_SIGNALS`** — без хотя бы одного признака заказа текст не рассматривается.
   Первое совпадение даёт 50, каждое следующее +8.
4. **`BOOST_SIGNALS`** — сроки, бюджет, запуск, прототип/MVP, редизайн, промо: + вес категории (максимум +35).
5. **`SELLER_PENALTY`** — «сделаю сайт», «wykonam», «i can build», «моё портфолио»…: −45 за каждое.
6. Итог 0–100; присылается всё, что ≥ `MIN_SCORE` (50).
7. **Дубли** — одно сообщение не обрабатывается дважды, а одинаковый текст из разных чатов (кросс-постинг)
   не приходит повторно `DEDUP_DAYS` дней.

Язык определяется по алфавиту, характерным буквам (і/ї/є/ґ — UK, ы/э/ъ/ё — RU, ą/ę/ł/ś/ż… — PL)
и частым словам. Черновик ответа берётся на языке лида.

### Настройка словарей

Фраза совпадает **с начала слова**, конец может быть любым: `стажировк` ловит «стажировка/стажировку».
Регистр, «ё/е» и польские диакритики не важны. Пробел и дефис взаимозаменяемы (`full-time` = `full time`).
Префикс `re:` — регулярное выражение. После правок проверяйте: `python main.py --test "…"`.

## Ограничения и устойчивость

* Сетевые ошибки, таймауты, `FloodWaitError`, 429 от Reddit/HN/Bot API обрабатываются паузой и повтором;
  упавший источник перезапускается сам, остальные продолжают работать.
* Reddit часто отвечает 403/429 запросам с IP дата-центров (VPS). Парсер пробует запасной адрес `old.reddit.com`,
  но если блок держится — Reddit с этого сервера работать не будет (Telegram и HN продолжат).
  Обязательно укажите в `REDDIT_USER_AGENT` свой ник на Reddit.
* Если Bot API не может разобрать HTML, алерт уйдёт простым текстом.
* Telethon работает от вашего личного аккаунта и только **читает** чаты, в которых вы и так состоите.
  Не используйте его для массовых рассылок — это нарушает правила Telegram и ведёт к бану аккаунта.
