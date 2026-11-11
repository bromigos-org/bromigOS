// People (IA.md §2). Ways in: "Where am I signed in, and how does another browser get in?"
// The signed-in browsers are the service's own list (GET /api/session), and ending one is its
// DELETE /api/session/ID. Signing a browser in is the one-time code, printed at the server.
// Household stays planned: the board has one role today, the lab's owner.
import { useEffect, useState } from "react";
import { Icon, IconButton, Planned, State } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import type { Browser, Session } from "@/lib/api/types";
import { useLab } from "@/lib/lab";
import { ago, when } from "@/lib/time";
import { shownUrl } from "@/lib/url";
import { Tabs } from "@/shell/Shell";

const day = (ms: number) => new Date(ms).toLocaleDateString("en-GB", { day: "numeric", month: "short" });

function BrowserRow({ b, now, onSaid }: { b: Browser; now: number; onSaid: (words: string, bad: boolean) => void }) {
  const { signOut, signOutBrowser, rereadSession } = useLab();
  const [busy, setBusy] = useState(false);
  const facts = [
    b.current ? "this browser" : null,
    b.signed_in_at !== null ? `signed in ${when(b.signed_in_at, now)}` : null,
    !b.current && b.last_seen_at !== null ? `last used ${ago(b.last_seen_at, now)}` : null,
    b.expires_at !== null ? `until ${day(b.expires_at)}` : null,
  ].filter(Boolean);
  return (
    <li className={b.current ? "here" : ""} title={`${b.name}${b.current ? ": the browser you are using" : ""}. ${facts.join(", ")}`}>
      <Icon id="i-browser" size={20} />
      <span className="grow">
        <b>{b.name}</b>
        <br />
        <span className="small muted">{facts.join(" · ")}</span>
      </span>
      <IconButton
        icon="i-signout"
        move="slide"
        label={b.current ? "Sign this browser out" : `Sign out ${b.name}`}
        hint={b.current ? "Sign this browser out: it goes back to the door, and needs a new code to come in again" : `Sign out ${b.name}: it goes back to the door at its next request, and needs a new code to come in again`}
        aria-disabled={busy}
        onClick={() => {
          if (busy) return;
          setBusy(true);
          (b.current ? signOut() : signOutBrowser(b.id)).then(
            () => {
              setBusy(false);
              if (!b.current) onSaid(`${b.name} is signed out.`, false);
            },
            (e) => {
              setBusy(false);
              onSaid(e instanceof ApiError ? e.words : "The server couldn't do that.", true);
              rereadSession(); // it may have signed out by itself meanwhile: show the server's list
            },
          );
        }}
      />
    </li>
  );
}

function Browsers({ s, now }: { s: Session; now: number }) {
  const [said, setSaid] = useState<{ words: string; bad: boolean } | null>(null);
  const list = [...s.browsers].sort((a, b) => Number(b.current) - Number(a.current) || (b.last_seen_at ?? 0) - (a.last_seen_at ?? 0));
  return (
    <section className="panel" title="The browsers signed in to this board as the lab's owner. Each stays signed in for 30 days, and any of them can sign another out">
      <h2 className="ph">
        <span>
          <Icon id="i-browser" size={16} />
          SIGNED-IN BROWSERS · {list.length}
        </span>
        <span className="tags">
          <span className="chip" title="A browser stays signed in for 30 days from its sign-in, then needs a new code">
            30 DAYS
          </span>
          <span className="chip" title="Everyone signed in today is the lab's owner: the board has no other role yet">
            OWNER
          </span>
        </span>
      </h2>
      {list.length ? (
        <ul className="rows wide pp-browsers">
          {list.map((b) => (
            <BrowserRow key={b.id} b={b} now={now} onSaid={(words, bad) => setSaid({ words, bad })} />
          ))}
        </ul>
      ) : (
        <p className="small muted">The server lists no signed-in browser.</p>
      )}
      {said && (
        <p className={said.bad ? "signin-err" : "small"} role="status">
          {said.words}
        </p>
      )}
      <pre className="pp-cmd">{`# the same list, at the server\nsudo bromigos server board sessions\n# sign every browser out at once\nsudo bromigos server board sessions --end-all`}</pre>
    </section>
  );
}

function NewCode({ address }: { address: string | null }) {
  return (
    <section className="panel" title="How another browser gets in: a one-time code, printed at the server, typed at the door. No password is ever typed into this page">
      <h2 className="ph">
        <span>
          <Icon id="i-signin" size={16} />
          SIGN ANOTHER BROWSER IN
        </span>
        <span className="tags">
          <span className="chip lit" title="The code works with no internet and with Bromigos unreachable">
            WORKS OFFLINE
          </span>
          <span className="chip" title="No way in types a password into this page">
            NO PASSWORD
          </span>
        </span>
      </h2>
      <ol className="flow pp-steps">
        <li title="Step 1, at the server's console or over SSH: it prints a code. The code is good for ten minutes and for one use.">
          <span>
            <span className="num">1</span>
            <Icon id="i-rack" size={20} />
          </span>
          Make a code at the server<code>sudo bromigos server board code</code>
        </li>
        <li title={`Step 2, on the other browser: open the lab's address${address ? ` (${address})` : ""}. It shows the door.`}>
          <span>
            <span className="num">2</span>
            <Icon id="i-browser" size={20} />
          </span>
          Open the lab there{address && <code>{shownUrl(address)}</code>}
        </li>
        <li title="Step 3: press Sign in at the door and type the code. That browser is then in this list.">
          <span>
            <span className="num">3</span>
            <Icon id="i-signin" size={20} />
          </span>
          Type the code at the door
        </li>
      </ol>
      <ul className="icol tight pp-facts">
        <li title="A code that nobody used stops working ten minutes after it was printed">
          <Icon id="i-snooze" size={20} />
          10 minutes
        </li>
        <li title="A code signs one browser in, once. A used code is worth nothing">
          <Icon id="s-done" size={20} />
          One use
        </li>
      </ul>
      <p className="small muted" title="Two more ways in are drawn in the design and not built">
        With your phone (BRODEC) and with a Bromigos account <Planned hint="Planned: approving a browser from BRODEC, and signing in with a Bromigos account, aren't built yet. The code at the server stays, so an account is never the only way in" />
      </p>
    </section>
  );
}

/** People › Ways in. */
export function Ways() {
  const { session, board, now: clock, rereadSession } = useLab();
  const now = clock();
  // the list is the server's: read it again whenever this tab is opened
  useEffect(() => rereadSession(), [rereadSession]);
  const s = session.state === "ok" ? session.doc : null;
  const address = board.state === "ok" ? board.doc.lab.address : null;
  return (
    <>
      <Tabs place="people" label="People" />
      {!s ? (
        <p className="small muted" role="status">
          {session.state === "error" ? "The signed-in browsers couldn't be read: the server isn't answering." : "Reading the signed-in browsers…"}
        </p>
      ) : (
        <div className="stack">
          <section className="panel" title="How you are signed in here">
            <div className="rdrow pp-rd">
              <div className="rd" title="How many browsers are signed in to this board">
                <span className="k">Signed in</span>
                <span className="v">
                  {s.browsers.length}
                  <small>{s.browsers.length === 1 ? "browser" : "browsers"}</small>
                </span>
              </div>
              <div className="rd" title="The browser you are using, as the server named it when it signed in">
                <span className="k">This browser</span>
                <span className="v m">{s.browser?.name ?? "·"}</span>
              </div>
              <div className="rd" title="When this browser's sign-in ends by itself: 30 days after it signed in">
                <span className="k">Signed in until</span>
                <span className={`v m${s.expires_at === null ? " q" : ""}`}>{s.expires_at !== null ? day(s.expires_at) : "·"}</span>
              </div>
              <div className="rd" title="What this browser may do: the owner sees and changes everything the board offers">
                <span className="k">As</span>
                <span className="v m">
                  <State shape="ok" word={s.role ?? "owner"} />
                </span>
              </div>
            </div>
          </section>
          <div className="two">
            <Browsers s={s} now={now} />
            <NewCode address={address} />
          </div>
        </div>
      )}
    </>
  );
}
