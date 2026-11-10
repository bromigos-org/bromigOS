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
#   activity-checks.sh control        a stand-in "replace a drive" job in a real unit asks, a second
#                                     job waits for its lock, `answer` lets it carry on, `cancel` is
#                                     refused while it says stopping isn't safe and stops a job that
#                                     says it is, and a job that fails raises an alert
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

until_state() {      # wait until job $1 is in state $2; then the record must say so
    for _ in $(seq 60); do
        [[ $(record "$1" 2>/dev/null | py "print(job['state'])" 2>/dev/null) == "$2" ]] && break
        sleep 0.5
    done
    record "$1" | py "assert job['state'] == '$2', (job['state'], job['error'])"
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
control)
    password
    go=/run/bromigos-activity-check.go
    sudo rm -f $go
    cat > replace.sh <<SH
echo "::cancel safe"
echo "::step swap running Swapping the drive"
echo "::ask swapped Take the old drive out of bay 2 and put the new one in. [swapped] I've swapped the drive"
read -r answer < "\$BROMIGOS_ACTIVITY_ANSWERS"
echo "the answer was: \$answer"
[ "\$answer" = swapped ] || exit 1
echo "::cancel unsafe The new drive is being filled."
echo "::step swap done"
echo "::step rebuild running Copying your files onto the new drive"
while [ ! -e $go ]; do sleep 0.2; done
echo "::stage 100 The new drive is in"
SH
    id=$(sudo bromigos activity run --kind drive.replace --title "CI: replacing a drive" --subject drive:bay-2 \
        --lock pool --detach -- sh "$d/replace.sh")
    unit=bromigos-job-$id.service
    until_state "$id" needs-you
    record "$id" | py "
q = job['question']
assert (q['id'], q['choices']) == ('swapped', [{'id': 'swapped', 'label': \"I've swapped the drive\", 'danger': False}]), q
assert job['waiting_for'] == 'you' and job['can'] == ['answer', 'cancel'] and job['locks'] == ['pool'], job
print('record:', job['id'], job['state'] + ':', q['text'])"
    systemctl is-active "$unit"
    bromigos activity show "$id" | grep -F "Answer with: sudo bromigos activity answer $id swapped"
    # a second job that needs the same lock waits behind it, in a unit of its own
    id2=$(sudo bromigos activity run --kind pool.check --title "CI: a job that waits its turn" --lock pool --detach -- true)
    until_state "$id2" waiting
    record "$id2" | py "
assert job['waiting_for'] == 'another job' and job['stage'] == 'Waiting for another job to finish: CI: replacing a drive', job
print('record:', job['id'], job['state'] + ':', job['stage'])"
    # the answer, as someone who isn't root: `answer` asks for root by itself. A wrong one is
    # refused before any password would be asked
    rc=0; bromigos activity answer "$id" nope 2> answer.err || rc=$?
    [[ $rc == 3 ]] || { echo "a wrong answer ended with $rc, not 3"; cat answer.err; exit 1; }
    [[ $(bromigos activity answer "$id" swapped) == "Answered: I've swapped the drive" ]]
    for _ in $(seq 40); do
        [[ $(record "$id" | py "print(job['cancel_note'])") == None ]] || break
        sleep 0.5
    done
    record "$id" | py "
assert job['state'] == 'running' and job['question'] is None and job['can'] == [], job
assert [(s['id'], s['state']) for s in job['steps']] == [('swap', 'done'), ('rebuild', 'running')], job['steps']
print('record:', job['id'], job['state'] + ', after:', job['notes'][-1]['words'])"
    # while it rebuilds, cancel is refused with the job's reason, and the unit goes on
    rc=0; bromigos activity cancel "$id" 2> cancel.err || rc=$?
    cat cancel.err
    [[ $rc == 3 ]] || { echo "cancel ended with $rc, not 3"; exit 1; }
    grep -qF "not stopped. The new drive is being filled." cancel.err
    grep -qF "To stop it anyway: sudo systemctl stop $unit" cancel.err
    systemctl is-active "$unit"
    sudo touch $go
    until_state "$id" succeeded
    until_state "$id2" succeeded
    sudo grep -qx "the answer was: swapped" "/var/lib/bromigos/activity/jobs/$id.log"
    [[ $(sudo sh -c "ls /var/lib/bromigos/activity/jobs/$id.*" | wc -l) == 2 ]]      # the pipe and the requests went
    # a job that says stopping is safe is stopped, unit and all
    id3=$(sudo bromigos activity run --kind ci.check --title "CI: a job that may be stopped" --cancel-safe --detach -- sleep 600)
    until_state "$id3" running
    [[ $(bromigos activity cancel "$id3") == "Stopped: CI: a job that may be stopped" ]]
    record "$id3" | py "assert job['state'] == 'cancelled' and job['can'] == [], job; print('record:', job['id'], job['state'])"
    for _ in $(seq 20); do                               # the job's process ends a moment after its record does
        [[ $(systemctl is-active "bromigos-job-$id3.service" || true) == active ]] || break
        sleep 0.5
    done
    [[ $(systemctl is-active "bromigos-job-$id3.service" || true) != active ]]
    # a job that fails is an alert as it ends (no waiting for the 15-minute timer), and a good
    # run clears it. The job's process runs the check just after it closes its record
    alerted() { bromigos alerts --json > alerts.json || true; py "print('activity.job:ci.alert' in [x['id'] for x in doc['alerts']])" < alerts.json; }
    sudo bromigos activity run --kind ci.alert --title "CI: a job that fails, for its alert" -- false > /dev/null 2>&1 || true
    for _ in $(seq 40); do [[ $(alerted) == True ]] && break; sleep 0.5; done
    py "
a = [x for x in doc['alerts'] if x['id'] == 'activity.job:ci.alert']
assert len(a) == 1 and a[0]['severity'] == 'needs_you' and a[0]['title'] == 'A job failed: CI: a job that fails, for its alert', doc['alerts']
print('alert:', a[0]['id'], a[0]['severity'] + ':', a[0]['title'])" < alerts.json
    sudo bromigos activity run --kind ci.alert --title "CI: a job that fails, for its alert" -- true > /dev/null
    for _ in $(seq 40); do [[ $(alerted) == False ]] && break; sleep 0.5; done
    py "assert 'activity.job:ci.alert' not in [x['id'] for x in doc['alerts']], doc['alerts']; print('alert: cleared')" < alerts.json
    echo ACTIVITY-CONTROL-OK
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
