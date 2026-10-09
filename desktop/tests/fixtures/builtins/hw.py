"""bromigos hw (stand-in): fixtures' hw.json, read-only."""
import json


def run(args, js, F):
    doc = F.load("hw")
    doc = {"channel": doc} if "hw" == "channel" else doc
    print(json.dumps(dict({"schema": 1}, **doc)))
