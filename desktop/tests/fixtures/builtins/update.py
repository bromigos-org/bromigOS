"""bromigos update (stand-in): --check answers from fixtures' update.json; an update itself
needs a terminal (sudo), so it isn't pretended."""
import json


def run(args, js, F):
    if "--check" not in args:
        print("bromigos update stand-in: only --check is pretended", flush=True)
        return 1
    print(json.dumps({"schema": 1, "check": F.load("update")}))
