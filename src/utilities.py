def pluralize(count: int, singular: str, plural: str | None = None) -> str:
    """The form of a word matching `count`. Defaults to adding an "s";
    pass `plural` for irregular words (e.g. pluralize(n, "entry", "entries"))."""
    if count == 1:
        return singular
    return plural if plural is not None else f"{singular}s"
