import json
from types import SimpleNamespace
import unittest
from bromigos_homelab import k3sbootstrap as B


class BootstrapTests(unittest.TestCase):
    def run_case(self, pending=False, accepted=True, settle=True):
        ticks = [0]
        calls = []
        def sleep(seconds): ticks[0] += seconds
        def run(argv, **kwargs):
            calls.append(argv)
            if 'annotate' in argv:
                return SimpleNamespace(returncode=0, stdout='')
            ready = not pending or (settle and any('annotate' in c for c in calls))
            rows = [{'metadata': {'name': name}, 'status': {'conditions': [{'type': 'NamesAccepted', 'status': 'True' if accepted else 'False'}, {'type': 'Established', 'status': 'True' if ready else 'False'}]}} for name in B.NAMES]
            return SimpleNamespace(returncode=0, stdout=json.dumps({'items': rows}))
        changed = B.reconcile(run=run, clock=lambda: ticks[0], sleep=sleep, timeout=40)
        return changed, calls, ticks[0]

    def test_ready_cluster_is_read_only(self):
        changed, calls, _ = self.run_case()
        self.assertFalse(changed)
        self.assertEqual(len(calls), 1)

    def test_stalled_bootstrap_requests_reconciliation_after_wait(self):
        changed, calls, elapsed = self.run_case(pending=True)
        self.assertTrue(changed)
        self.assertGreaterEqual(elapsed, 30)
        updates = [c for c in calls if 'annotate' in c]
        self.assertEqual(len(updates), len(B.NAMES))
        self.assertTrue(all(c[3] == 'crd' and c[4] in B.NAMES for c in updates))
        self.assertFalse(any('delete' in c or 'patch' in c for c in calls))

    def test_failed_names_or_readiness_do_not_fake_success(self):
        for accepted in (True, False):
            with self.assertRaisesRegex(RuntimeError, 'three minutes'):
                self.run_case(pending=True, accepted=accepted, settle=False)
