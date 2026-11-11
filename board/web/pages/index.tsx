// The Lab board: one page; the hash picks what it shows (lib/routes.ts). Before the session is
// known nothing is drawn, so the door and the board never flash into each other.
import { LabProvider, useLab } from "@/lib/lab";
import { Shell } from "@/shell/Shell";
import { Door } from "@/views/Door";
import { Pages } from "@/views/Pages";

function Board() {
  const { session, door, route } = useLab();
  if (session.state === "loading" && door.state === "loading") return <div className="boot" />;
  const signedIn = session.state === "ok" && session.doc.signed_in;
  return <Shell signedIn={signedIn}>{signedIn ? <Pages /> : <Door withSignIn={route.place === "signin"} />}</Shell>;
}

export default function Index() {
  return (
    <LabProvider>
      <Board />
    </LabProvider>
  );
}
