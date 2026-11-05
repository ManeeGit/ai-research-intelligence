from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

MAX_PAPERS = 5000
MAX_ABSTRACT = 24000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_url(value: str, *, synthetic: bool = False) -> str:
    if any(c.isspace() for c in value) or any(c in value for c in "\\<>\"\'"):
        raise ValueError("Source URLs cannot contain whitespace or unsafe delimiters")
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("Source URLs must be HTTPS without embedded credentials")
    if parts.port not in (None, 443) or len(value) > 2000:
        raise ValueError("Invalid source URL port or length")
    if parts.fragment:
        raise ValueError("Source URLs cannot contain fragments")
    if synthetic and not parts.hostname.endswith(".invalid"):
        raise ValueError("Synthetic fixtures must use reserved .invalid URLs")
    return value


@dataclass(frozen=True)
class Paper:
    external_id: str
    title: str
    abstract: str
    authors: list[str]
    published: str
    url: str
    source: str
    synthetic: bool = False

    @classmethod
    def from_dict(cls, value: dict) -> "Paper":
        if not isinstance(value, dict):
            raise ValueError("Each paper must be a JSON object")
        required = ("external_id", "title", "abstract", "published", "url", "source")
        for key in required:
            if not isinstance(value.get(key), str) or not value[key].strip():
                raise ValueError(f"Paper field {key} must be a nonempty string")
        limits = {"external_id": 300, "title": 1000, "abstract": MAX_ABSTRACT, "source": 120}
        for key, limit in limits.items():
            if len(value[key]) > limit:
                raise ValueError(f"Paper field {key} exceeds its length limit")
        authors = value.get("authors", [])
        if not isinstance(authors, list) or len(authors) > 100 or any(
            not isinstance(a, str) or len(a) > 200 for a in authors
        ):
            raise ValueError("authors must be a list of at most 100 short names")
        synthetic = value.get("synthetic", False)
        if not isinstance(synthetic, bool):
            raise ValueError("synthetic must be a boolean")
        published = datetime.fromisoformat(value["published"].replace("Z", "+00:00"))
        if published.tzinfo is None:
            raise ValueError("published must include a timezone")
        for key in required:
            if any(ord(c) < 32 and c not in "\n\t\r" for c in value[key]):
                raise ValueError("Control characters are not allowed in paper fields")
        safe_url(value["url"], synthetic=synthetic)
        return cls(**{key: value[key].strip() for key in required}, authors=authors,
                   synthetic=synthetic)

    @property
    def key(self) -> str:
        return hashlib.sha256(f"{self.source}\0{self.external_id}".encode()).hexdigest()[:20]

    @property
    def content_hash(self) -> str:
        import json
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)


STOPWORDS = frozenset("""a an and are as at be been being but by can could did do does for from
has have how i if in into is it its may more most of on or our paper papers research says show
some than that the their these they this those through to using was we were what when where
which who why will with would you about tell compare evidence find study studies approach
""".split())


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 1 and t not in STOPWORDS]
