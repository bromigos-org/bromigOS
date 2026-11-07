"""`make-stick --answers` and `--image` (stick.py): an answer file goes on the stick under its
edition's name, and the stick can be written to an image file as you, with no drive and no
root: the medium kept byte for byte, a FIELDKIT partition after it, the settings in it."""
import argparse
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from bromigos_fieldkit import stick

TOOLS = all(shutil.which(t) for t in ("sfdisk", "mkfs.fat", "mcopy", "mtype", "blkid"))
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyForTheStickTestsOnly tester@lab"
SERVER = '[install]\nedition = "server"\ndisk_model = "Samsung*990*PRO*"\nuser = "admin"\npassword = "x"\n'


def args(tmp, **kw):
    key = os.path.join(tmp, "id.pub")
    with open(key, "w") as f:
        f.write(KEY + "\n")
    a = argparse.Namespace(ssh_key=[key], wifi=[], lab=os.path.join(tmp, "no-lab.toml"), remote=False,
                           answers=None, image=None, iso=None)
    for k, v in kw.items():
        setattr(a, k, v)
    return a


class Answers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fk-stick-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, text):
        path = os.path.join(self.tmp, "answers.toml")
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_goes_in_under_its_editions_name(self):
        out = os.path.join(self.tmp, "fieldkit")
        os.makedirs(out)
        stick.gather(args(self.tmp, answers=self.write(SERVER)), out)
        with open(os.path.join(out, "install-server.toml")) as f:
            self.assertEqual(f.read(), SERVER)
        self.assertEqual(os.stat(os.path.join(out, "install-server.toml")).st_mode & 0o777, 0o600)
        self.assertFalse(os.path.exists(os.path.join(out, "install-desktop.toml")))

    def test_no_edition_is_the_desktop(self):
        out = os.path.join(self.tmp, "fieldkit")
        os.makedirs(out)
        stick.gather(args(self.tmp, answers=self.write('[install]\nuser = "alex"\n')), out)
        self.assertTrue(os.path.exists(os.path.join(out, "install-desktop.toml")))

    def test_a_bad_file_stops_it_in_plain_words(self):
        with self.assertRaises(SystemExit) as e:
            stick.answer_file(self.write('[install]\nedition = "fieldkit"\n'))
        self.assertIn('"server" or "desktop"', str(e.exception))
        with self.assertRaises(SystemExit):
            stick.answer_file(self.write("[install\n"))


@unittest.skipUnless(TOOLS, "needs sfdisk, mkfs.fat, mtools and blkid")
class Image(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fk-image-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # a stand-in medium: an MBR with the ISO's two partitions (the data, then the EFI image)
        self.iso = os.path.join(self.tmp, "bromigos-fieldkit-0.0.0-x86_64.iso")
        with open(self.iso, "wb") as f:
            f.write(os.urandom(1 << 20) * 8)
        subprocess.run(["sfdisk", "-q", self.iso], input="64,10000,0,*\n10064,4000,ef\n", text=True, check=True)
        with open(self.iso, "rb") as f:
            self.medium = f.read()

    def make(self):
        out = os.path.join(self.tmp, "stick.img")
        answers = os.path.join(self.tmp, "a.toml")
        with open(answers, "w") as f:
            f.write(SERVER)
        rc = stick.make_image(args(self.tmp, iso=self.iso, image=out, answers=answers))
        self.assertEqual(rc, 0)
        return out

    def test_the_medium_then_a_fieldkit_partition_with_the_settings(self):
        out = self.make()
        with open(out, "rb") as f:
            data = f.read()
        # the medium is unchanged except its partition table's new entry (bytes 446-509)
        self.assertEqual(data[:446], self.medium[:446])
        self.assertEqual(data[512:len(self.medium)], self.medium[512:])
        parts = json.loads(subprocess.run(["sfdisk", "-J", out], capture_output=True, text=True, check=True).stdout)
        parts = parts["partitiontable"]["partitions"]
        self.assertEqual(len(parts), 3)
        last = parts[-1]
        self.assertEqual(last["type"], "c")
        self.assertGreaterEqual(last["start"] * 512, len(self.medium))
        self.assertEqual(last["size"] * 512, stick.SETTINGS_MIB << 20)
        self.assertGreaterEqual(os.path.getsize(out), (last["start"] + last["size"]) * 512)
        at = f"{out}@@{last['start'] * 512}"
        label = subprocess.run(["blkid", "-p", "-O", str(last["start"] * 512), "-o", "value", "-s", "LABEL", out],
                               capture_output=True, text=True).stdout.strip()
        self.assertEqual(label, "FIELDKIT")
        got = subprocess.run(["mtype", "-i", at, "::/fieldkit/install-server.toml"], capture_output=True, text=True, check=True)
        self.assertEqual(got.stdout, SERVER)
        cfg = subprocess.run(["mtype", "-i", at, "::/fieldkit/config.toml"], capture_output=True, text=True, check=True)
        self.assertIn(KEY, cfg.stdout)
        # nothing left beside it
        self.assertEqual(sorted(os.listdir(self.tmp)), sorted(["a.toml", "bromigos-fieldkit-0.0.0-x86_64.iso", "id.pub", "stick.img"]))

    def test_again_over_the_same_file(self):
        self.make()
        out = self.make()
        parts = json.loads(subprocess.run(["sfdisk", "-J", out], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(len(parts["partitiontable"]["partitions"]), 3)


if __name__ == "__main__":
    unittest.main()
