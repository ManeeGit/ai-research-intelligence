import copy
import http.client
import json
import socket
import tempfile
import threading
import unittest
from dataclasses import replace
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

from research_agent.briefs import daily_brief, render_markdown, write_brief
from research_agent.cli import main
from research_agent.evaluation import evaluate
from research_agent.local_model import select_evidence
from research_agent.models import Paper
from research_agent.retrieval import answer, search, verify_citation
from research_agent.scheduler import exclusive_lock, watch
from research_agent.sources import PinnedHTTPSConnection, fetch_arxiv, Source, assert_public_arxiv, ingest_sources, load_fixture, load_sources, parse_atom
from research_agent.store import Store
from research_agent.web import make_handler

ATOM = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>http://arxiv.org/abs/2601.12345v2</id><title>Local evidence</title>
<summary>Exact citations preserve source evidence and improve traceability.</summary>
<author><name>Example Author</name></author><published>2026-01-02T12:00:00Z</published>
</entry></feed>'''


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.sqlite3"
        self.store = Store(self.path)
        self.papers = load_fixture()
        self.store.ingest(self.papers)

    def tearDown(self):
        self.store.conn.close()
        self.temp.cleanup()

    def test_deduplication(self):
        result = self.store.ingest(self.papers)
        self.assertEqual(result, {"added": 0, "updated": 0, "unchanged": 12, "total": 12})

    def test_changed_source_updates_same_identity(self):
        paper = replace(self.papers[0], abstract="A changed abstract contains a different evidence statement.")
        result = self.store.ingest([paper])
        self.assertEqual(result["updated"], 1)
        self.assertEqual(self.store.count(), 12)
        self.assertEqual(self.store.get(paper.key)["abstract"], paper.abstract)

    def test_duplicate_records_in_one_batch(self):
        self.assertEqual(self.store.ingest([self.papers[0]] * 3)["unchanged"], 3)

    def test_every_quote_is_exact(self):
        response = answer(self.store, "citation quotes offsets content hash")
        self.assertGreater(len(response["citations"]), 0)
        self.assertTrue(all(verify_citation(self.store, c) for c in response["citations"]))

    def test_tampered_citation_rejected(self):
        citation = answer(self.store, "citation quotes offsets")["citations"][0]
        for field, value in [("quote", "fabricated"), ("start", -1), ("end", 1_000_000), ("url", "https://evil.invalid"), ("content_hash", "bad"), ("paper_id", "absent"), ("start", True)]:
            altered = {**citation, field: value}
            self.assertFalse(verify_citation(self.store, altered), field)

    def test_stale_citation_rejected(self):
        citation = answer(self.store, "citation quotes offsets")["citations"][0]
        paper = next(p for p in self.papers if p.key == citation["paper_id"])
        self.store.ingest([replace(paper, abstract=paper.abstract + " The source changed.")])
        self.assertFalse(verify_citation(self.store, citation))

    def test_unknown_question_abstains(self):
        response = answer(self.store, "What is the mass of a Higgs boson?")
        self.assertEqual(response["status"], "insufficient_evidence")
        self.assertEqual(response["citations"], [])

    def test_stopwords_abstain(self):
        self.assertEqual(answer(self.store, "what is it")['citations'], [])

    def test_invalid_query(self):
        for query in ["", " " * 10, 42, "a" * 3001]:
            with self.assertRaises(ValueError):
                answer(self.store, query)

    def test_search_ranking(self):
        result = search(self.store, "BM25 lexical retrieval")
        self.assertEqual(result[0].paper["external_id"], "demo-bm25-index")

    def test_regression_evaluation(self):
        result = evaluate(self.store)
        self.assertEqual(result["passed"], result["total"])
        self.assertEqual(result["recall_at_3"], 1)
        self.assertTrue(result["citation_validity"])

    def test_daily_brief(self):
        brief = daily_brief(self.store)
        self.assertEqual(brief["new_or_changed"], 12)
        self.assertTrue(brief["synthetic"])
        paths = write_brief(brief, Path(self.temp.name) / "reports")
        self.assertTrue(all(path.exists() for path in paths))
        self.assertIn("SYNTHETIC DEMO", paths[0].read_text())

    def test_brief_uses_ingestion_not_publication_day(self):
        brief = daily_brief(self.store, day="2000-01-01")
        self.assertEqual(brief["new_or_changed"], 0)

    def test_brief_escapes_untrusted_markup(self):
        brief = daily_brief(self.store)
        brief["highlights"][0]["title"] = '<script>x</script> ![leak](https://evil.invalid)'
        rendered = render_markdown(brief)
        self.assertNotIn('<script>', rendered)
        self.assertNotIn('![leak]', rendered)

    def test_request_budget_persists(self):
        self.store.reserve_request("source", 1, "2026-11-05")
        with Store(self.path) as other:
            with self.assertRaisesRegex(ValueError, "budget"):
                other.reserve_request("source", 1, "2026-11-05")
            other.reserve_request("source", 1, "2026-11-06")

    def test_index_limit(self):
        with patch("research_agent.store.MAX_PAPERS", 12):
            with self.assertRaisesRegex(ValueError, "capped"):
                self.store.ingest([replace(self.papers[0], external_id="new")])
        self.assertEqual(self.store.count(), 12)

    def test_concurrent_writers_preserve_limit(self):
        errors = []
        def ingest(index):
            try:
                with Store(self.path) as store:
                    store.ingest([replace(self.papers[0], external_id=f"new-{index}")])
            except ValueError as error:
                errors.append(error)
        with patch("research_agent.store.MAX_PAPERS", 13):
            threads = [threading.Thread(target=ingest, args=(i,)) for i in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
        self.assertEqual(self.store.count(), 13)
        self.assertEqual(len(errors), 1)

    def test_watch_offline_and_finite(self):
        pauses = []
        with patch("research_agent.sources.fetch_arxiv") as fetch:
            events = watch(self.path, Path(self.temp.name) / "out", cycles=2, interval=300, sleep=pauses.append)
        self.assertEqual(len(events), 2)
        self.assertEqual(pauses, [300])
        fetch.assert_not_called()
        self.assertFalse(self.path.with_suffix('.sqlite3.watch.lock').exists())

    def test_watch_bounds(self):
        for options in [{"cycles": 0}, {"cycles": 25}, {"interval": 1}, {"cycles": 24, "interval": 86400}, {"allow_network": True}, {"config": "missing"}]:
            with self.assertRaises(ValueError):
                watch(self.path, self.temp.name, **options)

    def test_lock_rejects_overlap_and_cleans_up(self):
        lock = Path(self.temp.name) / "watch.lock"
        with exclusive_lock(lock):
            with self.assertRaises(ValueError):
                with exclusive_lock(lock): pass
        self.assertFalse(lock.exists())

    def test_watch_failure_releases_lock(self):
        with patch("research_agent.scheduler.load_fixture", side_effect=ValueError("bad source")):
            with self.assertRaises(ValueError):
                watch(self.path, self.temp.name)
        self.assertFalse(self.path.with_suffix('.sqlite3.watch.lock').exists())

    def test_failed_requests_consume_quota(self):
        config = Path(self.temp.name) / "sources.json"
        config.write_text(json.dumps({"sources":[{"name":"test", "query":"cat:cs.AI", "enabled":True, "daily_request_limit":1}]}))
        with patch("research_agent.sources.fetch_arxiv", side_effect=ValueError("network failure")) as fetch:
            with self.assertRaisesRegex(ValueError, "network failure"):
                ingest_sources(self.store, config, allow_network=True)
            with self.assertRaisesRegex(ValueError, "budget"):
                ingest_sources(self.store, config, allow_network=True)
            self.assertEqual(fetch.call_count, 1)

    def test_disabled_sources_do_not_fetch(self):
        config = Path(self.temp.name) / "sources.json"
        config.write_text(json.dumps({"sources":[{"name":"test", "query":"cat:cs.AI", "enabled":False}]}))
        with patch("research_agent.sources.fetch_arxiv") as fetch:
            with self.assertRaisesRegex(ValueError, "No sources"):
                ingest_sources(self.store, config, allow_network=True)
            fetch.assert_not_called()

    def test_network_is_opt_in(self):
        with patch("research_agent.sources.fetch_arxiv") as fetch:
            with self.assertRaisesRegex(ValueError, "allow-network"):
                ingest_sources(self.store, "does-not-exist")
        fetch.assert_not_called()


class SourceCase(unittest.TestCase):
    def test_valid_atom(self):
        papers = parse_atom(ATOM.encode(), Source("test", "cat:cs.AI"))
        self.assertEqual(papers[0].external_id, "2601.12345")
        self.assertEqual(papers[0].url, "https://arxiv.org/abs/2601.12345v2")
        self.assertFalse(papers[0].synthetic)

    def test_invalid_xml_rejected(self):
        samples = [b"<", b"<not_a_feed/>", ATOM.replace('http://arxiv.org/abs/2601.12345v2', 'http://arxiv.org/api/errors#bad').encode()]
        for sample in samples:
            with self.assertRaises(ValueError): parse_atom(sample, Source("test", "x"))

    def test_entities_and_alternate_encoding_rejected(self):
        xml = '<!DOCTYPE feed [<!ENTITY x "expanded">]>' + ATOM.replace('Local evidence', '&x;')
        for encoding in ['utf-8', 'utf-16', 'utf-32']:
            with self.assertRaises(ValueError): parse_atom(xml.encode(encoding), Source("test", "x"))

    def test_oversized_feed_rejected(self):
        with self.assertRaises(ValueError): parse_atom(b"a" * 2_000_001, Source("test", "x"))

    def test_unapproved_urls_rejected_before_dns(self):
        for url in ["http://export.arxiv.org/api/query", "https://evil.invalid/api/query", "https://user:password@export.arxiv.org/api/query", "https://export.arxiv.org:8443/api/query", "https://export.arxiv.org/other"]:
            with patch("socket.getaddrinfo") as dns:
                with self.assertRaises(ValueError): assert_public_arxiv(url)
                dns.assert_not_called()

    def test_private_and_mixed_dns_rejected(self):
        for addresses in [["127.0.0.1"], ["169.254.169.254"], ["8.8.8.8", "10.0.0.1"], ["::1"]]:
            resolved = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443)) for address in addresses]
            with patch("socket.getaddrinfo", return_value=resolved):
                with self.assertRaises(ValueError): assert_public_arxiv(Source("test", "x").url)

    def test_config_requires_explicit_boolean(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sources.json"
            path.write_text(json.dumps({"sources": [{"name":"test", "query":"x", "enabled":"false"}]}))
            with self.assertRaises(ValueError): load_sources(path)

    def test_pinned_tls_preserves_hostname_verification(self):
        context = MagicMock()
        with patch("ssl.create_default_context", return_value=context), patch("socket.create_connection") as connect:
            connection = PinnedHTTPSConnection("8.8.8.8")
            connection.connect()
            connect.assert_called_once_with(("8.8.8.8", 443), timeout=20)
            context.wrap_socket.assert_called_once_with(connect.return_value, server_hostname="export.arxiv.org")

    def test_redirect_not_followed(self):
        with patch("research_agent.sources.assert_public_arxiv", return_value="8.8.8.8"), patch("research_agent.sources.PinnedHTTPSConnection") as connection:
            connection.return_value.getresponse.return_value.status = 302
            with self.assertRaisesRegex(ValueError, "redirects"):
                fetch_arxiv(Source("test", "x"))
            self.assertEqual(connection.return_value.request.call_count, 1)
            connection.return_value.close.assert_called_once()

    def test_malformed_http_is_sanitized(self):
        with patch("research_agent.sources.assert_public_arxiv", return_value="8.8.8.8"), patch("research_agent.sources.PinnedHTTPSConnection") as connection:
            connection.return_value.getresponse.side_effect = http.client.BadStatusLine("bad source")
            with self.assertRaisesRegex(ValueError, "Source request failed"):
                fetch_arxiv(Source("test", "x"))

    def test_synthetic_requires_reserved_domain(self):
        data = load_fixture()[0].to_dict()
        data["url"] = "https://arxiv.org/abs/2601.12345"
        with self.assertRaises(ValueError): Paper.from_dict(data)

    def test_invalid_schema(self):
        for field, value in [("authors", "name"), ("synthetic", "true"), ("published", "2026-11-05"), ("title", "")]:
            data = load_fixture()[0].to_dict(); data[field] = value
            with self.assertRaises(ValueError): Paper.from_dict(data)


class ModelCase(unittest.TestCase):
    def call(self, raw):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = raw
        opener = MagicMock(); opener.open.return_value = response
        with patch("urllib.request.build_opener", return_value=opener):
            return select_evidence("citation evidence", [{"id":"E1", "title":"Test", "quote":"Source evidence."}], "qwen2.5:1.5b")

    def test_valid_selection(self):
        citations, note = self.call(json.dumps({"response":json.dumps({"evidence_ids":["E1"]})}).encode())
        self.assertEqual(citations[0]["id"], "E1"); self.assertIsNone(note)

    def test_invalid_outputs_fall_back(self):
        for output in [[], None, "string", 5, {}, {"evidence_ids":["E9"]}, {"evidence_ids":["E1", "E1"]}, {"evidence_ids":[]}, {"evidence_ids":[{}]}]:
            with self.subTest(output=output):
                citations, note = self.call(json.dumps({"response":json.dumps(output)}).encode())
                self.assertIsNotNone(note); self.assertEqual(len(citations), 1)

    def test_invalid_envelopes_fall_back(self):
        for raw in [b'[]', b'null', b'{}', b'not json', b'{"response":null}']:
            citations, note = self.call(raw)
            self.assertIsNotNone(note)


class WebCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temp.name) / "web.sqlite3"
        with Store(cls.path) as store: store.ingest(load_fixture())
        cls.server = HTTPServer(("127.0.0.1", 0), make_handler(cls.path))
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(); cls.temp.cleanup()

    def request(self, path, method="GET", body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse(); data = response.read(); status = response.status; response_headers = dict(response.getheaders()); conn.close()
        return status, data, response_headers

    def test_status(self):
        status, body, headers = self.request('/api/status')
        self.assertEqual(status, 200); self.assertEqual(json.loads(body)["papers"], 12)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_rebinding_and_cross_origin_blocked(self):
        for headers in [{"Host":"evil.invalid"}, {"Origin":"https://evil.invalid"}, {"Origin":"null"}]:
            self.assertEqual(self.request('/api/status', headers=headers)[0], 403)

    def test_answer(self):
        status, body, _ = self.request('/api/answer', 'POST', json.dumps({"query":"citation quotes offsets"}), {"Content-Type":"application/json", "X-Research-Request":"1"})
        self.assertEqual(status, 200); self.assertGreater(len(json.loads(body)["citations"]), 0)

    def test_csrf_and_invalid_payloads(self):
        self.assertEqual(self.request('/api/answer', 'POST', 'query=test')[0], 403)
        for body in ['[]', '{}', '{"query":42}', '{"query":"x","model":"remote"}', 'x']:
            self.assertEqual(self.request('/api/answer', 'POST', body, {"Content-Type":"application/json", "X-Research-Request":"1"})[0], 400)

    def test_static_and_no_path_traversal(self):
        for path in ['/', '/app.js', '/style.css']:
            self.assertEqual(self.request(path)[0], 200)
        for path in ['/../pyproject.toml', '/fixtures/papers.json', '/api/ingest']:
            self.assertEqual(self.request(path)[0], 404)


if __name__ == '__main__':
    unittest.main()
