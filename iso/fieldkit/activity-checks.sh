#!/usr/bin/env bash
# `bromigos activity` (docs/activity.md) under real systemd, on the installed bromigOS Server.
# iso/fieldkit/ci-test.sh sends this file into the VM and runs one check at a time, as the
# user the install made (tester, who has sudo with a password), on the serial console:
#
#   activity-checks.sh ok             a job in a real transient unit ends succeeded, with its steps
#   activity-checks.sh failed         a job that fails names its step and its exit status
#   activity-checks.sh detach-start   a detached job starts; the caller then ends this session
#   activity-checks.sh detach-end     in a new session: the job went on, and ended succeeded
#   activity-checks.sh tour           the Server tour's apply (bromigos welcome-console --provision
#                                     apply) as this user: sudo -v, then the job as root
#   activity-checks.sh reboot-start   a detached long job starts, then the system restarts
#   activity-checks.sh reboot-end     after the restart: the record reads and is closed interrupted
#
# The unit tests (tests/activity) use stand-ins for systemd-run and sudo. Nothing here does.
set -euo pipefail
d=$HOME/activity-checks
mkdir -p "$d"
cd "$d"

# sudo's ticket belongs to this terminal and this sign-in: the harness types the password here,
# as a person would at sudo's prompt
password() { echo tester | sudo -S -p "" -v; }

# the record of job $1 as this user reads it; py CODE… checks it (the record is `job`)
record() { bromigos activity show "$1" --json; }
py() { python3 -c "import json, sys
doc = json.load(sys.stdin)
job = doc.get('job', doc)
$1"; }

running() {          # wait until job $1 runs, in its unit
    for _ in $(seq 40); do
        [[ $(record "$1" 2>/dev/null | py "print(job['state'] if job['steps'] else 'starting')" 2>/dev/null) == running ]] && break
        sleep 0.5
    done
    record "$1" | py "assert job['state'] == 'running' and job['steps'][0]['state'] == 'running', job"
    systemctl is-active "bromigos-job-$1.service"
}

case ${1:?which check} in
ok)
    password
    cat > ok.sh <<'SH'
echo "::stage 0 Getting ready"
echo "::step one running The first step"
echo "::step one done"
echo "::step two running The second step"
echo "a line of detail, for the log"
echo "::stage 100 All done"
SH
    # no sudo in front: `run` asks for root by itself (sudo, on this terminal)
    out=$(bromigos activity run --kind ci.check --title "CI: a job that ends well" --json -- sh "$d/ok.sh")
    id=$(py "print(job['id'])" <<<"$out")
    unit=bromigos-job-$id.service
    py "
assert job['state'] == 'succeeded' and job['exit_code'] == 0 and job['pct'] == 100, job
assert [(s['id'], s['label'], s['state']) for s in job['steps']] == [('one', 'The first step', 'done'), ('two', 'The second step', 'done')], job['steps']
assert job['unit'] == '$unit' and job['result'] == {'ok': True, 'summary': 'All done', 'undo': None}, job
assert job['command'] == ['sh', '$d/ok.sh'], job['command']
print('record:', job['id'], job['state'], [s['state'] for s in job['steps']])" <<<"$out"
    # the unit was real: systemd's own journal has it starting and ending
    sudo journalctl -u "$unit" --no-pager -o cat | tee unit.journal
    grep -q "bromigOS job: CI: a job that ends well" unit.journal
    # the readers, as someone who isn't root: both parse, and the log stays root's
    bromigos activity list --json | py "assert '$id' in [j['id'] for j in doc['jobs']], doc; print('list --json:', len(doc['jobs']), 'job(s)')"
    record "$id" | py "assert job['state'] == 'succeeded' and doc['log_tail'] is None, doc; print('show --json: reads; the log is not ours to read')"
    sudo bromigos activity show "$id" --json | py "assert 'a line of detail, for the log' in doc['log_tail'], doc; print('show --json as root: the log tail')"
    bromigos activity | grep -E "^done +.* CI: a job that ends well: All done$"
    # the files: the record for everyone, the log root's, nothing else left; on the state subvolume
    [[ $(stat -c "%a %U" "/var/lib/bromigos/activity/jobs/$id.json") == "644 root" ]]
    [[ $(sudo stat -c "%a %U" "/var/lib/bromigos/activity/jobs/$id.log") == "640 root" ]]
    [[ $(sudo sh -c "ls /var/lib/bromigos/activity/jobs/$id.*" | wc -l) == 2 ]]
    [[ $(readlink /var/lib/bromigos/activity) == server/activity ]]
    findmnt -no SOURCE,FSTYPE -T /var/lib/bromigos/server/activity
    echo ACTIVITY-DONE-OK
    ;;
failed)
    password
    cat > fail.sh <<'SH'
echo "::step one running The first step"
echo "::step one done"
echo "::step two running The second step"
echo "::error two The second step could not finish."
exit 7
SH
    rc=0
    out=$(sudo bromigos activity run --kind ci.check --title "CI: a job that fails" --json -- sh "$d/fail.sh") || rc=$?
    [[ $rc == 7 ]] || { echo "run ended with $rc, not the command's 7"; exit 1; }
    py "
assert job['state'] == 'failed' and job['exit_code'] == 7, job
assert job['error'] == {'step': 'two', 'words': 'The second step could not finish.', 'code': 'exit', 'fix': None}, job['error']
assert [s['state'] for s in job['steps']] == ['done', 'failed'], job['steps']
print('record:', job['id'], job['state'], 'at', job['error']['step'], 'exit', job['exit_code'])" <<<"$out"
    bromigos activity | grep -E "^failed +.* CI: a job that fails: stopped at The second step: The second step could not finish\.$"
    echo ACTIVITY-FAILED-OK
    ;;
detach-start)
    password
    cat > nap.sh <<'SH'
echo "::step nap running Sleeping"
sleep 25
echo "::step nap done"
echo "::stage 100 Woke up"
SH
    id=$(sudo bromigos activity run --kind ci.check --title "CI: a job that outlives its session" --detach -- sh "$d/nap.sh")
    echo "$id" > detached.id
    echo "${XDG_SESSION_ID:?no login session}" > detached.session
    running "$id"
    echo "started $id in session $XDG_SESSION_ID"
    ;;
detach-end)
    id=$(<detached.id) was=$(<detached.session)
    [[ ${XDG_SESSION_ID:?no login session} != "$was" ]] || { echo "still session $was: it never ended"; exit 1; }
    echo "session $was ended (this is $XDG_SESSION_ID); the job: $(record "$id" | py "print(job['state'])")"
    for _ in $(seq 80); do
        [[ $(record "$id" | py "print(job['state'])") == running ]] || break
        sleep 0.5
    done
    record "$id" | py "
took = job['ended_at'] - job['started_at']
assert job['state'] == 'succeeded' and job['pct'] == 100 and job['steps'][0]['state'] == 'done', job
assert took >= 25000, took
print('record:', job['id'], job['state'], 'after', took // 1000, 's')"
    echo ACTIVITY-DETACH-OK
    ;;
tour)
    password
    # a tiny plan: the tour asks this stand-in engine for it, and its apply is what the job runs
    cat > engine.py <<'PY'
import json, os, sys, tomllib
ids = tomllib.load(open(sys.argv[sys.argv.index("--from-answers") + 1], "rb"))["server"]["provision"]
if "--plan" in sys.argv:
    print(json.dumps({"items": [{"id": i, "name": i, "ports": [], "size_text": "", "internet": False} for i in ids]}))
    sys.exit(0)
for i in ids:
    print(f"::item {i} waiting", flush=True)
for k, i in enumerate(ids):
    print(f"::stage {100 * k // len(ids)} Installing {i}", flush=True)
    print(f"::item {i} installing", flush=True)
    print(f"::item {i} done", flush=True)
with open("/run/bromigos-activity-check.applied", "w") as f:
    f.write(f"uid={os.geteuid()} home={os.environ.get('HOME')} job={os.environ.get('BROMIGOS_ACTIVITY_JOB')}\n")
print("::stage 100 Done", flush=True)
PY
    printf '[server]\nprovision = ["ci-one", "ci-two"]\n' > answers.toml
    sudo rm -f /run/bromigos-activity-check.applied
    rc=0
    BROMIGOS_PROVISION_CMD="python3 $d/engine.py" BROMIGOS_INSTALL_ANSWERS=$d/answers.toml \
        bromigos welcome-console --provision apply > tour.out 2>&1 || rc=$?
    cat tour.out
    [[ $rc == 0 ]] || { echo "the tour's apply ended with $rc"; exit 1; }
    diff <(grep -E "^(item|stage) " tour.out) - <<'OUT'
item ci-one waiting
item ci-two waiting
stage 0 Installing ci-one
item ci-one installing
item ci-one done
stage 50 Installing ci-two
item ci-two installing
item ci-two done
stage 100 Done
OUT
    # the apply ran as root, in a job's unit, with root's home
    applied=$(cat /run/bromigos-activity-check.applied)
    echo "applied: $applied"
    [[ $applied == "uid=0 home=/root job="2* ]]
    bromigos activity list --json | py "
job = [j for j in doc['jobs'] if j['kind'] == 'app.install'][0]
assert job['state'] == 'succeeded' and job['title'] == 'Setting up this server', job
assert [(s['id'], s['state']) for s in job['steps']] == [('ci-one', 'done'), ('ci-two', 'done')], job['steps']
assert job['unit'] == 'bromigos-job-' + job['id'] + '.service' and job['command'][-2:] == ['--apply', '--json'], job
assert '$applied'.endswith('job=' + job['id']), job['id']
print('record:', job['id'], job['state'], [s['id'] for s in job['steps']])"
    echo ACTIVITY-TOUR-OK
    ;;
reboot-start)
    password
    cat > long.sh <<'SH'
echo "::step wait running Waiting for a restart"
sleep 900
SH
    id=$(sudo bromigos activity run --kind ci.check --title "CI: a job a restart interrupts" --detach -- sh "$d/long.sh")
    echo "$id" > reboot.id
    cat /proc/sys/kernel/random/boot_id > reboot.boot
    running "$id"
    sync
    # the restart, once this check has answered the harness
    sudo -n true
    (sleep 2; sudo -n systemctl reboot) > /dev/null 2>&1 < /dev/null &
    echo "started $id; restarting"
    ;;
reboot-end)
    id=$(<reboot.id)
    [[ $(cat /proc/sys/kernel/random/boot_id) != "$(<reboot.boot)" ]] || { echo "the same boot: it never restarted"; exit 1; }
    # as someone who can't write the record: it reads as interrupted, never as still running
    record "$id" | py "
assert job['state'] == 'interrupted' and job['error']['code'] == 'interrupted' and job['error']['step'] == 'wait', job
assert job['steps'][0]['state'] == 'skipped' and job['ended_at'], job
print('record:', job['id'], job['state'] + ':', job['error']['words'])"
    # and the file itself is closed: by the job as the system went down, or by the next start
    password
    sudo bromigos activity list > /dev/null
    py "assert job['state'] == 'interrupted', job; print('on disk:', job['state'] + ':', job['error']['words'])" \
        < "/var/lib/bromigos/activity/jobs/$id.json"
    [[ $(sudo sh -c "ls /var/lib/bromigos/activity/jobs/$id.*" | wc -l) == 2 ]]
    [[ $(systemctl is-active "bromigos-job-$id.service" || true) != active ]]
    # systemd stopped the unit cleanly, so the job itself should have said why
    py "assert job['error']['words'] == 'This computer was shut down or restarted while it ran.', job['error']" \
        < "/var/lib/bromigos/activity/jobs/$id.json"
    echo ACTIVITY-REBOOT-OK
    ;;
*)
    echo "activity-checks.sh: no check $1" >&2
    exit 2
    ;;
esac
