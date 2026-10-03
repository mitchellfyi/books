"""The production image's nginx server sends the site's HSTS header."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "nginx" / "default.conf"


class NginxConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = CONFIG.read_text()

    def test_sends_hsts_on_every_response_without_preload(self) -> None:
        headers = re.findall(r'add_header\s+Strict-Transport-Security\s+"([^"]+)"\s+always;', self.config)
        self.assertEqual(["max-age=63072000; includeSubDomains"], headers)
        self.assertNotIn("preload", headers[0])

    def test_no_location_replaces_the_server_headers(self) -> None:
        for block in re.findall(r"location[^{]*\{([^}]*)\}", self.config):
            self.assertNotIn("add_header", block)

    def test_the_image_installs_this_config(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("COPY nginx/default.conf /etc/nginx/conf.d/default.conf", dockerfile)


if __name__ == "__main__":
    unittest.main()
