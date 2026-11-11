// The small parts every page uses, drawn as the prototype draws them. The rules they keep:
// every control has a hint (title: what it is and what it does) and an accessible name; a state
// is a shape and a word, never colour alone; a mark (PLANNED) is an outline that never takes a
// state colour (IA.md §4).
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from "react";
import type { Shape } from "@/lib/api/types";

export type IconSize = 16 | 20 | 24 | 32 | 40;
/** How an icon moves once on hover (DESIGN.md §5): its own verb. */
export type Move = "beat" | "turn" | "wind" | "lift" | "drop" | "slide" | "out" | "sweep";

export function Icon({ id, size = 24, move, className = "" }: { id: string; size?: IconSize; move?: Move; className?: string }) {
  const cls = ["i", size !== 24 ? `s${size}` : "", move ? `m-${move}` : "", className].filter(Boolean).join(" ");
  return (
    <svg className={cls} aria-hidden="true" focusable="false">
      <use href={`#${id}`} />
    </svg>
  );
}

type BtnProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "title"> & {
  icon: string;
  /** The accessible name: a few words. */
  label: string;
  /** The hover hint: what it is and what it does. */
  hint: string;
  move?: Move;
  size?: IconSize;
  kind?: "big" | "danger" | "off" | "on";
};

/** A control that is an icon: the family's square button with its name and its hint. */
export function IconButton({ icon, label, hint, move = "beat", size, kind, className = "", type = "button", ...rest }: BtnProps) {
  return (
    <button type={type} className={["ib", kind ?? "", className].filter(Boolean).join(" ")} aria-label={label} title={hint} {...rest}>
      <Icon id={icon} move={move} size={size ?? (kind === "big" ? 32 : 24)} />
    </button>
  );
}

type LinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "title"> & {
  icon: string;
  label: string;
  hint: string;
  move?: Move;
  kind?: "big" | "danger" | "on";
};

export function IconLink({ icon, label, hint, move = "out", kind, className = "", ...rest }: LinkProps) {
  return (
    <a className={["ib", kind ?? "", className].filter(Boolean).join(" ")} aria-label={label} title={hint} {...rest}>
      <Icon id={icon} move={move} size={kind === "big" ? 32 : 24} />
    </a>
  );
}

const SHAPE: Record<Shape, string> = { ok: "s-ok", warn: "s-warn", down: "s-down", unknown: "s-unk" };
const STCLASS: Record<Shape, string> = { ok: "ok", warn: "warn", down: "down", unknown: "unk" };

/** A state: its shape, then its word (BRODEC's DESIGN.md, "LAB"). "busy" is the half ring:
 *  starting, updating, checking: on its way, not yet well. */
export function State({ shape, word, hint }: { shape: Shape | "busy"; word: string; hint?: string }) {
  return (
    <span className={`st ${shape === "busy" ? "busy" : STCLASS[shape]}`} title={hint}>
      <Icon id={shape === "busy" ? "s-start" : SHAPE[shape]} size={16} />
      {word}
    </span>
  );
}

export const shapeIcon = (s: Shape) => SHAPE[s];

/** The planned mark: dashed, never a state colour. Its hint says what isn't built. */
export function Planned({ hint = "Planned: not built yet" }: { hint?: string }) {
  return (
    <span className="pl" title={hint}>
      planned
    </span>
  );
}

export function Panel({ title, hint, tags, warn, quiet, children, className = "" }: {
  title?: ReactNode;
  hint?: string;
  tags?: ReactNode;
  warn?: boolean;
  quiet?: boolean;
  children?: ReactNode;
  className?: string;
}) {
  const cls = ["panel", warn ? "is-warn" : "", quiet ? "quiet" : "", className].filter(Boolean).join(" ");
  return (
    <section className={cls} title={hint}>
      {title !== undefined && (
        <h3>
          <span>{title}</span>
          {tags}
        </h3>
      )}
      {children}
    </section>
  );
}
