from locales import ru

_TRANSLATIONS = {"ru": ru.STRINGS}
_DEFAULT = "ru"


def t(key: str, lang: str = _DEFAULT, **kwargs) -> str:
    table = _TRANSLATIONS.get(lang) or _TRANSLATIONS[_DEFAULT]
    text = table.get(key) or _TRANSLATIONS[_DEFAULT].get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text