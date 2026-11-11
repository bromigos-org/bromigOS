// An error boundary: when a part of the page throws while it draws, that part alone is
// replaced by a plain sentence, and the rest of the page (the rail, the other panels, the
// strip) keeps working. It tries again when what it shows changes (`again`: the route, say).
import { Component, type ReactNode } from "react";
import { Icon } from "./ui";

export class Boundary extends Component<{ what: string; again?: string; children: ReactNode }, { broken: boolean; at: string | undefined }> {
  state = { broken: false, at: undefined as string | undefined };

  static getDerivedStateFromError() {
    return { broken: true };
  }

  static getDerivedStateFromProps(props: { again?: string }, state: { broken: boolean; at: string | undefined }) {
    // a new route (or whatever `again` names) gets a fresh try
    return props.again !== state.at ? { broken: false, at: props.again } : null;
  }

  componentDidCatch(error: unknown) {
    console.warn(`The board couldn't show ${this.props.what}:`, error);
  }

  render() {
    if (!this.state.broken) return this.props.children;
    return (
      <div className="broken" role="alert" title={`${this.props.what} couldn't be shown. The rest of the page still works.`}>
        <Icon id="s-unk" size={20} />
        <span>
          {this.props.what} couldn't be shown. The rest of the page still works; reloading the page may bring it back.
        </span>
      </div>
    );
  }
}
