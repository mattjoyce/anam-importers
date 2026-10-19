"""Config keys override opinionated defaults (anam card 151): a bad value fails the
command at start, naming the key, before any source is read or Anam called."""

import tempfile
import unittest
from pathlib import Path

from anam_importer import config as cfg
from anam_importer import ductile
from tests.helpers import REPO, run_plugin


class HelperTest(unittest.TestCase):
    def test_a_key_left_out_is_the_default(self):
        self.assertEqual(cfg.integer({}, "n", 5, 0, 10), 5)
        self.assertEqual(cfg.number({}, "x", 2.5, 0, 10), 2.5)
        self.assertEqual(cfg.text({}, "t", "d"), "d")
        self.assertEqual(cfg.url({}, "u", "https://example.test"), "https://example.test")

    def test_a_key_set_overrides_the_default(self):
        self.assertEqual(cfg.integer({"n": 7}, "n", 5, 0, 10), 7)
        self.assertEqual(cfg.integer({"n": "7"}, "n", 5, 0, 10), 7)
        self.assertEqual(cfg.integer({"n": 7.0}, "n", 5, 0, 10), 7)
        self.assertEqual(cfg.number({"x": 0.5}, "x", 2.5, 0, 10, low_open=True), 0.5)
        self.assertEqual(cfg.number({"x": "3"}, "x", 2.5, 0, 10), 3.0)
        self.assertEqual(cfg.text({"t": "other"}, "t", "d"), "other")
        self.assertEqual(cfg.url({"u": "http://host:8080/base"}, "u", "https://example.test"), "http://host:8080/base")

    def test_a_bad_value_is_refused_naming_the_key(self):
        cases = [
            ("integer below range", lambda: cfg.integer({"n": -1}, "n", 5, 0, 10)),
            ("integer above range", lambda: cfg.integer({"n": 11}, "n", 5, 0, 10)),
            ("integer with a fraction", lambda: cfg.integer({"n": 1.5}, "n", 5, 0, 10)),
            ("integer as a bool", lambda: cfg.integer({"n": True}, "n", 5, 0, 10)),
            ("integer as words", lambda: cfg.integer({"n": "lots"}, "n", 5, 0, 10)),
            ("number at an open low", lambda: cfg.number({"n": 0}, "n", 5, 0, 10, low_open=True)),
            ("number above range", lambda: cfg.number({"n": 10.5}, "n", 5, 0, 10)),
            ("number not a number", lambda: cfg.number({"n": "nan"}, "n", 5, 0, 10)),
            ("number as null", lambda: cfg.number({"n": None}, "n", 5, 0, 10)),
            ("text empty", lambda: cfg.text({"n": ""}, "n", "d")),
            ("text not text", lambda: cfg.text({"n": 3}, "n", "d")),
            ("url not http", lambda: cfg.url({"n": "ftp://host"}, "n", "https://example.test")),
            ("url with credentials", lambda: cfg.url({"n": "https://u:p@host"}, "n", "https://example.test")),
        ]
        for name, call in cases:
            with self.subTest(name):
                with self.assertRaises(ductile.Failure) as ctx:
                    call()
                self.assertFalse(ctx.exception.retry)
                self.assertIn("config n:", str(ctx.exception))


class AbsentIdsShownTest(unittest.TestCase):
    def test_the_alert_carries_as_many_ids_as_it_is_given(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("anam_submit_run", REPO / "anam_submit" / "run.py")
        submit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(submit)
        report = {"absent": 30, "live": 40, "absent_ids": [f"f{i}" for i in range(30)]}
        snapshot = {"id": "run-1", "types": ["a.b"]}
        for shown, want in ((submit.ABSENT_IDS_SHOWN, 20), (0, 0), (25, 25), (1000, 30)):
            with self.subTest(shown=shown):
                ev = submit.absent_event(snapshot, report, shown)
                self.assertEqual(len(ev["payload"]["absent_ids"]), want)


class PluginsTest(unittest.TestCase):
    """Each plugin checks its keys first: the source paths here do not exist, so an
    error naming the key, not the path, shows the check ran at start."""

    def test_every_plugin_refuses_a_bad_value_at_start(self):
        with tempfile.TemporaryDirectory() as d:
            missing = str(Path(d) / "missing")
            cases = [
                ("anam_submit", "health", {"anam_url": "http://127.0.0.1:9", "token_secret": "t", "timeout": 0},
                 "timeout"),
                ("anam_submit", "health", {"anam_url": "http://127.0.0.1:9", "token_secret": "t",
                                           "max_response_bytes": 0}, "max_response_bytes"),
                ("anam_submit", "health", {"anam_url": "http://127.0.0.1:9", "token_secret": "t",
                                           "absent_ids_shown": 1001}, "absent_ids_shown"),
                ("withings", "poll", {"db_path": missing, "person_id": "p", "busy_timeout_ms": -1}, "busy_timeout_ms"),
                ("bp_csv", "poll", {"export_dir": missing, "person_id": "p", "pattern": ""}, "pattern"),
                ("garmin", "poll", {"fit_dir": missing, "activities_dir": missing, "garmin_db": missing,
                                    "person_id": "p", "busy_timeout_ms": "soon"}, "busy_timeout_ms"),
                ("garmin", "handle", {"fit_dir": missing, "activities_dir": missing, "garmin_db": missing,
                                      "person_id": "p", "lookback_days": 0}, "lookback_days"),
                ("concept2", "poll", {"cache_dir": missing, "person_id": "p", "token_secret": "t",
                                      "logbook_url": "log.concept2.com"}, "logbook_url"),
                ("concept2", "handle", {"cache_dir": missing, "person_id": "p", "token_secret": "t",
                                        "lookback_days": -3}, "lookback_days"),
                ("owntracks", "health", {"spool_dir": missing, "person_id": "p", "max_payload_bytes": 0},
                 "max_payload_bytes"),
                ("links", "poll", {"links_dir": missing, "root_name": "r", "person_id": "p", "identity": "path",
                                   "zone": "UTC", "state_file": missing + ".json", "unseen_after": 0}, "unseen_after"),
                ("links", "health", {"links_dir": missing, "root_name": "r", "person_id": "p", "identity": "path",
                                     "zone": "Nowhere/Here", "state_file": missing + ".json"}, "zone"),
            ]
            for plugin, command, config, key in cases:
                with self.subTest(f"{plugin} {key}"):
                    r = run_plugin(REPO / plugin / "run.py", {"command": command, "config": config, "secrets": {"t": "x"}})
                    self.assertEqual(r["status"], "error", r)
                    self.assertFalse(r["retry"])
                    self.assertIn(f"config {key}:", r["error"])


if __name__ == "__main__":
    unittest.main()
