// The rail (IA.md §2): the lab's name, Home, the machines and +, then the places, and Settings at
// the foot. At phone width it becomes the bottom bar (styles/shell.css): the places only.
import { Icon, shapeIcon } from "@/components/ui";
import type { Board, Machine, MachineKind } from "@/lib/api/types";
import { useLab } from "@/lib/lab";
import { href, type Place } from "@/lib/routes";

export const KIND_ICON: Record<MachineKind, string> = {
  server: "i-rack",
  storage: "i-storage",
  node: "i-rack",
  desktop: "i-desktop",
  other: "i-module",
};
const KIND_WORD: Record<MachineKind, string> = {
  server: "a server",
  storage: "a storage server",
  node: "a lab node",
  desktop: "a bromigOS desktop",
  other: "a machine",
};

const PLACES: { place: Place; icon: string; hint: string }[] = [
  { place: "den", icon: "i-tv", hint: "Den: what is playing on the TVs, the library, requests, and game worlds" },
  { place: "cameras", icon: "i-camera", hint: "Cameras: the wall and today's events. Shown because a machine runs the Cameras app." },
  { place: "supply", icon: "i-supply", hint: "Supply: what runs, what the lab can run, and what changes tonight" },
  { place: "data", icon: "i-drive", hint: "Data: drives, backups, shares and moving in. Is my stuff safe?" },
  { place: "network", icon: "i-router", hint: "Network: the devices on the home network, ad blocking, and reaching home from away" },
  { place: "people", icon: "i-people", hint: "People: the household, what each can see, and the ways in" },
];

function machineHint(m: Machine): string {
  const parts = [`${m.name}: ${KIND_WORD[m.kind]}`];
  if (m.roles.length) parts[0] += ` with ${m.roles.join(", ")}`;
  parts.push(m.state_word);
  if (m.updates?.count)
    parts.push(`${m.updates.count} update${m.updates.count === 1 ? "" : "s"} waiting${m.updates.security ? ", one a security update (the red arrow)" : " (a grey arrow; a red one would be a security update)"}`);
  if (m.here) parts.push("this page is served by it");
  return `${parts.join(". ")}. Opens its page; picking it also scopes Den, Supply and Data to it.`;
}

/** Cameras earns its rail entry only when a machine runs it (UniFi OS's rule, IA.md §1). */
const hasCameras = (b: Board | null) => !!b?.apps.some((t) => t.installed && (t.group === "cameras" || t.id === "cameras"));

export function Rail() {
  const { route, board, scope } = useLab();
  const b = board.state === "ok" ? board.doc : null;
  const labName = b?.lab.name ?? "MYLAB";
  const on = (place: Place) => route.place === place || (place === "supply" && route.place === "app");
  const cur = (yes: boolean) => (yes ? { "aria-current": "page" as const } : {});
  return (
    <nav className="sh-rail" aria-label="The lab">
      <a
        className="sh-lab"
        href="#settings/lab"
        title={`Your lab: ${labName}.${b?.lab.address ? ` Its own address is ${b.lab.address}, and every server also serves this page at its own name.` : ""} Opens the lab's settings.`}
      >
        {labName}
      </a>
      <a className={`sh-i${route.place === "home" ? " on" : ""}`} href="#home" title="Home: is the lab all right, and what do I do first?" aria-label="Home" {...cur(route.place === "home")}>
        <Icon id="i-home" />
      </a>
      <span className="sh-sep" aria-hidden="true" />
      {(b?.machines ?? []).map((m) => {
        const lit = (route.place === "machine" && route.id === m.name) || (!!scope && scope === m.name && route.place !== "home");
        return (
          <a
            key={m.name}
            className={`sh-i sh-m${lit ? " on" : ""}`}
            href={href("machine", "", m.name)}
            title={machineHint(m)}
            aria-label={`${m.name}, ${m.state_word}`}
            data-m={m.name}
            {...cur(route.place === "machine" && route.id === m.name)}
          >
            <Icon id={KIND_ICON[m.kind]} />
            <svg className={`i sh-sd ${m.state === "unknown" ? "unk" : m.state}`} aria-hidden="true" focusable="false">
              <use href={`#${shapeIcon(m.state)}`} />
            </svg>
            {!!m.updates?.count && (
              <svg className={`i sh-up${m.updates.security ? " sec" : ""}`} aria-hidden="true" focusable="false">
                <use href="#i-update" />
              </svg>
            )}
            <span className="sh-rl">{m.name}</span>
          </a>
        );
      })}
      <a className={`sh-i sh-add${route.sheet === "add-machine" ? " on" : ""}`} href="#add-machine" title="Add a machine: a new box joins the lab with a one-time code" aria-label="Add a machine">
        <Icon id="i-add" />
      </a>
      <span className="sh-sep" aria-hidden="true" />
      {PLACES.filter((p) => p.place !== "cameras" || hasCameras(b)).map((p) => (
        <a key={p.place} className={`sh-i${on(p.place) ? " on" : ""}`} href={href(p.place)} title={p.hint} aria-label={p.place[0].toUpperCase() + p.place.slice(1)} {...cur(on(p.place))}>
          <Icon id={p.icon} />
        </a>
      ))}
      <span className="sh-grow" aria-hidden="true" />
      <a className={`sh-i${on("settings") ? " on" : ""}`} href="#settings" title="Settings: how the lab is set. Notifications, power, recovery, the lab itself" aria-label="Settings" {...cur(on("settings"))}>
        <Icon id="i-gear" />
      </a>
    </nav>
  );
}
