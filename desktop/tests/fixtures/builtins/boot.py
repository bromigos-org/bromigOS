"""bromigos boot (stand-in): `boot theme [status]` answers from fixtures' boot.json; on, off and
apply need root (a terminal), so they aren't pretended."""
import json


def run(args, js, F):
    if args[:1] != ["theme"] or (len(args) > 1 and args[1] != "status"):
        print("bromigos boot stand-in: only `boot theme status` is pretended")
        return 1
    print(json.dumps(dict({"schema": 1}, **F.load("boot"))))
