"""Configuration constants, language mappings, and content filter lists."""

ALL_RESOLUTIONS = [360, 480, 720, 1080]
PER_PAGE_OPTIONS = [20]

TMDB_LANG_MAP: dict[str, list[str]] = {
    "en": ["english"],
    "de": ["german", "deutsch"],
    "ja": ["japanese"],
    "ko": ["korean"],
    "fr": ["french"],
    "es": ["spanish"],
    "ar": ["arabic"],
    "hi": ["hindi"],
    "zh": ["chinese", "mandarin", "cantonese"],
    "it": ["italian"],
    "pt": ["portuguese"],
    "ru": ["russian"],
    "tr": ["turkish"],
    "th": ["thai"],
    "nl": ["dutch"],
    "sv": ["swedish"],
    "da": ["danish"],
    "no": ["norwegian"],
    "fi": ["finnish"],
    "pl": ["polish"],
    "cs": ["czech"],
    "hu": ["hungarian"],
    "ro": ["romanian"],
    "id": ["indonesian"],
    "ms": ["malay"],
    "vi": ["vietnamese"],
}

DUBBED_KEYWORDS = [
    "hindi", "dubbed", " dub", "tamil", "telugu", "malayalam",
    "kannada", "bengali", "marathi", "[hindi]", "(hindi)", "urdu", "punjabi",
]

ARABIC_LAN_CODES = {"ar", "ara", "arabic"}

DUMMY_VIDEO_HASH = "b164fbfb4347792950bdfbfb563d39d9"

ADULT_KEYWORDS = [
    "+18", "xxx", "adult", "hentai", "erotica", "porn", "nsfw", "sex",
]

ADULT_QUERIES = [
    # Hentai & Anime Adult
    "hentai", "ecchi", "yaoi", "yuri", "shota", "lolicon",
    "tentacle", "doujinshi", "anime adult", "anime hentai",
    # Explicit - Movies & Series
    "xxx", "adult movie", "adult film", "erotic film", "erotic movie",
    "nsfw", "mature content", "18+", "onlyfans", "porn",
    "sex scene", "nude", "nudity", "explicit content",
    "hardcore", "softcore", "porn movie", "porn film",
    # Family taboo / step
    "stepsister", "stepbrother", "stepmom", "stepmother",
    "stepdad", "stepfather", "step sister", "step mom",
    "step brother", "step father", "step mother",
    # Body focused
    "boobs", "big tits", "big titty", "huge tits", "big ass",
    "tits", "ass", "milf", "teen", "busty", "curvy",
    "big cock", "big dick", "pussy", "blowjob",
    # Slang
    "fuck", "fucking", "fucked", "fucks",
    "motherfucker", "bitch", "slut", "whore",
    "cum", "cumshot", "sperm", "orgy",
    "gangbang", "threesome", "foursome",
    "dirty talk", "rough sex", "anal",
    # Softcore / Romance +
    "erotic", "sexy", "sensual", "steamy", "seduction",
    "adult comedy", "adult animation", "adult drama",
    "erotic thriller", "erotic romance", "sexy comedy",
    # International
    "porno", "film érotique", "film erotico", "erotik film",
    "adult series", "adult tv", "mature anime",
    "pornhub", "xvideos", "redtube", "youporn",
    "hentai uncensored", "hentai english dub",
    # Specific categories
    "bondage", "bdsm", "fetish", "lingerie",
    "strip", "striptease", "burlesque", "lap dance",
    "taboo", "forbidden love", "illicit", "affair",
    "cheating wife", "cheating husband", "swingers",
    # Lesbian / Gay
    "lesbian", "gay porn", "gay sex", "homemade",
    # Horror + Erotic mixed
    "vampire erotic", "horror erotic", "erotic horror",
]
