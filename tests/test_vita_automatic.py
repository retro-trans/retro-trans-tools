from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from retro_trans.vita_automatic import detect, append_packages, VitaAutomaticPlan
from retro_trans.core import Cancelled, GitHubClient
from test_vita_downloads import pkg_bytes


class VitaAutomaticTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_header_detection_without_network_or_registry(self):
        for title in ('PCSG00597','PCSE12345'):
            path = self.root/'renamed.file'
            path.write_bytes(pkg_bytes('JP0700-'+title+'_00-ABCDEFGHIJKLMNOP'))
            with patch.object(GitHubClient,'json') as network:
                package = detect(path)
            network.assert_not_called()
            self.assertEqual(package.title_id,title)
            self.assertIn('latest compatible',VitaAutomaticPlan(package).summary)

    def test_ps3_and_unsupported_packages_stay_on_other_routes(self):
        path = self.root/'game.pkg'
        for raw in (b'ordinary binary',pkg_bytes('JP0700-NPJB00689_00-ABCDEFGHIJKLMNOP')):
            path.write_bytes(raw); self.assertIsNone(detect(path))
        self.assertIsNone(detect(self.root))

    def test_folder_scan_adds_vita_but_preserves_matches_and_deduplicates(self):
        path = self.root/'game.pkg';path.write_bytes(pkg_bytes('JP0700-PCSE12345_00-ABCDEFGHIJKLMNOP'))
        ordinary = (self.root/'game.iso','existing catalog match')
        rows = append_packages(self.root,[ordinary])
        self.assertEqual(rows[0],ordinary)
        self.assertEqual(rows[1][1].title_id,'PCSE12345')
        self.assertEqual(append_packages(self.root,rows),rows)
        cancel=threading.Event();cancel.set()
        with self.assertRaises(Cancelled):append_packages(self.root,[],cancel)
