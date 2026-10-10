"""The console's Storage card (cards.py): each NAS share the lab mounts, named by its NAS,
with its free space; the NAS adapter's pools and shares carry the NAS's label. No network."""
import os
import unittest
from unittest import mock

os.environ.setdefault("BROMIGOS_HOMELAB_CONFIG", "/nonexistent")

from bromigos_homelab import caps, cards  # noqa: E402
from bromigos_homelab.adapters import labcommon as L, labstorage  # noqa: E402

TIB = 2 ** 40


def res(items):
    return {"ok": True, "items": items, "errors": {}, "sources": ["x"]}


class StorageCardTest(unittest.TestCase):
    def test_share_of(self):
        self.assertEqual(cards.share_of("nas.lab.example:/volume/media"), ("nas.lab.example", "/volume/media"))
        self.assertEqual(cards.share_of("//nas.lab.example/backups"), ("nas.lab.example", "/backups"))
        self.assertEqual(cards.share_of("/dev/sda1"), (None, "/dev/sda1"))

    def test_shares_name_their_nas_and_free_space(self):
        lb = {"instance": "box:9100", "fstype": "nfs4", "device": "nas.lab.example:/volume/media",
              "mountpoint": "/mnt/media"}
        sb = {"instance": "box:9100", "fstype": "cifs", "device": "//nas.lab.example/backups", "mountpoint": "/mnt/b"}

        def metrics(q, timeout=6):
            if q.startswith("node_filesystem_size_bytes"):
                return res([{"labels": lb, "value": 10 * TIB}, {"labels": sb, "value": 4 * TIB}])
            return res([{"labels": lb, "value": 1 * TIB}, {"labels": sb, "value": 3 * TIB}])
        pool = {"name": "pool1", "kind": "pool", "used": 6 * TIB, "total": 8 * TIB, "used_pct": 75.0, "nas": "Media NAS"}
        with mock.patch.object(caps, "available", return_value=True), \
                mock.patch.object(caps, "metrics", side_effect=metrics), \
                mock.patch.object(caps, "collect", return_value=res([pool])), \
                mock.patch.object(caps, "hosts", return_value=res([{"name": "box", "disk_pct": 40.0}])):
            card = cards._storage(None)
        by = {i["name"]: i for i in card["items"]}
        self.assertEqual(card["columns"], ["name", "kind", "nas", "free_h", "used_pct"])
        media = by["/volume/media"]
        self.assertEqual((media["kind"], media["nas"], media["free_h"], media["state"]), ("NFS share", "nas.lab.example", "1.0 TiB", "warn"))
        self.assertIn("on the NAS nas.lab.example", media["hint"])
        self.assertIn("1.0 TiB free of 10.0 TiB", media["hint"])
        self.assertEqual(by["/backups"]["kind"], "SMB share")
        self.assertEqual((by["pool1"]["nas"], by["pool1"]["free_h"]), ("Media NAS", "2.0 TiB"))
        self.assertEqual(by["box"]["kind"], "root disk")
        self.assertIn("NAS: Media NAS, nas.lab.example", card["summary"])
        self.assertTrue(card["summary"].startswith("fullest: /volume/media 90%"))

    def test_nas_adapter_labels_its_records(self):
        rows = {"nas_pool_total_bytes": [{"labels": {"pool": "pool1"}, "value": 8 * TIB}],
                "nas_pool_used_bytes": [{"labels": {"pool": "pool1"}, "value": 6 * TIB}],
                "nas_share_usage_bytes": [{"labels": {"share": "media"}, "value": 2 * TIB}],
                "nas_share_quota_bytes": [{"labels": {"share": "media"}, "value": 4 * TIB}]}
        a = labstorage.NAS({"name": "nas", "type": "nas", "label": "Media NAS", "volume_classes": ["none"]})
        with mock.patch.object(L, "mq", return_value=[]), \
                mock.patch.object(L, "mq_soft", side_effect=lambda q, timeout=6: rows.get(q, [])):
            recs = a.storage()
        by = {r["name"]: r for r in recs}
        self.assertEqual((by["pool1"]["nas"], by["pool1"]["free"]), ("Media NAS", 2 * TIB))
        self.assertEqual((by["media"]["nas"], by["media"]["free"]), ("Media NAS", 2 * TIB))


if __name__ == "__main__":
    unittest.main()
