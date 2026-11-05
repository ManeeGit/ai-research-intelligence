"""Bounded public-source ingestion. No generic URL fetching, redirects, or cookies."""
from __future__ import annotations

import ipaddress
import http.client
import ssl
import time
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .models import Paper
from .store import Store

MAX_INPUT_BYTES = 2_000_000
FIXTURES = Path(__file__).parent / "fixtures" / "papers.json"


def read_json(path: str | Path):
    with Path(path).open("rb") as handle:
        data = handle.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("Input exceeds the 2 MB limit")
    return json.loads(data)


def load_fixture(path: str | Path = FIXTURES) -> list[Paper]:
    payload = read_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("papers"), list):
        raise ValueError("Expected an object containing a papers array")
    if len(payload["papers"]) > 500:
        raise ValueError("A fixture may contain at most 500 papers")
    # Validate every record before making any database changes.
    return [Paper.from_dict(value) for value in payload["papers"]]


@dataclass(frozen=True)
class Source:
    name: str
    query: str
    enabled: bool = False
    max_results: int = 25
    daily_request_limit: int = 8

    @property
    def url(self) -> str:
        return "https://export.arxiv.org/api/query?" + urllib.parse.urlencode({
            "search_query": self.query, "start": 0, "max_results": self.max_results,
            "sortBy": "submittedDate", "sortOrder": "descending"})


def load_sources(path: str | Path) -> list[Source]:
    config = read_json(path)
    if not isinstance(config, dict) or not isinstance(config.get("sources"), list):
        raise ValueError("Config must contain a sources array")
    if len(config["sources"]) > 5:
        raise ValueError("At most five sources may be configured")
    sources = []
    for entry in config["sources"]:
        if not isinstance(entry, dict) or set(entry) - {"name", "query", "enabled", "max_results", "daily_request_limit"}:
            raise ValueError("Unknown source configuration fields")
        source = Source(**entry)
        if not isinstance(source.name, str) or not re.fullmatch(r"[a-z0-9_-]{1,64}", source.name):
            raise ValueError("Source names must be short lowercase identifiers")
        if not isinstance(source.query, str) or not 1 <= len(source.query) <= 300:
            raise ValueError("Source queries must contain 1–300 characters")
        if any(ord(c) < 32 for c in source.query):
            raise ValueError("Source queries cannot contain control characters")
        if type(source.enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        if type(source.max_results) is not int or not 1 <= source.max_results <= 100:
            raise ValueError("max_results must be between 1 and 100")
        if type(source.daily_request_limit) is not int or not 1 <= source.daily_request_limit <= 24:
            raise ValueError("daily_request_limit must be between 1 and 24")
        sources.append(source)
    if len({s.name for s in sources}) != len(sources):
        raise ValueError("Source names must be unique")
    return sources


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Source redirects are not permitted")


def assert_public_arxiv(url: str):
    parts = urllib.parse.urlsplit(url)
    if (parts.scheme != "https" or parts.hostname != "export.arxiv.org" or
            parts.path != "/api/query" or parts.username or parts.password or
            parts.port not in (None, 443) or parts.fragment):
        raise ValueError("Only the approved HTTPS arXiv API endpoint is supported")
    addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Source did not resolve exclusively to public addresses")
    return addresses[0][4][0]


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to the validated IP while verifying TLS against the official hostname."""
    def __init__(self, address: str):
        self.address = address
        self.tls_context = ssl.create_default_context()
        super().__init__("export.arxiv.org", timeout=20, context=self.tls_context)

    def connect(self):
        sock = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self.tls_context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def fetch_arxiv(source: Source) -> list[Paper]:
    address = assert_public_arxiv(source.url)
    connection = PinnedHTTPSConnection(address)
    parts = urllib.parse.urlsplit(source.url)
    try:
        connection.request("GET", parts.path + "?" + parts.query, headers={
            "User-Agent": "ResearchIntelligence/0.1 (bounded personal research reader)",
            "Accept": "application/atom+xml", "Accept-Encoding": "identity"})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("Source returned an unexpected status; redirects are not followed")
        payload = response.read(MAX_INPUT_BYTES + 1)
    except (OSError, http.client.HTTPException) as error:
        raise ValueError("Source request failed; no automatic retry was attempted") from error
    finally:
        connection.close()
    return parse_atom(payload, source)


def parse_atom(payload: bytes, source: Source) -> list[Paper]:
    if len(payload) > MAX_INPUT_BYTES:
        raise ValueError("Source response exceeds the 2 MB limit")
    try:
        decoded = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Source XML must use UTF-8") from error
    if "\x00" in decoded or "<!DOCTYPE" in decoded.upper() or "<!ENTITY" in decoded.upper():
        raise ValueError("XML declarations with entities or non-UTF-8 content are forbidden")
    try:
        root = ET.fromstring(decoded)
    except ET.ParseError as error:
        raise ValueError("Source returned malformed XML") from error
    if root.tag != "{http://www.w3.org/2005/Atom}feed":
        raise ValueError("Source did not return an Atom feed")
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entries = root.findall("a:entry", ns)
    if len(entries) > source.max_results:
        raise ValueError("Source returned more papers than the configured limit")
    papers = []
    for entry in entries:
        def get(name):
            return " ".join((entry.findtext(f"a:{name}", default="", namespaces=ns)).split())
        raw_id = get("id")
        match = re.fullmatch(r"https?://arxiv\.org/abs/((?:\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7})(?:v\d+)?)", raw_id)
        if not match:
            raise ValueError("Source entry has an unexpected arXiv identifier")
        versioned_id = match.group(1)
        stable_id = re.sub(r"v\d+$", "", versioned_id)
        authors = [" ".join((node.text or "").split()) for node in entry.findall("a:author/a:name", ns)]
        papers.append(Paper.from_dict({
            "external_id": stable_id, "source": "arxiv", "title": get("title"),
            "abstract": get("summary"), "authors": authors,
            "published": get("published"), "url": f"https://arxiv.org/abs/{versioned_id}",
            "synthetic": False,
        }))
    return papers


def ingest_sources(store: Store, config: str | Path, *, allow_network: bool = False) -> list[dict]:
    if not allow_network:
        raise ValueError("Live ingestion requires explicit --allow-network")
    sources = [s for s in load_sources(config) if s.enabled]
    if not sources:
        raise ValueError("No sources are enabled; review and enable one in your config")
    results = []
    for index, source in enumerate(sources):
        if index:
            time.sleep(3)  # Respect arXiv guidance between sequential requests.
        store.reserve_request("arxiv:" + source.name, source.daily_request_limit)
        papers = fetch_arxiv(source)
        results.append({"source": source.name, **store.ingest(papers, source.name)})
    return results
