"""No AI warnings for an unconfigured lab; explicit target choices are still checked."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from bromigos_homelab import doctor


class TargetChecks(unittest.TestCase):
    def test_unconfigured_targets_are_skipped_without_a_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.toml"
            path.write_text("[targets]\n")
            with mock.patch.dict(os.environ, BROMIGOS_TARGETS_CONFIG=str(path)), \
                    mock.patch.object(doctor.caps, "available", return_value=False), \
                    mock.patch.object(doctor.subprocess, "run") as run:
                findings = list(doctor.targets())
                self.assertEqual([f["status"] for f in findings], ["skip"])
                run.assert_not_called()

    def test_personal_order_is_checked_even_without_lab_ai(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.toml"
            path.write_text('[targets]\norder = ["local"]\n')
            result = mock.Mock(stdout=json.dumps({"services": [{"service": "llm", "entries": [], "uses": {}}]}))
            with mock.patch.dict(os.environ, BROMIGOS_TARGETS_CONFIG=str(path)), \
                    mock.patch.object(doctor.caps, "available", return_value=False), \
                    mock.patch.object(doctor.shutil, "which", return_value="/usr/bin/bromigos"), \
                    mock.patch.object(doctor.os.path, "exists", return_value=True), \
                    mock.patch.object(doctor.subprocess, "run", return_value=result) as run:
                findings = list(doctor.targets())
                self.assertEqual([f["status"] for f in findings], ["warn"])
                run.assert_called_once()
