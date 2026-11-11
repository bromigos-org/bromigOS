// What a page shows while there is no board to draw: the server is still reading itself for
// the first time, or it isn't answering. The server's own sentence, and that the page keeps asking.
import type { ApiError } from "@/lib/api/errors";
import { Icon } from "./ui";

export function NoBoard({ error }: { error: ApiError }) {
  const first = error.code === "gathering";
  return (
    <div className="unreach" role="status" title={first ? "The server is reading itself for the first time" : "The board couldn't be read from the server"}>
      <Icon id={first ? "s-wait" : "i-offline"} size={40} />
      <p>
        {error.words}
        {first ? "" : " The page keeps asking, and shows the board as soon as the server answers."}
      </p>
    </div>
  );
}
