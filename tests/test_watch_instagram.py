#!/usr/bin/env python3
"""Logic tests for the Instagram feed watch. No network."""

import io
import json
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import watch_instagram as watch


TODAY = date(2026, 11, 15)


def festival(fid, start, end, url="https://instagram.com/seismicdanceevent"):
    return {
        "id": fid,
        "name": fid,
        "startDate": start,
        "endDate": end,
        "instagramUrl": url,
    }


class UsernameTests(unittest.TestCase):
    def test_profile_urls(self):
        self.assertEqual(watch.instagram_username("https://instagram.com/aclfestival"), "aclfestival")
        self.assertEqual(
            watch.instagram_username("https://www.instagram.com/EDC_LasVegas/"),
            "EDC_LasVegas",
        )
        self.assertEqual(
            watch.instagram_username("https://instagram.com/dreamstateusa?hl=en"),
            "dreamstateusa",
        )

    def test_rejects_posts_and_empty(self):
        self.assertIsNone(watch.instagram_username("https://instagram.com/p/abc123"))
        self.assertIsNone(watch.instagram_username("https://instagram.com/reel/abc"))
        self.assertIsNone(watch.instagram_username(""))
        self.assertIsNone(watch.instagram_username(None))
        self.assertIsNone(watch.instagram_username("https://example.com/aclfestival"))


class WindowTests(unittest.TestCase):
    def test_includes_the_night_before_through_the_last_day(self):
        on = festival("on", "2026-11-16", "2026-11-18")
        during = festival("during", "2026-11-13", "2026-11-15")
        after = festival("after", "2026-11-01", "2026-11-14")
        later = festival("later", "2026-11-20", "2026-11-22")
        self.assertTrue(watch.on_watch(on, TODAY))
        self.assertTrue(watch.on_watch(during, TODAY))
        self.assertFalse(watch.on_watch(after, TODAY))
        self.assertFalse(watch.on_watch(later, TODAY))

    def test_missing_instagram_is_reported_not_queried(self):
        due = watch.festivals_due(
            [festival("bare", "2026-11-15", "2026-11-15", url=None)],
            TODAY,
        )
        self.assertEqual(due[0]["username"], None)


class ReportTests(unittest.TestCase):
    def test_parses_posts_and_drops_a_token_from_errors(self):
        body = json.dumps(
            {
                "business_discovery": {
                    "username": "seismicdanceevent",
                    "media": {
                        "data": [
                            {
                                "caption": "Sunday is cancelled",
                                "permalink": "https://www.instagram.com/p/abc/",
                                "timestamp": "2026-11-15T18:00:00+0000",
                                "media_type": "IMAGE",
                            }
                        ]
                    },
                }
            }
        ).encode()

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def opener(request, timeout):
            self.assertIn("business_discovery.username", request.full_url)
            self.assertIn("seismicdanceevent", request.full_url)
            self.assertIn("access_token=secret-token", request.full_url)
            return Response(body)

        found = watch.fetch_discovery("1789", "seismicdanceevent", "secret-token", opener)
        self.assertEqual(found["posts"][0]["permalink"], "https://www.instagram.com/p/abc/")

        def failing(request, timeout):
            raise watch.urllib.error.HTTPError(
                request.full_url, 400, "bad", {}, io.BytesIO(b'{"error":{"message":"no"}} access_token=secret-token')
            )

        with self.assertRaises(watch.WatchError) as caught:
            watch.fetch_discovery("1789", "seismicdanceevent", "secret-token", failing)
        self.assertNotIn("secret-token", str(caught.exception))
        self.assertIn("[redacted]", str(caught.exception))

    def test_one_query_per_shared_account_and_a_missing_token_fails_closed(self):
        calls = []

        def opener(request, timeout):
            calls.append(request.full_url)
            raise AssertionError("should not be called without a token")

        festivals = [
            festival("a", "2026-11-15", "2026-11-15", "https://instagram.com/same"),
            festival("b", "2026-11-15", "2026-11-15", "https://instagram.com/same"),
            festival("later", "2026-12-01", "2026-12-02", "https://instagram.com/other"),
        ]
        report = watch.build_report(festivals, TODAY, None, "1789", opener)
        self.assertEqual(calls, [])
        self.assertEqual(report["failed"], ["a", "b"])
        self.assertIn("no token", report["festivals"][0]["error"])
        self.assertNotIn("later", [row["id"] for row in report["festivals"]])

    def test_graph_error_is_the_message(self):
        with self.assertRaises(watch.WatchError) as caught:
            watch.parse_discovery(b'{"error":{"message":"(#10) permission denied"}}')
        self.assertIn("permission denied", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
