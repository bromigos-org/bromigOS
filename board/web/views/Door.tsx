// The door (DESIGN.md §1, IA.md §2): what anyone on the home network sees before signing in.
// The server's name, the household's apps to open, and the ways in. No state, no readings, no
// versions, no addresses beyond the app links. The sign-in sheet takes the one-time code.
import { useEffect, useRef, useState } from "react";
import { Icon, IconButton, IconLink, Planned } from "@/components/ui";
import type { Door as DoorDoc } from "@/lib/api/types";
import { ApiError } from "@/lib/api/errors";
import { holoIcon } from "@/lib/icons";
import { useLab } from "@/lib/lab";
import { Sheet } from "@/shell/Shell";

function Ways({ door }: { door: DoorDoc }) {
  return (
    <section className="panel" title="Sign in. None of the ways types a password into this page.">
      <h2 className="ph">
        <span>SIGN IN</span>
        <span className="tags">
          <span className="chip lit" title="The code at the server works with no internet and with Bromigos unreachable, so an account is never the only way in.">
            WORKS OFFLINE
          </span>
          <span className="chip" title="No way in types a password into this page">
            NO PASSWORD
          </span>
        </span>
      </h2>
      <div className="ways three">
        <div className="way" title="With your Bromigos account: the page shows a short code for account.bromigos.org/device, and you approve where you are already signed in. Planned: the account service is not live yet.">
          <span className="over muted">
            BROMIGOS ACCOUNT <Planned hint="Planned: the account service is not live yet" />
          </span>
          <ul className="icol tight q">
            <li>
              <Icon id="i-qr" size={20} />
              account.bromigos.org/device
            </li>
            <li>
              <Icon id="s-wait" size={20} />
              Approve where you're signed in
            </li>
          </ul>
        </div>
        <div className="way" title={door.signin.phone ? "With your phone: BRODEC shows the same code; you approve with a fingerprint." : "With your phone: BRODEC shows the same code and you approve with a fingerprint. Planned: the phone's approval isn't built yet."}>
          <span className="over muted">WITH YOUR PHONE {!door.signin.phone && <Planned hint="Planned: approving a browser from BRODEC isn't built yet" />}</span>
          <ul className={`icol tight${door.signin.phone ? "" : " q"}`}>
            <li>
              <Icon id="i-qr" size={20} />
              Scan or match
            </li>
            <li>
              <Icon id="i-finger" size={20} />
              Fingerprint
            </li>
          </ul>
        </div>
        <div className="way" title="At the server: a one-time code printed at the console or over SSH. Good for ten minutes and one use. Works with no phone, no account and no internet.">
          <span className="over muted">AT THE SERVER {!door.signin.code && <Planned hint="Planned: this server doesn't offer the code yet" />}</span>
          <pre>sudo bromigos server board code</pre>
          <ul className="icol tight">
            <li>
              <Icon id="i-snooze" size={20} />
              10 minutes
            </li>
            <li>
              <Icon id="s-done" size={20} />
              One use
            </li>
          </ul>
          {door.signin.code && (
            <div className="acts">
              <IconLink icon="i-signin" kind="big" move="slide" href="#signin" label="Sign in with a code" hint="Sign in: type the one-time code the server printed" />
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function Apps({ door }: { door: DoorDoc }) {
  return (
    <section className="panel quiet" title="What anyone on the home network sees without signing in: the apps to open, and nothing else">
      <h2 className="ph muted">
        <span>ON {door.server.name.toUpperCase()}</span>
        <span
          className="lockic"
          role="img"
          aria-label="What the door never shows"
          title="The door never shows: drives or backups; versions or updates; activity or logs; Supply or controls. Who sees what is set in People › Household."
        >
          <Icon id="i-lock" size={20} />
        </span>
        {!door.tiles.length && (
          <span className="st unk" title="Nothing yet: no app has been added">
            <Icon id="s-unk" size={16} />
            nothing yet
          </span>
        )}
      </h2>
      {door.tiles.length ? (
        <div className="door-tiles">
          {door.tiles.map((t) => {
            const ic = holoIcon(t.holo);
            return (
              <a key={t.id} className="tile" href={t.open.url} title={`${t.job}: ${t.app}. Opens it at ${t.open.url}`} rel="noreferrer">
                <span className={`plate${ic.known ? "" : " off"}`} aria-hidden="true">
                  <Icon id={ic.id} />
                </span>
                <span className="nm">
                  <b>{t.job}</b>
                  <span className="app">{t.app}</span>
                </span>
              </a>
            );
          })}
        </div>
      ) : (
        <ul className="icol q">
          <li title="Apps appear here to open once the owner adds them">
            <Icon id="i-supply" size={20} />
            Apps appear here to open
          </li>
          <li title="No readings, drives, backups or controls show before sign-in">
            <Icon id="i-vpn" size={20} />
            No readings or controls before sign-in
          </li>
        </ul>
      )}
    </section>
  );
}

export function SignIn() {
  const { signIn, door } = useLab();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [why, setWhy] = useState<string | null>(null);
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => field.current?.focus(), []);
  const name = door.state === "ok" ? door.doc.server.name : "the server";
  return (
    <Sheet title="Sign in" close="#home" closeHint="Close: back to the door">
      <div className="pg">
        <div className="body stack">
          <section className="panel" title="Sign in with a one-time code: proof that you can sit at the server, or reach it over SSH">
            <h3>
              <span>AT THE SERVER</span>
              <span className="chip" title="Good for ten minutes and one use">
                10 MIN · ONE USE
              </span>
            </h3>
            <ol className="flow">
              <li title={`Step 1: at ${name}'s console, or over SSH, run this. It prints a code.`}>
                <span>
                  <span className="num">1</span>
                </span>
                Make a code at {name}
                <code>sudo bromigos server board code</code>
              </li>
              <li title="Step 2: type it here. Spaces and case don't matter.">
                <span>
                  <span className="num">2</span>
                </span>
                Type it here
              </li>
            </ol>
            <form
              className="signin-form"
              onSubmit={(e) => {
                e.preventDefault();
                if (!code.trim() || busy) return;
                setBusy(true);
                setWhy(null);
                signIn(code).then(
                  () => {
                    window.location.hash = "#home";
                  },
                  (err) => {
                    setBusy(false);
                    setWhy(err instanceof ApiError ? err.words : "The server didn't answer.");
                    field.current?.select();
                  },
                );
              }}
            >
              <label className="fld">
                <span className="k">One-time code</span>
                <input
                  ref={field}
                  className="field"
                  name="code"
                  autoComplete="one-time-code"
                  autoCapitalize="characters"
                  spellCheck={false}
                  maxLength={64}
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  title="The one-time code the server printed"
                  aria-invalid={!!why}
                  aria-describedby={why ? "signin-why" : undefined}
                />
              </label>
              <div className="row">
                <IconButton type="submit" icon="i-signin" move="slide" kind={code.trim() && !busy ? "big" : "off"} label="Sign in" hint="Sign in: this browser becomes the owner's for 30 days" aria-disabled={!code.trim() || busy} />
                {why && (
                  <p className="signin-err" id="signin-why" role="alert">
                    {why}
                  </p>
                )}
              </div>
            </form>
          </section>
        </div>
      </div>
    </Sheet>
  );
}

export function Door({ withSignIn }: { withSignIn: boolean }) {
  const { door } = useLab();
  if (door.state === "loading") return null;
  if (door.state === "error")
    return (
      <div className="unreach" title="The page loaded, but the server's board service didn't answer">
        <Icon id="i-offline" size={40} />
        <p>{door.error.words} The board service may be starting; this page tries again when you reload it.</p>
      </div>
    );
  return (
    <>
      <section className={`page${withSignIn ? " sh-under" : ""}`} aria-label="The door" inert={withSignIn || undefined}>
        <div className="pg">
          <div className="body stack">
            <Ways door={door.doc} />
            <div className="two">
              <Apps door={door.doc} />
            </div>
          </div>
        </div>
      </section>
      {withSignIn && <SignIn />}
    </>
  );
}
