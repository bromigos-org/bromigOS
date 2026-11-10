"""`bromigos activity answer`, `cancel` and `retry` on a stand-in machine (tests/activity/fake.py):
a stand-in "replace a drive" job that stops to ask "I've swapped the drive", waits, is answered
and carries on; two jobs on one lock that queue; a cancel refused while the job says stopping
isn't safe; a job started again; a parent and its child; and the alert a failed job raises
through `bromigos alerts`. No root, no real systemd unit, nothing on this machine read or changed."""
import json
import os
import signal
import stat
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fake  # noqa: E402
from fake import NOW  # noqa: E402
from test_activity import DAY, RECORD_KEYS, Machine  # noqa: E402

import bromigos_activity as A  # noqa: E402

ASKS = "Take the old drive out of bay 2 and put the new one in."
UNSAFE = "The new drive is being filled. Stopping now would leave your files with one copy."
TITLE = "Replacing the drive in bay 2"

# the stand-in for the replace-a-drive flow (docs/activity.md, "Ask a question"): it is safe to
# stop until the swap is done, asks for the swap, and must not be stopped while it rebuilds
REPLACE = f'''echo "::cancel safe"
echo "::step ready running Getting the pool ready to lose the drive"
echo "::step ready done"
echo "::step swap running Swapping the drive"
echo "::ask swapped {ASKS} [swapped] I've swapped the drive"
read -r answer < "$BROMIGOS_ACTIVITY_ANSWERS"
echo "the answer was: $answer"
[ "$answer" = swapped ] || exit 1
echo "::cancel unsafe {UNSAFE}"
echo "::step swap done"
echo "::step rebuild running Copying your files onto the new drive"
while [ ! -e "$GATE" ]; do sleep 0.02; done
echo "::step rebuild done"
echo "::stage 100 The new drive is in"
'''
HOLD = 'echo "::step work running Working"\nwhile [ ! -e "$GATE" ]; do sleep 0.02; done\necho "::stage 100 Finished"\n'


class Control(Machine):
    def setUp(self):
        super().setUp()
        self.gate = self.m.tmp / "go"
        self.m.environ["GATE"] = str(self.gate)

    def start(self, body, *args, name="job", kind="drive.replace", title=TITLE):
        """`bromigos activity run` in the background, watched as a person would."""
        p = self.m.popen("run", "--kind", kind, "--title", title, *args, "--", self.m.script(body, name))
        self.addCleanup(lambda: (p.poll() is None and p.kill(), p.wait(), p.stdout.close(), p.stderr.close()))
        return p

    def rec(self, title, want=None, timeout=20):
        """The record of a job with this title, once want(record) holds for one (or its state is want)."""
        test = want if callable(want) else (lambda r: want is None or r["state"] == want)

        def look():
            if not self.m.jobs.is_dir():
                return None
            return next((r for r in self.m.on_disk().values() if r["title"] == title and test(r)), None)
        return self.m.wait(look, timeout, f"{title!r} never got to {want if not callable(want) else 'that'}")

    def files(self, job_id):
        return sorted(p.name[len(job_id):] for p in self.m.jobs.iterdir() if p.name.startswith(job_id))


class TheLines(Machine):
    def test_a_question_and_its_choices(self):
        self.assertEqual(A.parse(f"::ask swapped {ASKS} [swapped] I've swapped the drive [wipe!] Wipe it first"),
                         {"kind": "ask", "id": "swapped", "words": ASKS, "choices": [
                             {"id": "swapped", "label": "I've swapped the drive", "danger": False},
                             {"id": "wipe", "label": "Wipe it first", "danger": True}]})
        # with no choices it is a yes or no; a choice with no words is called by its id; one id counts once
        self.assertEqual([c["id"] for c in A.parse("::ask replace Replace the drive in bay 2?")["choices"]], ["yes", "no"])
        self.assertEqual(A.parse("::ask go Ready? [go] [go] Again [later]")["choices"],
                         [{"id": "go", "label": "go", "danger": False}, {"id": "later", "label": "later", "danger": False}])
        many = A.parse("::ask n Which? " + " ".join(f"[c{k}] Choice {k}" for k in range(30)))
        self.assertEqual(len(many["choices"]), A.MAX_CHOICES)
        for odd in ("::ask", "::ask lonely", "::ask Shouting Is this an id?", "::ask swapped [swapped] No question"):
            self.assertIsNone(A.parse(odd), odd)

    def test_whether_stopping_is_safe(self):
        self.assertEqual(A.parse("::cancel safe"), {"kind": "cancel", "safe": True, "words": ""})
        self.assertEqual(A.parse(f"::cancel unsafe {UNSAFE}"), {"kind": "cancel", "safe": False, "words": UNSAFE})
        for odd in ("::cancel", "::cancel maybe", "::cancel Safe"):
            self.assertIsNone(A.parse(odd), odd)

    def test_what_a_job_says_reads_back(self):
        line = A.line_ask("swapped", ASKS, [("swapped", "I've swapped the drive"), ("wipe", "Wipe it\nfirst", True),
                                            {"id": "later"}])
        self.assertEqual(A.parse(line)["choices"], [{"id": "swapped", "label": "I've swapped the drive", "danger": False},
                                                    {"id": "wipe", "label": "Wipe it first", "danger": True},
                                                    {"id": "later", "label": "later", "danger": False}])
        self.assertEqual(A.parse(A.line_ask("go", "Ready?"))["words"], "Ready?")
        self.assertEqual(A.parse(A.line_cancel(False, "Half\nway")), {"kind": "cancel", "safe": False, "words": "Half way"})
        self.assertEqual(A.line_cancel(True), "::cancel safe")


class Questions(Control):
    def test_a_replace_job_asks_waits_is_answered_and_carries_on(self):
        p = self.start(REPLACE, "--subject", "drive:bay-2:Bay 2", "--lock", "pool")
        rec = self.rec(TITLE, "needs-you")
        job_id = rec["id"]
        self.assertEqual(set(rec), RECORD_KEYS)                                   # the fields #104 shipped, and no other
        self.assertEqual((rec["waiting_for"], rec["can"], rec["cancel_safe"], rec["locks"]), ("you", ["answer", "cancel"], True, ["pool"]))
        self.assertEqual(rec["question"], {"id": "swapped", "text": ASKS, "asked_at": rec["question"]["asked_at"],
                                           "choices": [{"id": "swapped", "label": "I've swapped the drive", "danger": False}]})
        self.assertIsInstance(rec["question"]["asked_at"], int)
        self.assertEqual([(s["id"], s["state"]) for s in rec["steps"]], [("ready", "done"), ("swap", "running")])
        # for people: the list says a job needs them, show says what it asks and what to type
        code, out, _ = self.m.cli()
        self.assertRegex(out, rf"(?m)^needs you +just now +{job_id} +{TITLE}: it asks: {ASKS}$")
        self.assertIn(f"A job needs you. Its question and how to answer: bromigos activity show {job_id}", out)
        code, out, _ = self.m.cli("show", job_id)
        self.assertIn(f"It asks\n  {ASKS}\n    swapped  I've swapped the drive\n"
                      f"  Answer with: sudo bromigos activity answer {job_id} swapped\n", out)
        self.assertIn(f"Stopping it now is safe: sudo bromigos activity cancel {job_id}", out)
        self.assertIn("Locks    pool", out)
        # it waits: for as long as nobody answers, nothing moves
        time.sleep(0.6)
        self.assertEqual(self.m.on_disk()[job_id]["state"], "needs-you")
        self.assertIsNone(p.poll())
        # an answer it doesn't have is refused, and changes nothing
        code, out, err = self.m.cli("answer", job_id, "yes")
        self.assertEqual((code, out), (3, ""))
        self.assertIn("'yes' isn't one of its answers: swapped.", err)
        self.assertEqual(self.m.on_disk()[job_id]["question"], rec["question"])
        # the answer: the job carries on, with what was answered in its record
        code, out, err = self.m.cli("answer", job_id, "swapped")
        self.assertEqual((code, out, err), (0, "Answered: I've swapped the drive\n", ""))
        rec = self.rec(TITLE, lambda r: r["state"] == "running" and r["cancel_note"])
        self.assertEqual((rec["question"], rec["waiting_for"], rec["can"]), (None, None, []))
        self.assertEqual([(n["id"], n["words"]) for n in rec["notes"]], [("swapped", "Answered: I've swapped the drive")])
        self.assertEqual([(s["id"], s["state"]) for s in rec["steps"]][1:], [("swap", "done"), ("rebuild", "running")])
        # now it rebuilds, and says stopping isn't safe: cancel is refused, with its reason
        code, out, err = self.m.cli("cancel", job_id)
        self.assertEqual((code, out), (3, ""))
        self.assertIn(f"not stopped. {UNSAFE}", err)
        self.assertIn("To stop it anyway: press Ctrl+C in the terminal that runs it", err)
        self.assertIn(f"Stopping it now isn't safe. {UNSAFE}", self.m.cli("show", job_id)[1])
        self.assertEqual(self.m.on_disk()[job_id]["state"], "running")
        self.assertEqual(self.m.cli("answer", job_id, "swapped")[0], 3)           # it isn't asking any more
        self.gate.write_text("")
        self.assertEqual(p.wait(timeout=20), 0)
        rec = self.m.on_disk()[job_id]
        self.assertEqual((rec["state"], rec["result"]["summary"], rec["can"], rec["question"]),
                         ("succeeded", "The new drive is in", [], None))
        self.assertEqual([s["state"] for s in rec["steps"]], ["done", "done", "done"])
        self.assertIn("the answer was: swapped", Path(rec["log"]).read_text())    # the command got the choice
        watcher = p.stderr.read()
        self.assertIn(f"bromigos activity: it asks: {ASKS}", watcher)             # whoever watched was told what to type
        self.assertIn(f"sudo bromigos activity answer {job_id} swapped    (I've swapped the drive)", watcher)
        self.assertEqual(self.files(job_id), [".json", ".log"])                   # the pipe and the requests are gone
        code, _, err = self.m.cli("answer", job_id, "swapped")
        self.assertEqual(code, 3)
        self.assertIn("That job has ended (done), so there is nothing to answer.", err)

    def test_the_outcome_as_json(self):
        self.start(REPLACE)
        job_id = self.rec(TITLE, "needs-you")["id"]
        code, out, err = self.m.cli("answer", job_id, "nope", "--json")
        doc = json.loads(out)
        self.assertEqual((code, err, set(doc)), (3, "", {"schema", "ok", "refused", "words", "job"}))
        self.assertEqual((doc["schema"], doc["ok"], doc["refused"], doc["job"]["state"]), (1, False, "no-such-choice", "needs-you"))
        code, out, err = self.m.cli("answer", job_id, "swapped", "--json")
        doc = json.loads(out)
        self.assertEqual((code, doc["ok"], doc["refused"], doc["words"]), (0, True, None, "Answered: I've swapped the drive"))
        self.assertEqual(set(doc["job"]), RECORD_KEYS)
        self.rec(TITLE, lambda r: r["cancel_note"])
        code, out, err = self.m.cli("cancel", job_id, "--json")
        doc = json.loads(out)
        self.assertEqual((code, err, doc["ok"], doc["refused"], doc["words"]), (3, "", False, "unsafe", UNSAFE))
        code, out, err = self.m.cli("answer", job_id, "swapped", "--json")
        self.assertEqual((code, json.loads(out)["refused"]), (3, "not-asking"))
        for args in (["answer", job_id], ["answer"], ["cancel"], ["cancel", job_id, "now"], ["retry"], ["answer", job_id, "a", "--force"]):
            self.assertEqual(self.m.cli(*args)[0], 2, args)
        code, _, err = self.m.cli("answer", "no-such-job", "yes")
        self.assertEqual((code, "no job 'no-such-job'" in err), (1, True))

    def test_a_python_command_asks_through_the_library(self):
        body = (f"import sys; sys.path.insert(0, {str(fake.REPO / 'lib')!r}); import bromigos_activity as activity\n"
                "with activity.job('drive.replace', 'unused: the wrapper has the title') as j:\n"
                "    j.can_cancel(True)\n"
                "    j.step('swap', 'Swapping the drive')\n"
                f"    choice = j.ask('swapped', {ASKS!r}, [('swapped', \"I've swapped the drive\"), ('wipe', 'Wipe it first', True)])\n"
                "    j.can_cancel(False, 'Half way.')\n"
                "    j.note('picked ' + choice)\n")
        script = self.m.tmp / "replace.py"
        script.write_text(body)
        p = self.m.popen("run", "--kind", "drive.replace", "--title", TITLE, "--", sys.executable, str(script))
        self.addCleanup(lambda: (p.poll() is None and p.kill(), p.wait(), p.stdout.close(), p.stderr.close()))
        rec = self.rec(TITLE, "needs-you")
        self.assertEqual([(c["id"], c["danger"]) for c in rec["question"]["choices"]], [("swapped", False), ("wipe", True)])
        self.assertIn("wipe     Wipe it first  (this can't be undone)", self.m.cli("show", rec["id"])[1])
        self.assertEqual(self.m.cli("answer", rec["id"], "wipe")[0], 0)
        self.assertEqual(p.wait(timeout=20), 0, p.stderr.read())
        rec = self.m.on_disk()[rec["id"]]
        self.assertEqual((rec["state"], rec["cancel_safe"], rec["cancel_note"]), ("succeeded", False, "Half way."))
        self.assertEqual([n["words"] for n in rec["notes"]], ["Answered: Wipe it first", "picked wipe"])

    def test_a_python_command_that_keeps_its_own_record_asks_too(self):
        env, got = self.m.env(), {}

        def the_command():
            with A.job("backup.run", "Backing up", env=env) as j:
                got["choice"] = j.ask("usb", "Plug in the backup drive.", [("ready", "It's plugged in")])
                got["then"] = j.rec["state"]
        t = threading.Thread(target=the_command, daemon=True)
        t.start()
        rec = self.rec("Backing up", "needs-you")
        self.assertEqual(A.answer(env, rec["id"], "later")["refused"], "no-such-choice")
        out = A.answer(env, rec["id"], "ready", wait=5)
        t.join(20)
        self.assertFalse(t.is_alive())
        self.assertEqual((got["choice"], got["then"], out["ok"], out["words"]), ("ready", "running", True, "Answered: It's plugged in"))
        self.assertEqual(self.rec("Backing up", "succeeded")["id"], rec["id"])
        with self.assertRaises(A.ActivityError):                                 # outside a job nobody can answer
            A.Lines().ask("usb", "Plug in the backup drive.")

    def test_a_question_asked_while_it_waits_and_one_that_replaces_another(self):
        j = self.job()
        j.begin()
        j.feed("::item jellyfin waiting-for-network")
        self.assertEqual((j.rec["state"], j.rec["waiting_for"]), ("waiting", "network"))
        j.feed("::ask proxy Use the proxy? [yes] Use it [no] Go without")
        self.assertEqual((j.rec["state"], j.rec["waiting_for"], j.rec["question"]["id"]), ("needs-you", "you", "proxy"))
        j.feed("::item jellyfin installing")                                      # steps move; the job still needs someone
        self.assertEqual(j.rec["state"], "needs-you")
        j.feed("::ask sure Really without? [yes] Yes")
        first = dict(question="proxy", asked_at=j.rec["question"]["asked_at"], choice="no")
        self.assertEqual(j.rec["question"]["id"], "sure")
        self.assertIsNone(j.take_answer(first))                                   # an answer to the question before
        self.assertIsNone(j.take_answer(dict(first, question="sure", choice="maybe")))
        self.assertEqual(j.take_answer(dict(first, question="sure", choice="yes")), "yes")
        self.assertEqual((j.rec["state"], j.rec["question"], j.rec["can"]), ("running", None, []))
        j.feed("::ask last One more? [ok] OK")
        j.finish(1)                                                               # it ends while asking: nothing to answer
        rec = self.m.on_disk()[j.id]
        self.assertEqual((rec["state"], rec["question"], rec["waiting_for"], rec["can"]), ("failed", None, None, []))


class Locks(Control):
    def test_two_jobs_on_one_lock_queue(self):
        a = self.start(HOLD, "--lock", "pool", name="a", kind="pool.check", title="Checking the pool")
        first = self.rec("Checking the pool", lambda r: r["state"] == "running" and r["steps"])
        marker = self.m.tmp / "b-ran"
        b = self.start(f'echo ran > {marker}\necho "::stage 100 Replaced"\n', "--lock", "pool", name="b")
        second = self.rec(TITLE, "waiting")
        self.assertEqual((second["waiting_for"], second["locks"], second["can"], second["steps"]), ("another job", ["pool"], ["cancel"], []))
        self.assertEqual(second["stage"], "Waiting for another job to finish: Checking the pool")
        self.assertEqual((first["locks"], first["waiting_for"]), (["pool"], None))
        self.assertRegex(self.m.cli()[1], rf"(?m)^waiting +just now +{second['id']} +{TITLE}: Waiting for another job to finish: Checking the pool$")
        # a job on another lock doesn't wait
        code, _, err = self.m.cli("run", "--kind", "backup.run", "--title", "Backing up", "--lock", "backup-repo", "--", "true")
        self.assertEqual(code, 0, err)
        time.sleep(0.8)                                                           # more than one look at the lock
        self.assertFalse(marker.exists())                                         # its command hasn't started
        self.assertEqual(self.m.on_disk()[second["id"]]["state"], "waiting")
        self.gate.write_text("")
        self.assertEqual((a.wait(timeout=20), b.wait(timeout=20)), (0, 0))
        first, second = self.m.on_disk()[first["id"]], self.m.on_disk()[second["id"]]
        self.assertEqual((second["state"], second["waiting_for"], second["result"]["summary"]), ("succeeded", None, "Replaced"))
        self.assertGreaterEqual(marker.stat().st_mtime, first["ended_at"] / 1000 - 0.05)   # only once the first had ended
        self.assertIn("Waiting for another job to finish: Checking the pool", b.stderr.read())

    def test_those_who_wait_go_in_the_order_they_came(self):
        order = self.m.tmp / "order"
        a = self.start(HOLD, "--lock", "apps", "--lock", "pool", name="a", title="First")
        self.rec("First", lambda r: r["state"] == "running" and r["steps"])
        rest = []
        for name, locks in (("b", ["pool"]), ("c", ["apps", "pool"]), ("d", ["pool"])):
            args = [x for lock in locks for x in ("--lock", lock)]
            rest.append(self.start(f'echo {name} >> {order}\nsleep 0.3\n', *args, name=name, title=f"Job {name}"))
            self.rec(f"Job {name}", "waiting")
        self.gate.write_text("")
        self.assertEqual([p.wait(timeout=30) for p in [a] + rest], [0, 0, 0, 0])
        self.assertEqual(order.read_text().split(), ["b", "c", "d"])

    def test_a_job_that_came_later_does_not_jump_the_line(self):
        """The lock is free and the later job looks first: it still lets the earlier one go."""
        holder = self.job(kind="pool.check", title="Checking the pool", locks=["pool"])
        self.assertTrue(holder.try_locks())
        holder.begin()
        early = self.job(self.m.env(BROMIGOS_ACTIVITY_NOW_MS=NOW), title="Came first", locks=["pool", "apps"])
        late = self.job(self.m.env(BROMIGOS_ACTIVITY_NOW_MS=NOW + 1000), title="Came later", locks=["pool"])
        other = self.job(self.m.env(BROMIGOS_ACTIVITY_NOW_MS=NOW + 2000), title="Another matter", locks=["backup-repo"])
        for j in (early, late):
            self.assertFalse(j.try_locks())
            j.queue()
        self.assertTrue(other.try_locks())                                        # nobody is in line for its lock
        other.begin()
        holder.finish(0)
        self.assertFalse(late.try_locks())
        self.assertEqual(self.m.on_disk()[late.id]["state"], "waiting")
        self.assertTrue(early.try_locks())
        early.begin()
        self.assertFalse(late.try_locks())
        early.finish(0)
        self.assertTrue(late.try_locks())
        late.begin()
        self.assertEqual(Path(A.lock_file(self.m.env(), "pool")).read_text(), late.id + "\n")   # who has it, for whoever waits next
        for j in (late, other):
            j.finish(0)

    def test_a_job_that_only_waits_can_always_be_stopped(self):
        self.start(HOLD, "--lock", "pool", name="a", title="First")
        self.rec("First", lambda r: r["state"] == "running" and r["steps"])
        marker = self.m.tmp / "b-ran"
        b = self.start(f"echo ran > {marker}\n", "--lock", "pool", name="b")       # it never said stopping is safe
        job_id = self.rec(TITLE, "waiting")["id"]
        code, out, err = self.m.cli("cancel", job_id)
        self.assertEqual((code, out, err), (0, f"Stopped: {TITLE}\n", ""))
        self.assertEqual(b.wait(timeout=20), 130)
        rec = self.m.on_disk()[job_id]
        self.assertEqual((rec["state"], rec["exit_code"], rec["can"], rec["result"]["summary"]),
                         ("cancelled", None, [], "Stopped before it finished."))
        self.assertFalse(marker.exists())
        self.assertEqual(self.files(job_id), [".json", ".log"])
        code, _, err = self.m.cli("cancel", job_id)
        self.assertEqual((code, "That job has already ended (cancelled)." in err), (3, True))

    def test_what_a_lock_may_be_called(self):
        for name in ("Pool", "a b", "", "x" * 80):
            code, _, err = self.m.cli("run", "--kind", "pool.check", "--title", "Checking", "--lock", name, "--", "true")
            self.assertEqual((code, "a lock's name is a short lower-case word" in err), (1, True), name)
        with self.assertRaises(A.ActivityError):
            A.check_locks([f"l{k}" for k in range(A.MAX_LOCKS + 1)])
        self.assertEqual(A.check_locks(["pool", "apps", "pool"]), ["pool", "apps"])
        self.assertEqual(self.m.listed(), [])

    def test_a_python_command_waits_for_its_lock(self):
        env = self.m.env()
        holder = self.job(env, kind="pool.check", title="Checking the pool", locks=["pool"])
        self.assertTrue(holder.try_locks())
        holder.begin()
        seen = {}

        def other():
            with A.job("drive.replace", TITLE, env=env, locks=["pool"]) as j:
                seen["state"] = j.rec["state"]
        t = threading.Thread(target=other, daemon=True)
        t.start()
        rec = self.rec(TITLE, "waiting")
        self.assertEqual((rec["waiting_for"], rec["stage"]), ("another job", "Waiting for another job to finish: Checking the pool"))
        holder.finish(0)                                                          # its end lets the lock go
        t.join(20)
        self.assertFalse(t.is_alive())
        rec = self.rec(TITLE, "succeeded")
        self.assertEqual((seen["state"], rec["stage"], rec["result"]["summary"]), ("running", None, "Finished."))


class Cancel(Control):
    def test_cancel_is_refused_unless_the_job_says_it_is_safe(self):
        marker = self.m.tmp / "told"
        body = (f'trap "echo stopped > {marker}; exit 0" TERM\necho "::step work running Working"\n'
                'while [ ! -e "$GATE" ]; do sleep 0.02; done\necho "::cancel safe"\nwhile :; do sleep 0.02; done\n')
        p = self.start(body, title="Backing up", kind="backup.run")
        rec = self.rec("Backing up", lambda r: r["state"] == "running" and r["steps"])
        self.assertEqual((rec["cancel_safe"], rec["cancel_note"], rec["can"]), (False, None, []))
        code, out, err = self.m.cli("cancel", rec["id"])
        self.assertEqual((code, out), (3, ""))
        self.assertIn("not stopped. It hasn't said that stopping it now is safe.", err)
        time.sleep(0.5)
        self.assertEqual(self.m.on_disk()[rec["id"]]["state"], "running")         # refused means untouched
        self.assertFalse(marker.exists())
        self.assertEqual(self.files(rec["id"]), [".answers", ".json", ".lock", ".log"])   # no request left waiting
        self.gate.write_text("")
        self.rec("Backing up", lambda r: r["can"] == ["cancel"])
        code, out, err = self.m.cli("cancel", rec["id"])
        self.assertEqual((code, out, err), (0, "Stopped: Backing up\n", ""))
        self.assertEqual(p.wait(timeout=20), 130)
        rec = self.m.on_disk()[rec["id"]]
        self.assertEqual((rec["state"], rec["error"], rec["steps"][0]["state"]), ("cancelled", None, "skipped"))
        self.assertEqual(marker.read_text(), "stopped\n")                         # the command was told, and ended
        self.assertEqual(self.files(rec["id"]), [".json", ".log"])
        self.assertEqual(self.m.calls(), [])                                       # a cancel that was asked for isn't a shutdown

    def test_safe_from_the_start_until_the_job_says_otherwise(self):
        body = 'echo "::step work running Working"\nwhile [ ! -e "$GATE" ]; do sleep 0.02; done\necho "::cancel unsafe"\nwhile :; do sleep 0.02; done\n'
        self.start(body, "--cancel-safe", title="Testing a drive", kind="drive.test")
        rec = self.rec("Testing a drive", lambda r: r["state"] == "running" and r["steps"])
        self.assertEqual((rec["cancel_safe"], rec["can"]), (True, ["cancel"]))
        self.gate.write_text("")
        rec = self.rec("Testing a drive", lambda r: not r["cancel_safe"])
        self.assertEqual((rec["cancel_note"], rec["can"]), (None, []))
        self.assertEqual(self.m.cli("cancel", rec["id"])[0], 3)

    def test_the_job_itself_decides_when_the_cancel_arrives(self):
        """What the asker read may be a moment old: the job's own process has the last word."""
        marker = self.m.tmp / "told"
        p = self.start(f'trap "echo stopped > {marker}; exit 0" TERM\n' + HOLD, title="Backing up", kind="backup.run")
        rec = self.rec("Backing up", lambda r: r["state"] == "running" and r["steps"])
        rec["cancel_safe"] = True                                                 # a record that says "safe", as it did a moment ago
        (self.m.jobs / f"{rec['id']}.json").write_text(json.dumps(rec))
        code, out, err = self.m.cli("cancel", rec["id"])
        self.assertEqual((code, out), (3, ""))
        self.assertIn("not stopped.", err)
        self.assertEqual(self.files(rec["id"]), [".answers", ".json", ".lock", ".log"])   # the job took the request, and refused
        self.assertFalse(marker.exists())
        self.gate.write_text("")
        self.assertEqual(p.wait(timeout=20), 0)
        self.assertEqual(self.m.on_disk()[rec["id"]]["state"], "succeeded")


class Retry(Control):
    def test_a_job_that_failed_is_started_again(self):
        fixed = self.m.tmp / "fixed"
        body = f'echo "::step read running Reading the drive"\n[ -e {fixed} ] || {{ echo "::error read The drive is not there."; exit 4; }}\necho "::stage 100 It reads"\n'
        script = self.m.script(body)
        args = ["--kind", "drive.test", "--title", "Testing the drive in bay 2", "--subject", "drive:bay-2:Bay 2", "--lock", "pool"]
        code, _, err = self.m.cli("run", *args, "--retry-safe", "--cancel-safe", "--", script, "--long")
        self.assertEqual(code, 4)
        [old] = self.m.listed()
        self.assertEqual((old["state"], old["can"]), ("failed", ["retry"]))
        again = self.m.jobs / f"{old['id']}.retry"
        self.assertEqual(stat.S_IMODE(again.stat().st_mode), 0o600)
        self.assertEqual(json.loads(again.read_text()), {"argv": [script, "--long"], "cwd": str(self.m.tmp), "cancel_safe": True})
        self.assertIn(f"To start it again: sudo bromigos activity retry {old['id']}", self.m.cli("show", old["id"])[1])
        fixed.write_text("")
        code, out, err = self.m.cli("retry", old["id"], "--via", "phone", "--device", "pixel")
        self.assertEqual(code, 0, err)
        new = self.m.listed()[0]
        self.assertNotEqual(new["id"], old["id"])
        self.assertEqual((new["state"], new["result"]["summary"]), ("succeeded", "It reads"))
        for key in ("kind", "title", "subject", "command", "locks"):
            self.assertEqual(new[key], old[key], key)
        self.assertEqual(new["requested_by"], {"via": "phone", "device": "pixel"})
        self.assertEqual([n["words"] for n in new["notes"]], [f"Started again from {old['id']}."])
        self.assertEqual(self.m.on_disk()[old["id"]]["state"], "failed")          # the old record stays what it was
        self.assertEqual(self.m.cli("retry", old["id"], "--json")[0], 0)          # as often as it takes
        doc = json.loads(self.m.cli("retry", new["id"], "--json")[1])              # but not one that ended well
        self.assertEqual((doc["ok"], doc["refused"]), (False, "not-retryable"))
        self.assertIn("nothing to try again", doc["words"])

    def test_only_a_job_started_as_safe_to_start_again(self):
        script = self.m.script("exit 1\n")
        self.m.cli("run", "--kind", "drive.test", "--title", "Testing", "--", script)
        [rec] = self.m.listed()
        self.assertEqual(rec["can"], [])
        code, out, err = self.m.cli("retry", rec["id"])
        self.assertEqual((code, out), (3, ""))
        self.assertIn("not started again. It wasn't started as a job that is safe to start again (--retry-safe)", err)
        self.assertIn(f"To run it again yourself: {script}", err)
        self.assertEqual(len(self.m.listed()), 1)
        self.start(HOLD, title="Still going")
        going = self.rec("Still going", "running")
        code, _, err = self.m.cli("retry", going["id"])
        self.assertEqual((code, "It is still going (running)." in err), (3, True))

    def test_a_command_with_a_secret_is_never_kept_to_start_again(self):
        script = self.m.script("exit 1\n")
        code, _, err = self.m.cli("run", "--kind", "backup.run", "--title", "Backing up", "--retry-safe", "--", script, "--password", "hunter2")
        self.assertEqual(code, 1)
        self.assertIn("can't be started again with `retry`: its command has a secret in it", err)
        [rec] = self.m.listed()
        self.assertEqual((rec["can"], rec["command"]), ([], [script, "--password", "***"]))
        self.assertEqual(self.files(rec["id"]), [".json", ".log"])
        self.assertNotIn("hunter2", "".join(p.read_text() for p in self.m.jobs.iterdir()))
        self.assertEqual(self.m.cli("retry", rec["id"])[0], 3)

    def test_an_interrupted_job_offers_retry_and_its_files_go_with_it(self):
        env = self.m.env(BROMIGOS_ACTIVITY_NOW_MS=NOW)
        j = self.job(env, retry=A.retry_spec(["true"], "/"))
        j.begin()
        j.open_answers()
        j.feed("::ask go Ready? [go] Go")
        self.assertEqual(self.m.on_disk()[j.id]["can"], ["answer"])
        os.close(j._lock)                                                         # the power went
        j._lock = None
        rec = A.find(env, j.id)
        self.assertEqual((rec["state"], rec["can"], rec["question"]), ("interrupted", ["retry"], None))
        self.assertEqual(A.answer(env, j.id, "go")["refused"], "ended")
        self.assertEqual(A.sweep(env)[0], [j.id])
        self.assertEqual(self.files(j.id), [".json", ".retry"])                   # the pipe went; what to start again stays
        self.assertEqual(self.m.on_disk()[j.id]["can"], ["retry"])
        A.sweep(self.m.env(BROMIGOS_ACTIVITY_NOW_MS=NOW + 31 * DAY))
        self.assertEqual(self.files(j.id), [])


class Parts(Control):
    def run_child(self, *args):
        return f'{sys.executable} {fake.SCRIPT} run --kind app.update --title "Updating Photos" --subject app:photos:Photos {" ".join(args)}'

    def test_a_job_started_by_a_job_is_a_part_of_it(self):
        child = self.m.script('echo "::stage 100 Photos is up to date"\n', "child")
        body = f'echo "::step photos running Photos"\n{self.run_child("--lock", "apps")} -- {child} || exit 1\necho "::stage 100 Everything is up to date"\n'
        code, out, err = self.m.cli("run", "--kind", "app.update-all", "--title", "Updating every app", "--lock", "apps", "--", self.m.script(body))
        self.assertEqual(code, 0, err)
        jobs = {r["kind"]: r for r in self.m.listed()}
        parent, kid = jobs["app.update-all"], jobs["app.update"]
        self.assertEqual((parent["children"], parent["parent"]), ([kid["id"]], None))
        self.assertEqual((kid["parent"], kid["children"]), (parent["id"], []))
        # the child named the lock its parent holds, and didn't wait for it
        self.assertEqual((kid["locks"], kid["state"], parent["state"]), (["apps"], "succeeded", "succeeded"))
        out = self.m.cli("show", parent["id"])[1]
        self.assertIn(f"Parts    {kid['id']}", out)
        self.assertIn(f"Part of  {parent['id']}", self.m.cli("show", kid["id"])[1])
        self.assertEqual(self.files(parent["id"]), [".children", ".json", ".log"])
        # nothing can be a part of a job that has ended, or of one that isn't there
        code, _, err = self.m.cli("run", "--kind", "app.update", "--title", "Late", "--parent", parent["id"], "--", "true")
        self.assertEqual((code, f"{parent['id']} has ended (done), so a new job can't be a part of it" in err), (1, True))
        code, _, err = self.m.cli("run", "--kind", "app.update", "--title", "Lost", "--parent", "nothing-like-it", "--", "true")
        self.assertEqual((code, "--parent: no job 'nothing-like-it'" in err), (1, True))
        self.assertEqual(len(self.m.listed()), 2)

    def parent_and_child(self, child_args):
        body = f'{self.run_child(*child_args)} -- {self.m.script(HOLD, "child")}\n'
        p = self.start(body, "--cancel-safe", title="Updating every app", kind="app.update-all")
        kid = self.rec("Updating Photos", lambda r: r["state"] == "running" and r["steps"])
        parent = self.rec("Updating every app", lambda r: r["children"])
        return p, parent, kid

    def test_a_parent_is_stopped_with_its_children(self):
        p, parent, kid = self.parent_and_child(["--cancel-safe"])
        code, out, err = self.m.cli("cancel", parent["id"])
        self.assertEqual((code, out), (0, "Stopped: Updating every app\n"), err)
        self.assertEqual(p.wait(timeout=20), 130)
        self.assertEqual(self.rec("Updating Photos", "cancelled")["id"], kid["id"])
        self.assertEqual(self.m.on_disk()[parent["id"]]["state"], "cancelled")

    def test_one_part_that_cannot_stop_keeps_them_all_going(self):
        p, parent, kid = self.parent_and_child([])
        code, out, err = self.m.cli("cancel", parent["id"])
        self.assertEqual(code, 3)
        self.assertIn("not stopped. Its part \"Updating Photos\" can't be stopped now. It hasn't said that stopping it now is safe.", err)
        time.sleep(0.5)
        self.assertEqual({r["state"] for r in self.m.on_disk().values()}, {"running"})
        self.gate.write_text("")
        self.assertEqual(p.wait(timeout=20), 0)


class TheAlert(Control):
    """A job that failed is one alert in `bromigos alerts`' system document, raised as it ends."""
    FAILS = 'echo "what only the log may hold: 4c1d-detail"\necho "::step copy running Copying what changed"\necho "::error copy The backup drive stopped answering."\nexit 12\n'
    ARGS = ["run", "--kind", "backup.run", "--title", "Backing up to the USB drive", "--subject", "backup:usb:USB drive"]

    def alerts(self):
        p = self.m.root / "var/lib/bromigos/alerts/system.json"
        return [a for a in json.loads(p.read_text())["alerts"]] if p.exists() else None

    def test_a_failed_job_raises_one_alert_and_a_good_run_clears_it(self):
        code, _, err = self.m.cli("run", "--kind", "backup.run", "--title", "A good run first", "--", "true")
        self.assertIsNone(self.alerts())                                          # a job that ends well runs no check
        self.assertEqual(self.m.cli(*self.ARGS, "--retry-safe", "--", self.m.script(self.FAILS))[0], 12)
        rec = self.m.listed()[0]
        [a] = self.alerts()
        self.assertEqual((a["id"], a["check"], a["severity"], a["subject"], a["source"]),
                         ("activity.job:backup.run:backup/usb", "activity.job", "needs_you", "usb", "Activity"))
        self.assertEqual(a["title"], "A job failed: Backing up to the USB drive")
        self.assertEqual(a["detail"], '"Backing up to the USB drive" stopped at "Copying what changed": The backup drive stopped '
                                      f"answering. `bromigos activity show {rec['id']}` has its steps and what it printed.")
        self.assertEqual(a["fix"]["commands"], [f"bromigos activity show {rec['id']}", f"sudo bromigos activity retry {rec['id']}"])
        self.assertEqual(a["evidence"]["facts"], {"job": rec["id"], "kind": "backup.run", "state": "failed", "exit_code": "12", "step": "copy"})
        self.assertNotIn("4c1d-detail", json.dumps(a))                            # the log is root's; the alert is everyone's
        since = a["since"]
        # it fails again: still one alert, first seen when it first failed
        self.assertEqual(self.m.cli(*self.ARGS, "--", self.m.script(self.FAILS))[0], 12)
        [a] = self.alerts()
        self.assertEqual((a["since"], a["evidence"]["facts"]["job"]), (since, self.m.listed()[0]["id"]))
        # a run that is stopped changes nothing; the same work for something else is its own alert
        p = self.start(HOLD, "--subject", "backup:usb:USB drive", "--cancel-safe", kind="backup.run", title="Backing up to the USB drive")
        self.assertEqual(self.m.cli("cancel", self.rec("Backing up to the USB drive", "running")["id"])[0], 0)
        p.wait(timeout=20)
        self.assertEqual(self.m.cli(*self.ARGS[:5], "--subject", "backup:nas:The NAS", "--", self.m.script(self.FAILS))[0], 12)
        self.assertEqual(sorted(a["id"] for a in self.alerts()), ["activity.job:backup.run:backup/nas", "activity.job:backup.run:backup/usb"])
        # the work succeeds: its alert goes as the job ends, the other stays
        self.assertEqual(self.m.cli(*self.ARGS, "--", "true")[0], 0)
        self.assertEqual([a["id"] for a in self.alerts()], ["activity.job:backup.run:backup/nas"])

    def test_put_back_is_for_information_and_a_parent_leaves_the_word_to_its_child(self):
        env = self.m.env()
        with self.assertRaises(RuntimeError):
            with A.job("app.update", "Updating Photos", {"type": "app", "id": "photos", "name": "Photos"}, env=env) as j:
                j.step("health", "Checking it answers")
                j.finish(1, state="rolled-back", words="The new version didn't answer.")
                raise RuntimeError("after its end, nothing changes it")
        [a] = self.alerts()
        self.assertEqual((a["id"], a["severity"], a["title"]), ("activity.job:app.update:app/photos", "info", "A job failed and put things back: Updating Photos"))
        self.assertIn("It then put things back the way they were, so nothing is left half done.", a["detail"])
        self.assertEqual(a["fix"]["commands"], [f"bromigos activity show {j.id}"])
        parent = self.job(env, kind="app.update-all", title="Updating every app")
        parent.begin()
        kid = self.job(env, kind="app.update", title="Updating Films", subject={"type": "app", "id": "films", "name": "Films"}, parent=parent.id)
        kid.begin()
        kid.finish(1, words="No room left.")
        parent.finish(1, words="1 app didn't update.")
        self.assertEqual(self.m.on_disk()[parent.id]["children"], [kid.id])
        self.assertEqual([r["id"] for r in A.needing_a_look(env)], sorted([j.id, kid.id]))
        lone = self.job(env, kind="pool.check", title="Checking the pool")      # with no subject: one alert for the kind
        lone.begin()
        lone.finish(1)
        A.raise_alert(env, lone.rec)
        self.assertEqual(sorted(a["id"] for a in self.alerts()),
                         ["activity.job:app.update:app/films", "activity.job:app.update:app/photos", "activity.job:pool.check"])

    def test_the_check_in_a_pass_of_its_own(self):
        """As the timer runs it (`bromigos alerts check --system`), on the alerts' own stand-in root."""
        import bromigos_alerts as alerts
        aenv = alerts.Env(dict(self.m.environ, BROMIGOS_ALERTS_ROOT=str(self.m.root)))
        doc = alerts.run_pass(aenv, "system", checks={"activity.job"})
        self.assertEqual([(c["state"], c["error"]) for c in doc["checks"]], [("skipped", "no job has run here yet")])
        self.m.cli(*self.ARGS, "--", self.m.script(self.FAILS))
        os.unlink(self.m.root / "var/lib/bromigos/alerts/system.json")
        doc = alerts.run_pass(aenv, "system", checks={"activity.job"})
        self.assertEqual([(c["check"], c["state"]) for c in doc["checks"]], [("activity.job", "ran")])
        self.assertEqual([a["id"] for a in doc["alerts"]], ["activity.job:backup.run:backup/usb"])


class InItsOwnUnit(Control):
    """The same, where systemd runs (a stand-in systemd-run): the job that asks is a unit, and
    whoever answers is another command altogether."""
    systemd = True

    def test_a_unit_asks_is_answered_and_carries_on(self):
        code, out, err = self.m.cli("run", "--kind", "drive.replace", "--title", TITLE, "--lock", "pool", "--retry-safe", "--detach",
                                    "--", self.m.script(REPLACE))
        self.assertEqual(code, 0, err)
        job_id = out.strip()
        rec = self.rec(TITLE, "needs-you")
        self.assertEqual((rec["id"], rec["unit"], rec["can"]), (job_id, A.unit_name(job_id), ["answer", "cancel"]))
        # a second job on the same lock waits behind it, for as long as it asks
        code, out, err = self.m.cli("run", "--kind", "pool.check", "--title", "Checking the pool", "--lock", "pool", "--detach", "--", "true")
        other = self.rec("Checking the pool", "waiting")
        self.assertEqual((other["waiting_for"], other["stage"]), ("another job", f"Waiting for another job to finish: {TITLE}"))
        self.assertEqual(self.m.cli("answer", job_id, "swapped")[0], 0)
        self.rec(TITLE, lambda r: r["cancel_note"])
        code, _, err = self.m.cli("cancel", job_id)
        self.assertEqual(code, 3)
        self.assertIn(f"To stop it anyway: sudo systemctl stop bromigos-job-{job_id}.service", err)
        self.gate.write_text("")
        self.assertEqual(self.rec(TITLE, "succeeded")["id"], job_id)
        self.assertEqual(self.rec("Checking the pool", "succeeded")["id"], other["id"])
        self.assertEqual(self.files(job_id), [".json", ".log", ".retry"])

    def test_whoever_follows_a_unit_is_told_what_it_asks(self):
        p = self.start(REPLACE)
        job_id = self.rec(TITLE, "needs-you")["id"]
        self.assertEqual(self.m.cli("answer", job_id, "swapped")[0], 0)
        self.gate.write_text("")
        self.assertEqual(p.wait(timeout=20), 0)
        self.assertIn(f"sudo bromigos activity answer {job_id} swapped    (I've swapped the drive)", p.stderr.read())

    def test_a_cancelled_unit_and_one_started_again(self):
        code, out, err = self.m.cli("run", "--kind", "drive.test", "--title", "Testing a drive", "--cancel-safe", "--retry-safe",
                                    "--detach", "--", self.m.script('trap "exit 0" TERM\n' + HOLD))
        job_id = out.strip()
        self.rec("Testing a drive", lambda r: r["state"] == "running" and r["steps"])
        self.assertEqual(self.m.cli("cancel", job_id)[0], 0)
        rec = self.m.on_disk()[job_id]
        self.assertEqual((rec["state"], rec["can"]), ("cancelled", ["retry"]))
        self.assertNotIn("systemctl is-system-running", self.m.calls())           # it was asked to stop: no need to wonder
        self.gate.write_text("")
        code, out, err = self.m.cli("retry", job_id, "--detach", "--json")
        self.assertEqual(code, 0, err)
        new = json.loads(out)
        self.assertEqual(new["unit"], f"bromigos-job-{new['id']}.service")
        done = self.rec("Testing a drive", lambda r: r["id"] == new["id"] and r["state"] == "succeeded")
        self.assertEqual((done["cancel_safe"], [n["words"] for n in done["notes"]]), (True, [f"Started again from {job_id}."]))


if __name__ == "__main__":
    unittest.main()
