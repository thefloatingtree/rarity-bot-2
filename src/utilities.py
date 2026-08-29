# Postpone annotation evaluation so `str | None` style hints run on Python 3.9
# (the VM's interpreter) as well as 3.10+.
from __future__ import annotations


def pluralize(count: int, singular: str, plural: str | None = None) -> str:
    """The form of a word matching `count`. Defaults to adding an "s";
    pass `plural` for irregular words (e.g. pluralize(n, "entry", "entries"))."""
    if count == 1:
        return singular
    return plural if plural is not None else f"{singular}s"
