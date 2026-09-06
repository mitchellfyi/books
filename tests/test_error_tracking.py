"""Public ingestion configuration must not expose administrative credentials."""

import unittest
from fixtures import bookflow


class ErrorTrackingTests(unittest.TestCase):
    def test_disabled_without_a_dsn(self):
        self.assertEqual("", bookflow.error_tracking_script({}))

    def test_uses_only_public_configuration_and_escapes_attributes(self):
        script = bookflow.error_tracking_script({
            "NEXT_PUBLIC_SENTRY_DSN": "https://public@errors.m12n.org/14",
            "NEXT_PUBLIC_SENTRY_RELEASE": 'release"<unsafe>',
            "NEXT_PUBLIC_OPS_PROJECT_ID": "project-id",
            "SENTRY_AUTH_TOKEN": "never-include-me",
        })
        self.assertIn("https://errors.m12n.org/static/ops-errors.v1.js", script)
        self.assertIn('data-project="project-id"', script)
        self.assertIn("release&quot;&lt;unsafe&gt;", script)
        self.assertNotIn("never-include-me", script)

    def test_rejects_non_ops_endpoints_and_passwords(self):
        for dsn in ["http://public@errors.m12n.org/14", "https://public@evil.test/14", "https://public:password@errors.m12n.org/14"]:
            with self.assertRaises(ValueError):
                bookflow.error_tracking_script({"NEXT_PUBLIC_SENTRY_DSN": dsn})
