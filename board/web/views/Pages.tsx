// One page at a time, by route (lib/routes.ts). A page not built yet shows its place, its tabs
// and the planned mark: never a made-up reading.
import type { ReactNode } from "react";
import { Icon, Planned } from "@/components/ui";
import { useLab } from "@/lib/lab";
import { PLACE_NAME, TABS, type Place } from "@/lib/routes";
import { Sheet, Tabs } from "@/shell/Shell";

const PLACE_ICON: Record<Place, string> = {
  home: "i-home",
  machine: "i-rack",
  den: "i-tv",
  cameras: "i-camera",
  supply: "i-supply",
  app: "i-supply",
  data: "i-drive",
  network: "i-router",
  people: "i-people",
  activity: "i-job",
  settings: "i-gear",
  signin: "i-signin",
};

export function Stub({ place, title }: { place: Place; title: string }) {
  return (
    <div className="stub" title={`${title}: this page isn't built yet. Planned.`}>
      <Icon id={PLACE_ICON[place]} size={40} />
      <h2>{title}</h2>
      <Planned hint="Planned: this page is drawn in the design and comes in a following change" />
    </div>
  );
}

export function Page({ label, children, under }: { label: string; children: ReactNode; under?: boolean }) {
  return (
    <section className={`page${under ? " sh-under" : ""}`} aria-label={label} inert={under || undefined}>
      {children}
    </section>
  );
}

function AddMachine() {
  return (
    <Sheet title="Add a machine" close="#home" closeHint="Close: back to Home">
      <div className="pg">
        <div className="body stack">
          <section className="panel" title="How a machine joins the lab: a one-time join code, made on a machine that is in, used on the one coming in">
            <h3>
              <span>ADD A MACHINE</span>
              <span className="tags">
                <span className="chip" title="A join code works once, and stops working after a day if nobody uses it">
                  ONE-TIME CODE
                </span>
                <Planned hint="Planned: today this page shows the server it runs on; other machines of the lab appear here in a later change" />
              </span>
            </h3>
            <ol className="flow lb-join">
              <li title="Step 1, on a machine already in the lab: it prints the code, a QR code of it, and the plain command.">
                <span>
                  <span className="num">1</span>
                  <Icon id="i-qr" size={20} />
                </span>
                Make a join code<code>bromigos lab network join</code>
              </li>
              <li title="Step 2, on the new machine: paste the code. The Server installer asks for it on its Network step; a Field Kit stick can carry it.">
                <span>
                  <span className="num">2</span>
                  <Icon id="i-signin" size={20} />
                </span>
                Use it there<code>installer › Network</code>
              </li>
              <li title="Step 3: nothing to do. The new machine reports to the lab and appears in the rail by itself, with its state.">
                <span>
                  <span className="num">3</span>
                  <Icon id="i-home" size={20} />
                </span>
                It appears here
              </li>
            </ol>
          </section>
        </div>
      </div>
    </Sheet>
  );
}

/** A place with tabs, before its page is built. */
function Placeholder({ place, id }: { place: Place; id?: string | null }) {
  const { route } = useLab();
  const tabs = TABS[place];
  const tab = tabs?.find((t) => t.id === route.tab);
  const title = place === "machine" ? `${id} › ${tab?.label ?? "Set-up"}` : tab ? `${PLACE_NAME[place]} › ${tab.label}` : PLACE_NAME[place];
  return (
    <Page label={title}>
      {tabs && <Tabs place={place} id={id} label={place === "machine" ? `${id}'s tabs` : PLACE_NAME[place]} />}
      <Stub place={place} title={title} />
    </Page>
  );
}

export function Pages() {
  const { route } = useLab();
  switch (route.place) {
    case "home":
      return (
        <>
          <Page label="Home" under={route.sheet === "add-machine"}>
            <Stub place="home" title="Home" />
          </Page>
          {route.sheet === "add-machine" && <AddMachine />}
        </>
      );
    case "machine":
      return <Placeholder place="machine" id={route.id} />;
    case "app":
      return (
        <Page label={`App ${route.id}`}>
          <Stub place="app" title={`Supply › ${route.id}`} />
        </Page>
      );
    case "cameras":
      return (
        <Page label="Cameras">
          <Stub place="cameras" title="Cameras" />
        </Page>
      );
    case "signin":
      return null;
    default:
      return <Placeholder place={route.place} />;
  }
}
