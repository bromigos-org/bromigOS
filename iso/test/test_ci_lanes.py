"""iso/ci-test.sh's lanes: the suite's chains of VMs side by side, and the same result as one
after another.

Until 2026-11-09 the desktop medium's tests ran every VM in a row: 40 minutes of a release's
57, on a runner with room for two. Nothing here starts a VM: BROMIGOS_ISOTEST_T puts a stand-in
in iso/test.sh's place, which notes each call (the lane, when, its ports and environment) and
fails where the test says; sleep, socat, magick and pacman are stand-ins too, so the Secure
Boot lanes' own waits take no time and nothing of the machine is touched.
"""
import json
import os
import stat
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))
CI_TEST = os.path.join(HERE, "../ci-test.sh")

STANDIN = r'''#!/usr/bin/env python3
import json, os, socket, sys, time
d = os.environ["BROMIGOS_ISOTEST_DIR"]
lane, cmd = os.path.basename(d), sys.argv[1]
secboot = "secboot" in os.environ.get("BROMIGOS_ISOTEST_OVMF_CODE", "")
os.makedirs(os.path.join(d, "shots"), exist_ok=True)
start = time.time()
try:
    with open(os.path.join(d, "OVMF_VARS.fd")) as f:
        firmware = f.read()
except OSError:
    firmware = None
if cmd in ("boot", "install", "boot-disk", "menu", "mok-enroll"):
    time.sleep(json.loads(os.environ.get("STANDIN_SLOW", "{}")).get(lane, 0.05))
if cmd == "boot" and not os.path.exists(os.path.join(d, "qmp.sock")):
    # the VM's monitor: there, as the Secure Boot lane's key presses wait for it (nobody answers)
    here = os.getcwd()
    os.chdir(d)
    socket.socket(socket.AF_UNIX).bind("qmp.sock")
    os.chdir(here)
if cmd == "boot" and secboot:               # as MokManager's enrollment leaves the firmware
    with open(os.path.join(d, "OVMF_VARS.fd"), "a") as f:
        f.write("+the medium's key")
    open(os.path.join(d, "shots", ".menu-themed"), "w").close()
if cmd == "install" and secboot:
    with open(os.path.join(d, "secureboot-code"), "w") as f:
        f.write("123456\n")
line = json.dumps({
    "lane": lane, "cmd": cmd, "args": sys.argv[2:], "start": start, "end": time.time(), "firmware": firmware,
    **{k: os.environ.get("BROMIGOS_" + k) for k in (
        "ISOTEST_PORT", "ISOTEST_VNC", "ISOTEST_OFFLINE", "ISOTEST_OVMF_CODE", "ISOTEST_QEMU",
        "ISOTEST_PASS_WAIT", "VM_CI_BUDGET")}}) + "\n"
fd = os.open(os.environ["STANDIN_LOG"], os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
os.write(fd, line.encode())
os.close(fd)
print(f"stand-in: {lane} {cmd}")
sys.exit(1 if f"{lane}:{cmd}" in os.environ.get("STANDIN_FAIL", "").split() else 0)
'''

# on PATH before the machine's: the script's own waits take no time, and nothing is installed
SHIMS = {
    "sleep": "#!/bin/bash\nread -rt 0.005 <> <(:) || :\n",
    "socat": "#!/bin/sh\ncat >/dev/null\n",
    "magick": "#!/bin/sh\nexit 1\n",
    "pacman": "#!/bin/sh\nexit 1\n",
}


class Run:
    """One run of iso/ci-test.sh with the stand-ins: its output, exit status and the harness's calls."""

    def __init__(self, *args, env=None, ci=False):
        self.tmp = tempfile.TemporaryDirectory(prefix="ci-lanes-")
        t = self.tmp.name
        bin_ = os.path.join(t, "bin")
        os.mkdir(bin_)
        for name, body in {**SHIMS, "harness": STANDIN}.items():
            path = os.path.join(bin_, name)
            with open(path, "w") as f:
                f.write(body)
            os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        for name, body in (("medium.iso", ""), ("sb.cer", ""), ("ms-vars.fd", "Microsoft's keys")):
            with open(os.path.join(t, name), "w") as f:
                f.write(body)
        self.out = os.path.join(t, "out")
        self.log = os.path.join(t, "calls.jsonl")
        # the machine's own environment stays out: these tests may be running on a CI runner
        e = {"PATH": bin_ + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"), "HOME": t, "LC_ALL": "C",
             "BROMIGOS_ISOTEST_IN_CONTAINER": "1", "BROMIGOS_ISOTEST_T": os.path.join(bin_, "harness"),
             "BROMIGOS_ISOTEST_SB_VARS": os.path.join(t, "ms-vars.fd"), "STANDIN_LOG": self.log}
        if ci:
            e["GITHUB_ACTIONS"] = "true"
        e.update(env or {})
        args = [a.replace("SBCERT", os.path.join(t, "sb.cer")) for a in args]
        p = subprocess.run(["bash", CI_TEST, os.path.join(t, "medium.iso"), "--out", self.out, *args],
                           env=e, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, timeout=120)
        self.rc, self.text = p.returncode, p.stdout
        self.lines = self.text.splitlines()
        self.calls = []
        if os.path.exists(self.log):
            with open(self.log) as f:
                self.calls = [json.loads(line) for line in f]

    def close(self):
        self.tmp.cleanup()

    def most_at_once(self):
        """The most lanes that had a step of the harness's running at the same moment."""
        edges = sorted([(c["start"], 1, c["lane"]) for c in self.calls] + [(c["end"], -1, c["lane"]) for c in self.calls],
                       key=lambda e: (e[0], e[1]))
        busy, most = {}, 0
        for _, d, lane in edges:
            busy[lane] = busy.get(lane, 0) + d
            most = max(most, sum(1 for n in busy.values() if n > 0))
        return most

    def of(self, lane, cmd=None):
        return [c for c in self.calls if c["lane"] == lane and cmd in (None, c["cmd"])]

    def results(self):
        """The PASS, FAIL and SKIP lines, in the order printed."""
        return [line for line in self.lines if line.startswith(("PASS ", "FAIL ", "SKIP "))]


def run(case, *args, **kw):
    r = Run(*args, **kw)
    case.addCleanup(r.close)
    return r


DESKTOP = ["uefi-encrypted", "bios-offline-plain", "menu-text"]


class Lanes(unittest.TestCase):
    maxDiff = None

    def test_one_at_a_time_is_the_run_as_it_was(self):
        r = run(self, "--suite", "desktop", "--jobs", "1", "--dev-build")
        self.assertEqual(r.rc, 0, r.text)
        self.assertEqual(r.lines[-1], "==> 0 failed")
        self.assertEqual(r.most_at_once(), 1)
        # every lane's steps, whole, before the next lane's: by the calls and by what was printed
        self.assertEqual([c["lane"] for c in r.calls], sorted((c["lane"] for c in r.calls), key=DESKTOP.index))
        self.assertEqual(r.results(), [
            "PASS uefi-encrypted: the live desktop",
            "PASS uefi-encrypted: the graphical installer's fields take a real click and real typing",
            "PASS uefi-encrypted: the install",
            "PASS uefi-encrypted: the installed system",
            "SKIP uefi-encrypted: the first update and rollback (a pull request's medium, --dev-build)",
            "PASS bios-offline-plain: the live desktop",
            "PASS bios-offline-plain: the graphical installer's fields take a real click and real typing",
            "PASS bios-offline-plain: the install",
            "PASS bios-offline-plain: the installed system",
            "SKIP bios-offline-plain: the first update and rollback (a pull request's medium, --dev-build)",
            "PASS the boot menu's text installer: on the console's screen, taking keys (UEFI)",
        ])
        # the BIOS lane's medium has no network, its installed system does; the others always
        self.assertEqual({c["ISOTEST_OFFLINE"] for c in r.of("uefi-encrypted")}, {"0"})
        self.assertEqual([c["ISOTEST_OFFLINE"] for c in r.of("bios-offline-plain") if c["cmd"] in ("boot", "install", "boot-disk")],
                         ["1", "1", "0"])
        self.assertEqual(r.of("uefi-encrypted", "install")[0]["args"], [])
        self.assertEqual(r.of("bios-offline-plain", "install")[0]["args"], ["--no-encrypt"])
        # one at a time: neither a longer wait for the passphrase nor a CI budget
        self.assertEqual({(c["ISOTEST_PASS_WAIT"], c["VM_CI_BUDGET"]) for c in r.calls}, {(None, None)})
        for lane in DESKTOP:
            self.assertTrue(os.path.exists(os.path.join(r.out, f"lane-{lane}.log")), lane)

    def test_side_by_side_prints_the_same_in_the_same_order(self):
        # the first lane the slowest: the others end before it, and are still printed after it
        slow = {"STANDIN_SLOW": json.dumps({"uefi-encrypted": 0.4})}
        one = run(self, "--suite", "desktop", "--jobs", "1", "--dev-build", ci=True, env=slow)
        two = run(self, "--suite", "desktop", "--jobs", "2", "--dev-build", ci=True, env=slow)
        self.assertEqual(two.rc, 0, two.text)
        self.assertEqual(two.most_at_once(), 2)
        self.assertEqual(two.results(), one.results())
        self.assertEqual(two.lines[-1], "==> 0 failed")
        ended = [line.split(":")[0] for line in two.lines if line.startswith("lane ") and ": done in " in line]
        self.assertEqual(sorted(ended), sorted("lane " + n for n in DESKTOP))
        self.assertEqual(ended[-1], "lane uefi-encrypted", two.text)
        # each lane's log is its own steps, whole, under its heading
        text = two.text
        marks = [text.index(f"── lane {n} (") for n in DESKTOP]
        self.assertEqual(marks, sorted(marks))
        self.assertLess(marks[1], text.index("PASS bios-offline-plain: the install"))
        self.assertLess(text.index("PASS bios-offline-plain: the install"), marks[2])
        with open(os.path.join(two.out, "lane-bios-offline-plain.log")) as f:
            own = f.read()
        self.assertIn("::group::bios-offline-plain: the install", own)
        self.assertNotIn("uefi-encrypted", own)
        # side by side on a runner: the VMs' budget is the lanes', and the passphrase gets longer
        self.assertEqual({(c["ISOTEST_PASS_WAIT"], c["VM_CI_BUDGET"]) for c in two.calls}, {("40", "12288:8")})

    def test_failures_are_counted_across_lanes(self):
        fail = {"STANDIN_FAIL": "uefi-encrypted:gui-type bios-offline-plain:install menu-text:menu"}
        for jobs in ("1", "3"):
            with self.subTest(jobs=jobs):
                r = run(self, "--suite", "desktop", "--jobs", jobs, ci=True, env=fail)
                self.assertEqual(r.rc, 1, r.text)
                self.assertEqual(r.lines[-1], "==> 3 failed")
                self.assertEqual([line for line in r.results() if line.startswith("FAIL")], [
                    "FAIL uefi-encrypted: the graphical installer's fields take a real click and real typing",
                    "FAIL bios-offline-plain: the install",
                    "FAIL the boot menu's text installer: on the console's screen, taking keys (UEFI)",
                ])
                # the typing test doesn't stop its lane; a failed install does (nothing to start)
                self.assertTrue(r.of("uefi-encrypted", "boot-disk"))
                self.assertFalse(r.of("bios-offline-plain", "boot-disk"))
                summary = [line.split() for line in r.lines if line.startswith("    ") and line.rstrip().endswith("failed")]
                self.assertEqual([(s[0], s[3]) for s in summary], [(n, "1") for n in DESKTOP])

    def test_every_lane_has_ports_of_its_own(self):
        r = run(self, "--suite", "desktop", "--jobs", "3", "--secureboot-cert", "SBCERT", ci=True)
        self.assertEqual(r.rc, 0, r.text)
        lanes = DESKTOP + ["secureboot", "secureboot-dualboot"]
        ports = {n: {(c["ISOTEST_PORT"], c["ISOTEST_VNC"]) for c in r.of(n)} for n in lanes}
        for n in lanes:
            self.assertEqual(len(ports[n]), 1, (n, ports[n]))       # one pair for the lane's whole life
        ssh = [next(iter(ports[n]))[0] for n in lanes]
        vnc = [next(iter(ports[n]))[1] for n in lanes]
        self.assertEqual(len(set(ssh)), len(lanes), ssh)
        self.assertEqual(len(set(vnc)), len(lanes), vnc)
        with open(os.path.join(r.out, ".ports")) as f:
            book = f.read().split()
        self.assertEqual(sorted(book), sorted(ssh + [str(5900 + int(v)) for v in vnc]))

    def test_a_port_taken_in_this_run_is_never_given_twice(self):
        # two lanes asking from the same base at the same moment: the book, under its lock, decides
        with tempfile.TemporaryDirectory() as t:
            with open(CI_TEST) as f:
                src = f.read()
            py = src.split("python3 - \"$1\" \"$out/.ports\" <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
            procs = [subprocess.Popen(["python3", "-c", py, "23900", os.path.join(t, ".ports")],
                                      stdout=subprocess.PIPE, text=True) for _ in range(8)]
            got = [p.communicate()[0].strip() for p in procs]
        self.assertEqual(len(set(got)), 8, got)
        self.assertTrue(all(p.isdigit() and int(p) >= 23900 for p in got), got)


class HowMany(unittest.TestCase):
    def lanes_line(self, r):
        return next(line for line in r.lines if line.startswith("==> lanes: 3 "))

    def test_a_runner_takes_what_its_memory_and_cpus_hold(self):
        cores = len(os.sched_getaffinity(0))
        for avail, by_memory in (("14400", 2), ("13800", 1), ("8000", 1), ("3000", 1), ("40000", 6)):
            with self.subTest(avail=avail):
                r = run(self, "--suite", "desktop", ci=True, env={"BROMIGOS_ISOTEST_AVAIL_MIB": avail})
                self.assertEqual(r.rc, 0, r.text)
                want = max(1, min(by_memory, cores // 2, 3))
                self.assertIn(f", {want} side by side ({avail} MiB available, {cores} CPUs; 6144 MiB and 4 CPUs a VM)",
                              self.lanes_line(r))
                self.assertEqual(r.most_at_once(), want)

    def test_a_runner_is_given_the_number_it_is_told(self):
        # a container with a memory limit sees its machine's memory: whoever runs it there says
        r = run(self, "--suite", "desktop", ci=True, env={"BROMIGOS_ISOTEST_JOBS": "3", "BROMIGOS_ISOTEST_AVAIL_MIB": "2000"})
        self.assertEqual(r.most_at_once(), 3, r.text)
        self.assertEqual({c["VM_CI_BUDGET"] for c in r.calls}, {"18432:12"})

    def test_a_workstation_keeps_to_its_test_vm_budget(self):
        # not a CI runner: one VM of the default size, whatever is asked for or available
        for args, env in ((["--jobs", "4"], {}), ([], {"BROMIGOS_ISOTEST_AVAIL_MIB": "64000"}), ([], {"BROMIGOS_ISOTEST_JOBS": "auto"})):
            with self.subTest(args=args, env=env):
                r = run(self, "--suite", "desktop", *args, env=env)
                self.assertEqual(r.rc, 0, r.text)
                self.assertEqual(r.most_at_once(), 1)
                self.assertIn(", 1 side by side (the test VMs' budget here: 8 GiB and 4 CPUs together;", self.lanes_line(r))
                self.assertEqual({c["VM_CI_BUDGET"] for c in r.calls}, {None})
        r = run(self, "--suite", "desktop", "--jobs", "4")
        self.assertIn("==> lanes: 4 asked for, 1 side by side", r.text)
        # two small VMs fit the budget (2 CPUs and 2 GiB each), a third doesn't
        r = run(self, "--suite", "desktop", "--jobs", "3", env={"BROMIGOS_ISOTEST_MEM": "2048", "BROMIGOS_ISOTEST_SMP": "2"})
        self.assertEqual(r.most_at_once(), 2, r.text)
        self.assertEqual({c["VM_CI_BUDGET"] for c in r.calls}, {None})

    def test_jobs_must_be_a_number_or_auto(self):
        for args, env in ((["--jobs", "0"], {}), (["--jobs", "two"], {}), (["--jobs", ""], {}),
                          ([], {"BROMIGOS_ISOTEST_JOBS": "-1"}), ([], {"BROMIGOS_ISOTEST_JOBS": "1.5"})):
            with self.subTest(args=args, env=env):
                r = run(self, "--suite", "desktop", *args, env=env)
                self.assertEqual(r.rc, 2, r.text)
                self.assertIn("--jobs N or auto", r.text)
                self.assertFalse(r.calls)


class BesideWindows(unittest.TestCase):
    """Secure Boot's install beside Windows: a lane of its own, from the firmware variables the
    Secure Boot lane saves after its first start."""

    SECBOOT = "/usr/share/edk2/x64/OVMF_CODE.secboot.4m.fd"

    def test_it_waits_for_the_enrolled_firmware_then_runs_beside_the_install(self):
        slow = {"STANDIN_SLOW": json.dumps({"secureboot": 0.5})}
        r = run(self, "--suite", "none", "--secureboot-cert", "SBCERT", "--jobs", "2", ci=True, env=slow)
        self.assertEqual(r.rc, 0, r.text)
        self.assertEqual(r.lines[-1], "==> 0 failed")
        first, beside = r.of("secureboot", "boot")[0], r.of("secureboot-dualboot")
        self.assertTrue(beside)
        # nothing of its own before the medium's key is enrolled, and it starts from that firmware
        self.assertGreaterEqual(min(c["start"] for c in beside), first["end"])
        self.assertEqual(r.of("secureboot-dualboot", "boot")[0]["firmware"], "Microsoft's keys+the medium's key")
        self.assertEqual(first["firmware"], "Microsoft's keys")
        # then both installs at once
        self.assertEqual(r.most_at_once(), 2)
        # the Secure Boot firmware in both lanes, each with its own directory's code
        for c in r.calls:
            self.assertEqual((c["ISOTEST_OVMF_CODE"], c["ISOTEST_OFFLINE"]), (self.SECBOOT, "0"), c)
            self.assertIn("smm=on", c["ISOTEST_QEMU"])
        self.assertEqual(r.of("secureboot-dualboot", "install")[0]["args"], ["--alongside"])
        self.assertEqual(r.of("secureboot-dualboot", "mok-enroll")[0]["args"], ["123456"])
        results = r.results()
        last_installed = max(i for i, line in enumerate(results) if line.startswith("PASS secure boot, installed:"))
        first_beside = min(i for i, line in enumerate(results) if "beside Windows" in line)
        self.assertLess(last_installed, first_beside)
        self.assertEqual(sum("beside Windows" in line for line in results), 7)

    def test_one_at_a_time_it_follows_the_install_as_before(self):
        r = run(self, "--suite", "none", "--secureboot-cert", "SBCERT", "--jobs", "1", ci=True)
        self.assertEqual(r.rc, 0, r.text)
        self.assertEqual(r.most_at_once(), 1)
        self.assertGreaterEqual(min(c["start"] for c in r.of("secureboot-dualboot")), max(c["end"] for c in r.of("secureboot")))
        self.assertEqual(r.of("secureboot-dualboot", "boot")[0]["firmware"], "Microsoft's keys+the medium's key")

    def test_no_enrolled_firmware_is_a_skip_not_a_wait(self):
        # the Secure Boot lane ends before its first start (no firmware variables to be had)
        for jobs in ("1", "2"):
            with self.subTest(jobs=jobs):
                r = run(self, "--suite", "none", "--secureboot-cert", "SBCERT", "--jobs", jobs, ci=True,
                        env={"BROMIGOS_ISOTEST_SB_VARS": "/nowhere/vars.fd"})
                self.assertFalse(r.of("secureboot-dualboot"), r.text)
                self.assertIn("SKIP secure boot, beside Windows: the Secure Boot lane saved no firmware variables to start from",
                              r.results())
                self.assertEqual(r.lines[-1], "==> 0 failed")

    def test_a_failed_first_step_leaves_nothing_running_for_the_lanes_after(self):
        r = run(self, "--suite", "none", "--secureboot-cert", "SBCERT", "--jobs", "2", ci=True,
                env={"STANDIN_FAIL": "secureboot-dualboot:boot"})
        self.assertEqual(r.rc, 1, r.text)
        self.assertEqual(r.lines[-1], "==> 1 failed")
        # the lane stopped at its first step, and its VM was put away all the same
        self.assertEqual([c["cmd"] for c in r.of("secureboot-dualboot")], ["boot", "destroy"])


class OtherSuites(unittest.TestCase):
    def test_no_lanes_no_lane_output(self):
        r = run(self, "--suite", "none")
        self.assertEqual((r.rc, r.lines), (0, ["==> 0 failed"]))
        self.assertFalse(r.calls)


if __name__ == "__main__":
    unittest.main()
