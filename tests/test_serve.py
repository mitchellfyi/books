"""The local server: playlist persistence, byte ranges, and cache freshness.

Range arithmetic and the playlist payload are the two places the server does
its own parsing rather than deferring to http.server, so they are the two
worth holding still. Each test runs the real handler over a throwaway root.
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

from fixtures import bookflow, bookflow_at

BODY = bytes(range(256)) * 8  # 2048 bytes, every value distinguishable


class Quiet(bookflow.LibraryHandler):
    """The handler under test, minus its logging: these tests provoke errors."""

    def log_message(self, format: str, *args: object) -> None:
        pass


class ServerTestCase(unittest.TestCase):
    """A live server on a throwaway root, torn down with the test."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "data").mkdir()
        (self.root / "dist").mkdir()
        (self.root / "dist/media.mp3").write_bytes(BODY)
        (self.root / "dist/index.html").write_text("<p>hello</p>", encoding="utf-8")

        self.context = bookflow_at(self.root)
        self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)

        handler = partial(Quiet, directory=str(self.root / "dist"))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.addCleanup(self.server.server_close)
        # A short poll interval: shutdown() waits for the next one, and the
        # default half-second would dominate the whole suite's run time.
        thread = threading.Thread(target=self.server.serve_forever, args=(0.01,), daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def get(self, path: str, headers: dict | None = None):
        request = urllib.request.Request(self.base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def put(self, path: str, payload: object, raw: bytes | None = None):
        body = raw if raw is not None else json.dumps(payload).encode()
        request = urllib.request.Request(self.base + path, data=body, method="PUT")
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()


class RangeTests(ServerTestCase):
    def test_a_byte_range_returns_just_those_bytes(self) -> None:
        status, headers, body = self.get("/media.mp3", {"Range": "bytes=10-19"})
        self.assertEqual(status, 206)
        self.assertEqual(headers["Content-Range"], f"bytes 10-19/{len(BODY)}")
        self.assertEqual(headers["Content-Length"], "10")
        self.assertEqual(body, BODY[10:20])

    def test_an_open_ended_range_runs_to_the_end(self) -> None:
        status, headers, body = self.get("/media.mp3", {"Range": "bytes=2040-"})
        self.assertEqual(status, 206)
        self.assertEqual(headers["Content-Range"], f"bytes 2040-{len(BODY) - 1}/{len(BODY)}")
        self.assertEqual(body, BODY[2040:])

    def test_a_suffix_range_counts_back_from_the_end(self) -> None:
        status, _, body = self.get("/media.mp3", {"Range": "bytes=-16"})
        self.assertEqual(status, 206)
        self.assertEqual(body, BODY[-16:])

    def test_a_suffix_longer_than_the_file_returns_all_of_it(self) -> None:
        status, _, body = self.get("/media.mp3", {"Range": f"bytes=-{len(BODY) * 2}"})
        self.assertEqual(status, 206)
        self.assertEqual(body, BODY)

    def test_an_end_past_the_file_stops_at_the_last_byte(self) -> None:
        status, headers, body = self.get("/media.mp3", {"Range": "bytes=2000-99999"})
        self.assertEqual(status, 206)
        self.assertEqual(headers["Content-Range"], f"bytes 2000-{len(BODY) - 1}/{len(BODY)}")
        self.assertEqual(body, BODY[2000:])

    def test_a_start_past_the_file_is_unsatisfiable(self) -> None:
        status, headers, _ = self.get("/media.mp3", {"Range": "bytes=99999-"})
        self.assertEqual(status, 416)
        self.assertEqual(headers["Content-Range"], f"bytes */{len(BODY)}")

    def test_a_range_this_server_cannot_honour_serves_the_whole_file(self) -> None:
        # RFC 9110 allows ignoring a Range header; answering 206 with the whole
        # body would tell the player it received only part of the recording.
        for header in ("bytes=0-10,20-30", "sausages", "bytes=-", "items=0-1"):
            with self.subTest(header=header):
                status, _, body = self.get("/media.mp3", {"Range": header})
                self.assertEqual(status, 200)
                self.assertEqual(body, BODY)


class CacheTests(ServerTestCase):
    def test_rebuilt_files_are_never_served_from_cache(self) -> None:
        # serve rebuilds dist on every start, so a held copy would be stale.
        for path in ("/", "/index.html", "/data/library.json"):
            with self.subTest(path=path):
                _, headers, _ = self.get(path)
                self.assertEqual(headers.get("Cache-Control"), "no-store")

    def test_audio_stays_cacheable(self) -> None:
        _, headers, _ = self.get("/media.mp3")
        self.assertIsNone(headers.get("Cache-Control"))


class PlaylistApiTests(ServerTestCase):
    valid = {"schema_version": 1, "playlists": [
        {"id": "evening", "name": "Evening", "updated_at": "2026-01-01T00:00:00Z",
         "items": [{"book_id": "deep-work-newport", "duration": "30-seconds"}]}]}

    def test_an_absent_file_reads_as_an_empty_list(self) -> None:
        status, _, body = self.get("/api/playlists")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"schema_version": 1, "playlists": []})

    def test_a_saved_playlist_round_trips_to_the_library(self) -> None:
        self.assertEqual(self.put("/api/playlists", self.valid)[0], 200)
        stored = self.stored()
        self.assertEqual({k: v for k, v in stored.items() if k != "$schema"}, self.valid)
        self.assertEqual(json.loads(self.get("/api/playlists")[2]), stored)

    def test_the_schema_pointer_survives_a_save(self) -> None:
        # The browser sends playlists, not repository conventions; without this
        # the first save strips the pointer every sibling data file carries.
        self.put("/api/playlists", self.valid)
        self.assertEqual(self.stored()["$schema"], "../schemas/playlists.schema.json")
        # And a payload that carries its own does not end up with two.
        self.put("/api/playlists", {"$schema": "../schemas/playlists.schema.json", **self.valid})
        self.assertEqual(list(self.stored()), ["$schema", "schema_version", "playlists"])

    def stored(self) -> dict:
        return json.loads((self.root / "data/playlists.json").read_text(encoding="utf-8"))

    def test_a_rejected_payload_leaves_the_stored_playlists_alone(self) -> None:
        self.put("/api/playlists", self.valid)
        rejected = [
            {"schema_version": 2, "playlists": []},
            {"schema_version": 1, "playlists": "not a list"},
            {"schema_version": 1, "playlists": [{"id": "a"}]},
            {"schema_version": 1, "playlists": [
                {"id": "a", "name": "A", "items": [{"book_id": 1, "duration": "x"}]}]},
        ]
        for payload in rejected:
            with self.subTest(payload=payload):
                self.assertEqual(self.put("/api/playlists", payload)[0], 400)
        self.assertEqual({k: v for k, v in self.stored().items() if k != "$schema"}, self.valid)

    def test_malformed_json_is_rejected(self) -> None:
        self.assertEqual(self.put("/api/playlists", None, raw=b"{not json")[0], 400)

    def test_an_empty_body_is_a_bad_request_not_an_oversized_one(self) -> None:
        status, body = self.put("/api/playlists", None, raw=b"")
        self.assertEqual(status, 400)
        # Not just the status: an empty body and a malformed one are different
        # mistakes, and saying "invalid" for a missing one sends the reader
        # looking at a payload that was never sent.
        self.assertIn("missing playlists payload", body.decode())

    def test_an_oversized_body_is_refused_unread(self) -> None:
        huge = {"schema_version": 1, "playlists": [
            {"id": "x", "name": "y" * 3_000_000, "items": []}]}
        self.assertEqual(self.put("/api/playlists", huge)[0], 413)

    def test_writing_anywhere_else_is_not_offered(self) -> None:
        self.assertEqual(self.put("/api/other", self.valid)[0], 404)
        self.assertEqual(self.put("/index.html", self.valid)[0], 404)

    def test_no_scratch_file_is_left_behind(self) -> None:
        self.put("/api/playlists", self.valid)
        self.assertEqual([p.name for p in (self.root / "data").iterdir()], ["playlists.json"])


if __name__ == "__main__":
    unittest.main()
