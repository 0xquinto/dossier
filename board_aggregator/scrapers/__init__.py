from board_aggregator.scrapers.base import BaseScraper

SCRAPER_REGISTRY: dict[str, type[BaseScraper]] = {}


def register(cls: type[BaseScraper]) -> type[BaseScraper]:
    """Decorator to register a scraper class."""
    SCRAPER_REGISTRY[cls.name] = cls
    return cls


def get_all_scrapers() -> list[BaseScraper]:
    """Instantiate and return all registered scrapers."""
    return [cls() for cls in SCRAPER_REGISTRY.values()]


def _coerce_board_list(value: object, field: str) -> list[str] | None:
    """Validate an allow/deny value, rejecting silently-bypassing types.

    Returns None (no filter) or a list of board names. Raises ValueError on a
    malformed value. The critical case: a bare string (e.g. forgetting YAML
    list syntax, `deny: crypto_jobs cryptojobslist`) must NOT be iterated as a
    set of characters — that would silently bypass the filter and leak every
    board. Such values are rejected loudly.
    """
    if value is None:
        return None
    if isinstance(value, str):
        raise ValueError(
            f"boards.{field} must be a YAML list, got a string: {value!r}. "
            f"Use list syntax, e.g.\n  boards:\n    {field}:\n      - crypto_jobs"
        )
    if not isinstance(value, (list, tuple)):
        raise ValueError(
            f"boards.{field} must be a YAML list, got {type(value).__name__}: {value!r}"
        )
    items = [str(v) for v in value]
    return items or None


def filter_scrapers(
    names: list[str],
    allowlist: list[str] | None = None,
    denylist: list[str] | None = None,
) -> list[str]:
    """Apply a per-user board allow/deny filter to a list of scraper names.

    Backward-compatible: with no allowlist and no denylist, every name is
    returned unchanged. An allowlist restricts to the named boards; a denylist
    drops them. If both are given, allowlist applies first, then denylist.
    Order is preserved.

    A non-list allow/deny value (e.g. a bare string from malformed YAML) is
    rejected with ValueError rather than silently iterated character-by-character,
    which would bypass the filter and leak every board.
    """
    allowlist = _coerce_board_list(allowlist, "allow")
    denylist = _coerce_board_list(denylist, "deny")
    result = list(names)
    if allowlist:
        allowed = set(allowlist)
        result = [n for n in result if n in allowed]
    if denylist:
        denied = set(denylist)
        result = [n for n in result if n not in denied]
    return result
