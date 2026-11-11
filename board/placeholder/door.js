// The placeholder page's only script: the door's tiles (GET /api/door), as plain links. Caddy
// serves it only until the Lab board's pages (bromigos-board-web) are installed.
fetch("/api/door", { credentials: "same-origin" })
  .then((r) => r.json())
  .then((d) => {
    document.getElementById("server").textContent = d.server.name + " · Lab board";
    const ul = document.getElementById("tiles");
    for (const t of d.tiles || []) {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = t.open.url;
      a.textContent = t.app ? t.job + " · " + t.app : t.job;
      a.title = "Open " + (t.app || t.job);
      li.appendChild(a);
      ul.appendChild(li);
    }
  })
  .catch(() => {});
