"""bromigos profile (stand-in): who you are, kept in fixtures' profile.json."""
import json

FIELDS = ("name", "full_name", "pronouns")


def run(args, js, F):
    st = F.load("profile")
    verb = args[0] if args else "show"
    if verb == "set":
        if len(args) != 3 or args[1] not in FIELDS:
            print(json.dumps({"schema": 1, "ok": False, "error": "set name|full_name|pronouns VALUE"}))
            return 1
        st[args[1]] = args[2] or None
    elif verb == "alias":
        for v in args[2:]:
            if args[1] == "add" and v not in st["aliases"]:
                st["aliases"].append(v)
            elif args[1] == "remove" and v in st["aliases"]:
                st["aliases"].remove(v)
    elif verb == "address":
        if args[1] == "set":
            st["address"] = list(args[2:])
        for v in args[2:]:
            if args[1] == "add" and v not in st["address"]:
                st["address"].append(v)
            elif args[1] == "remove" and v in st["address"]:
                st["address"].remove(v)
    if verb != "show":
        F.save("profile", st)
    you = {k: st.get(k) for k in ("name", "full_name", "pronouns", "aliases", "address")}
    doc = {"schema": 1, "path": "~/.config/bromigos/profile.toml", "exists": True,
           "addressed_as": (st.get("address") or [None])[0] or st.get("name"), "you": you}
    print(json.dumps(doc) if js else json.dumps(you))
