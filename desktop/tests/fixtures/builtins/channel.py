"""bromigos channel (stand-in): fixtures' channel.json, read-only."""
import json


def run(args, js, F):
    doc = F.load("channel")
    doc = {"channel": doc} if "channel" == "channel" else doc
    print(json.dumps(dict({"schema": 1}, **doc)))
