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
            "NEXT_PUBLIC_CONTROL_PROJECT_ID": "project-id",
            "SENTRY_AUTH_TOKEN": "never-include-me",
        })
        self.assertIn("https://errors.m12n.org/static/control-errors.v1.js", script)
        self.assertNotIn("ops-errors", script)
        self.assertIn('data-project="project-id"', script)
        self.assertIn("release&quot;&lt;unsafe&gt;", script)
        self.assertNotIn("never-include-me", script)

    def test_the_old_project_id_variable_still_works_and_the_new_one_wins(self):
        dsn = "https://public@errors.m12n.org/14"
        old_only = bookflow.error_tracking_script({
            "NEXT_PUBLIC_SENTRY_DSN": dsn, "NEXT_PUBLIC_OPS_PROJECT_ID": "old-id"})
        self.assertIn('data-project="old-id"', old_only)
        both = bookflow.error_tracking_script({
            "NEXT_PUBLIC_SENTRY_DSN": dsn, "NEXT_PUBLIC_OPS_PROJECT_ID": "old-id",
            "NEXT_PUBLIC_CONTROL_PROJECT_ID": "new-id"})
        self.assertIn('data-project="new-id"', both)
        self.assertNotIn("old-id", both)

    def test_rejects_non_control_endpoints_and_passwords(self):
        for dsn in ["http://public@errors.m12n.org/14", "https://public@evil.test/14", "https://public:password@errors.m12n.org/14"]:
            with self.assertRaises(ValueError):
                bookflow.error_tracking_script({"NEXT_PUBLIC_SENTRY_DSN": dsn})
