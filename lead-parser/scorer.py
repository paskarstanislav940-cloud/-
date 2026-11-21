"""
Анализ текста: язык, скоринг, причина попадания, отпечаток для дедупликации.

Ничего не знает о сети и базе — только текст на входе, ScoreResult на выходе.
Проверить любую фразу без запуска мониторинга:  python main.py --test "нужен лендинг, бюджет 30к"
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser

import config

LANGS = ("en", "ru", "uk", "pl")

# ---------------------------------------------------------------------------
# Нормализация
# ---------------------------------------------------------------------------
# посимвольная замена (длина строки не меняется — позиции совпадений совпадают с исходным текстом)
_FOLD = str.maketrans({
    "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n", "ó": "o", "ś": "s", "ź": "z", "ż": "z",
    "ё": "е", "’": "'", "ʼ": "'", "`": "'", "‘": "'", " ": " ",
})


def prepare(text: str) -> str:
    """Исходный текст в каноническом виде (NFC, без управляющих символов). Его же показываем в алерте."""
    text = unicodedata.normalize("NFC", text or "")
    return "".join(ch if ch in "\n\t" or unicodedata.category(ch)[0] != "C" else " " for ch in text)


def fold(text: str) -> str:
    """Для поиска: нижний регистр, ё→е, польские буквы без диакритики. Длина та же, что у prepare()."""
    low = text.lower()
    if len(low) != len(text):          # редкие символы, меняющие длину при lower() (напр. «İ»)
        low = "".join(ch.lower()[:1] or ch for ch in text)
    return low.translate(_FOLD)


class _TextExtractor(HTMLParser):
    _BREAKS = {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "blockquote", "pre"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._BREAKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._BREAKS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def strip_html(raw: str) -> str:
    """HTML → обычный текст (для Reddit RSS и HN). Не падает на битой разметке."""
    if not raw:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(raw)
        parser.close()
        text = "".join(parser.parts)
    except Exception:  # noqa: BLE001 — на всякий случай: грубая очистка
        text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


# ---------------------------------------------------------------------------
# Компиляция словарей из config
# ---------------------------------------------------------------------------
def _compile(phrase: str) -> re.Pattern[str]:
    if phrase.startswith("re:"):
        return re.compile(phrase[3:])
    body = fold(prepare(phrase)).strip()
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", body) if p]
    pattern = r"[\s\-]*".join(parts)
    if body[:1] and (body[0].isalnum() or body[0] == "_"):
        pattern = r"(?<!\w)" + pattern        # совпадение с начала слова
    return re.compile(pattern)


@dataclass(frozen=True)
class _Rule:
    phrase: str
    lang: str
    rx: re.Pattern[str]


def _rules(source: dict[str, list[str]]) -> list[_Rule]:
    out = []
    for lang, phrases in source.items():
        for ph in phrases:
            try:
                out.append(_Rule(ph, lang, _compile(ph)))
            except re.error as exc:
                raise ValueError(f"Ошибка в регулярке config ({lang}): {ph!r}: {exc}") from exc
    return out


BUY_RULES = _rules(config.BUY_SIGNALS)
HARD_RULES = _rules(config.HARD_REJECT)
SELLER_RULES = _rules(config.SELLER_PENALTY)
BOOST_RULES = {cat: _rules(by_lang) for cat, by_lang in config.BOOST_SIGNALS.items()}
KIND_RULES = [(kind, _rules({"*": phrases})) for kind, phrases in config.KIND_SIGNALS.items()]

# ---------------------------------------------------------------------------
# Определение языка
# ---------------------------------------------------------------------------
_UK_ONLY = set("іїєґ")
_RU_ONLY = set("ыэъё")
_PL_ONLY = set("ąćęłńśźż")     # ó не берём: встречается и в других языках
_STOP = {
    "ru": {"что", "это", "нужно", "нужен", "нужна", "мне", "его", "который", "чтобы", "также", "ищу", "сделать",
           "если", "только", "есть", "или", "надо", "можно", "кто", "как", "все", "уже", "сайт"},
    "uk": {"що", "це", "потрібно", "потрібен", "потрібна", "мені", "його", "який", "щоб", "також", "шукаю",
           "зробити", "та", "або", "від", "треба", "можна", "хто", "як", "вже", "до", "із"},
    "pl": {"i", "w", "nie", "na", "się", "jest", "że", "do", "to", "jak", "dla", "potrzebuję", "szukam", "strony",
           "strona", "mam", "jestem", "kto", "czy", "albo", "oraz", "zlecę", "który", "która"},
    "en": {"the", "and", "to", "a", "is", "for", "need", "looking", "with", "my", "we", "you", "i'm", "that",
           "someone", "who", "can", "build", "website", "of", "in", "our", "this", "it"},
}
_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?")


def detect_language(text: str) -> str:
    """en / ru / uk / pl — по алфавиту, специфическим буквам и частым словам."""
    t = prepare(text).lower().replace("’", "'")
    cyr = sum(1 for c in t if "Ѐ" <= c <= "ӿ")
    lat = sum(1 for c in t if "a" <= c <= "z" or c in "ąćęłńóśźż")
    words = _WORD.findall(t)
    if cyr and cyr >= lat * 0.5:
        uk = 3 * sum(c in _UK_ONLY for c in t) + 2 * sum(w in _STOP["uk"] for w in words)
        ru = 3 * sum(c in _RU_ONLY for c in t) + 2 * sum(w in _STOP["ru"] for w in words)
        return "uk" if uk > ru else "ru"
    pl = 3 * sum(c in _PL_ONLY for c in t) + 2 * sum(w in _STOP["pl"] for w in words)
    en = 2 * sum(w in _STOP["en"] for w in words)
    return "pl" if pl > en else "en"


# ---------------------------------------------------------------------------
# Скоринг
# ---------------------------------------------------------------------------
_URL = re.compile(r"https?://\S+|www\.\S+|t\.me/\S+", re.I)
_HASHTAG = re.compile(r"#\w+")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


@dataclass
class ScoreResult:
    accepted: bool
    score: int
    lang: str
    kind: str = "site"
    buy: list[str] = field(default_factory=list)
    boosts: dict[str, list[str]] = field(default_factory=dict)
    penalties: list[str] = field(default_factory=list)
    reject_reason: str | None = None
    fingerprint: str = ""
    first_hit: int = 0           # позиция первого сигнала заказа — вокруг неё режем фрагмент

    @property
    def urgent(self) -> bool:
        return "deadline" in self.boosts

    def reason(self) -> str:
        if self.reject_reason:
            return f"отклонено: {self.reject_reason}"
        parts = []
        if self.buy:
            parts.append("заказ: " + ", ".join(f"«{b}»" for b in self.buy[:4]))
        for cat, hits in self.boosts.items():
            parts.append(f"{config.BOOST_LABELS.get(cat, cat)} ({', '.join(hits[:2])})")
        if self.penalties:
            parts.append("штраф: " + ", ".join(self.penalties[:3]))
        return " · ".join(parts) or "нет сигналов"


def fingerprint(text: str) -> str:
    """Отпечаток для поиска дублей: без ссылок, упоминаний, цифр, пунктуации и регистра."""
    t = fold(prepare(text))
    t = _URL.sub(" ", t)
    t = re.sub(r"@\w+", " ", t)
    t = re.sub(r"[^\w]+|\d+|_", " ", t)
    t = " ".join(t.split())
    return hashlib.sha1(t.encode("utf-8")).hexdigest()


def _hits(rules: list[_Rule], text: str) -> list[tuple[str, int]]:
    found, seen = [], set()
    for r in rules:
        m = r.rx.search(text)
        if m and r.phrase not in seen:
            seen.add(r.phrase)
            # для регулярок показываем совпавший кусок текста, а не саму регулярку
            label = m.group(0).strip() if r.phrase.startswith("re:") else r.phrase
            found.append((label, m.start()))
    return found


def _reject(lang: str, why: str, fp: str) -> ScoreResult:
    return ScoreResult(False, 0, lang, reject_reason=why, fingerprint=fp)


def score_text(raw: str) -> ScoreResult:
    text = prepare(raw)
    lang = detect_language(text)
    fp = fingerprint(text)
    low = fold(text)

    # --- мусор ---
    letters = sum(ch.isalpha() for ch in text)
    visible = sum(not ch.isspace() for ch in text) or 1
    if letters < config.MIN_LETTERS:
        return _reject(lang, "слишком короткий текст", fp)
    if letters / visible < 0.45:
        return _reject(lang, "почти нет букв (символы/ссылки)", fp)
    links = len(_URL.findall(text))
    if links > config.MAX_LINKS:
        return _reject(lang, f"спам: {links} ссылок", fp)

    # --- жёсткие отказы: найм в штат, «for hire» ---
    hard = _hits(HARD_RULES, low)
    if hard:
        return _reject(lang, "вакансия/исполнитель: " + ", ".join(f"«{h}»" for h, _ in hard[:3]), fp)

    # --- сигналы заказа ---
    buy = _hits(BUY_RULES, low)
    if not buy:
        return _reject(lang, "нет признаков заказа", fp)
    buy.sort(key=lambda x: x[1])
    score = config.SCORE_BUY_FIRST + config.SCORE_BUY_EXTRA * min(3, len(buy) - 1)

    boosts: dict[str, list[str]] = {}
    boost_total = 0
    for cat, rules in BOOST_RULES.items():
        hits = _hits(rules, low)
        if hits:
            boosts[cat] = [h for h, _ in hits]
            boost_total += config.BOOST_WEIGHTS.get(cat, 5)
    score += min(config.SCORE_BOOST_CAP, boost_total)

    penalties: list[str] = []
    for phrase, _ in _hits(SELLER_RULES, low):
        penalties.append(f"«{phrase}»")
        score -= config.SCORE_SELLER_PENALTY
    if links > 3:
        penalties.append(f"{links} ссылок"); score -= 15
    if len(_HASHTAG.findall(text)) > 8:
        penalties.append("много хэштегов"); score -= 10
    if len(_EMOJI.findall(text)) > 15:
        penalties.append("много эмодзи"); score -= 10
    if re.search(r"(.)\1{6,}", text):
        penalties.append("«!!!!!!»"); score -= 10
    if len(text) > 3500:
        penalties.append("очень длинный"); score -= 10

    kind = "site"
    for k, rules in KIND_RULES:
        if _hits(rules, low):
            kind = k
            break

    score = max(0, min(100, score))
    return ScoreResult(
        accepted=score >= config.MIN_SCORE, score=score, lang=lang, kind=kind,
        buy=[b for b, _ in buy], boosts=boosts, penalties=penalties, fingerprint=fp, first_hit=buy[0][1],
    )


# ---------------------------------------------------------------------------
# Текст для алерта
# ---------------------------------------------------------------------------
def make_snippet(raw: str, around: int = 0, limit: int | None = None) -> str:
    """Фрагмент до `limit` символов; если текст длинный — окно вокруг первого сигнала заказа."""
    limit = limit or config.SNIPPET_CHARS
    text = prepare(raw).strip()
    if len(text) <= limit:
        return re.sub(r"\n{3,}", "\n\n", text)
    start = max(0, min(around - limit // 4, len(text) - limit))
    if start:                                   # не резать слово в начале
        sp = text.find(" ", start)
        start = sp + 1 if 0 <= sp - start < 30 else start
    chunk = text[start:start + limit]
    if start + limit < len(text):
        sp = chunk.rfind(" ")
        chunk = (chunk[:sp] if sp > limit * 0.7 else chunk).rstrip() + "…"
    return re.sub(r"\n{3,}", "\n\n", ("…" if start else "") + chunk.strip())


def make_draft(res: ScoreResult) -> str:
    lang = res.lang if res.lang in config.DRAFTS else "en"
    topic = config.TOPICS.get(lang, config.TOPICS["en"]).get(res.kind) or config.TOPICS[lang]["site"]
    return config.DRAFTS[lang].format(topic=topic, brand=config.BRAND_NAME, url=config.PORTFOLIO_URL)
