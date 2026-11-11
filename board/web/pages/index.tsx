// The Lab board: one page; the hash picks what it shows (lib/routes.ts). Nothing is drawn until
// the session is known, so the door never flashes for a browser that is signed in.
import { useEffect } from "react";
import { Boundary } from "@/components/Boundary";
import { LabProvider, useLab } from "@/lib/lab";
import { Shell } from "@/shell/Shell";
import { Door } from "@/views/Door";
import { Pages } from "@/views/Pages";

function Board() {
  const { session, route } = useLab();
  const signedIn = session.state === "ok" && session.doc.signed_in;
  // the sign-in sheet is the door's: a signed-in browser that lands on it goes Home
  useEffect(() => {
    if (signedIn && route.place === "signin") window.location.replace("#home");
  }, [signedIn, route.place]);
  if (session.state === "loading") return <div className="boot" />;
  return (
    <Shell signedIn={signedIn}>
      <Boundary what="This page" again={route.hash}>
        {signedIn ? <Pages /> : <Door withSignIn={route.place === "signin"} />}
      </Boundary>
    </Shell>
  );
}

export default function Index() {
  return (
    <LabProvider>
      <Board />
    </LabProvider>
  );
}
