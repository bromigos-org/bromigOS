"""bromigos rollback (stand-in): fixtures' rollback.json, read-only."""
import json


def run(args, js, F):
    doc = F.load("rollback")
    doc = {"channel": doc} if "rollback" == "channel" else doc
    print(json.dumps(dict({"schema": 1}, **doc)))
