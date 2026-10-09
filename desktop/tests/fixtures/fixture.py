"""The stand-ins' shared state: each stand-in command (fixtures/bin/) keeps the machine it
pretends to be in $BROMIGOS_FIXTURE_STATE/<name>.json (a temp dir the test or the render
makes), seeded from fixtures/<name>.json on first use, so a change one command makes is
what the next read sees. Without $BROMIGOS_FIXTURE_STATE the seed is read and never written.
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    d = os.environ.get("BROMIGOS_FIXTURE_STATE")
    p = os.path.join(d, name + ".json") if d else None
    if p and os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    with open(os.path.join(HERE, name + ".json")) as f:
        return json.load(f)


def save(name, state):
    d = os.environ.get("BROMIGOS_FIXTURE_STATE")
    if not d:
        return
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, name + ".json.tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, os.path.join(d, name + ".json"))


def log(name, argv):
    """Every call, for tests that check what was asked: $BROMIGOS_FIXTURE_STATE/<name>.log."""
    d = os.environ.get("BROMIGOS_FIXTURE_STATE")
    if d:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name + ".log"), "a") as f:
            f.write(json.dumps(argv) + "\n")


def die(msg, code=1):
    print(msg, file=sys.stderr)
    sys.exit(code)


deepcopy = copy.deepcopy
