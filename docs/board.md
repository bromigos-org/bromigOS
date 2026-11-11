# The Lab board's page

The Lab board is bromigOS Server's own web page. You open it in any browser at home, at the
server's name (`https://myserver.local`). Before you sign in it is **the door**: the
household's apps, to open. After you sign in it is the whole board: Home, the machines,
Den, Supply, Data, Network, People, Settings, and the activity strip along the bottom.

This page covers the web app: the files in `board/web/`, how it reads the server, how it is
built and packaged, and how it is tested. The server's side (the API, sign-in, the reader
that gathers the readings, the Caddy site) is the board's service, the `bromigos-board`
package.

## What is built

- **The shell.** The rail on the left: the lab's name, Home, the machines and **+**, the
  places, and Settings at the foot. The top bar: where you are, Ask or search, Depth and
  You. The activity strip along the bottom, which rises into the drawer of jobs. At phone
  width the rail becomes a bar along the bottom with the places only.
- **Activity.** Every job the page knows, from the live stream and from the list the board
  read: the ones that ask, the ones that run or wait, and the ones that ended. Each shows
  its steps, what it asks, how it ended, and the command that looks closer
  (`bromigos activity show ID`). `#job/ID` opens one job. The page is read-only: see
  [What the page may do](#what-the-page-may-do).
- **The door and signing in.** Signed out, every address shows the door: the ways in and
  the apps to open, nothing else. **Sign in** takes the one-time code that
  `sudo bromigos server board code` prints at the server.
- **Home.** The lab's one status line, what needs you (each item with its machine and a
  link to where it is fixed), and a tile per machine. The hero is the mount point for
  Lamplight, the living station, which arrives in its own change.
- **A machine.** Overview: the machine's hologram with a module per catalogue group, its
  status line, what needs you and what fixed itself, the Storage, Backups and Updates
  tiles, its apps as tiles with Open, and the always-on parts. Vitals: four gauges and one
  trend chart. Hardware: processor, memory, drives and the graphics card. Set-up stands in
  for Overview on a first run.
- **Data.** Drives: each drive with its verdict, and for a drive that isn't healthy what the
  server says about it and what to do. Backups: the last good copy, where the copies go
  (the nightly destination and the Go Bag drive), and the last test restore.
- **Supply.** Installed: every installed app as a tile, with the memory and data they use.
  Browse: the whole catalogue by group, found by name, each with what it asks of the
  server. The Add sheet shows the exact command, and adds the app from the page on a server
  that lets the page (see [What the page may do](#what-the-page-may-do)). Updates: the
  system's update, and each app with one waiting.
- **One app** (`#app/ID`). What it is and the version installed, its state and since when,
  where it answers, the memory and data it uses beside what its recipe asks for, its folder
  (`/srv/apps/ID`) with its size, the server's backups, its update when it reports one, the
  apps that need it, the jobs about it that haven't ended, and the commands for its logs
  and a closer look. Restart, and the Remove sheet with its two separate choices, are
  controls on a server that lets the page (see
  [What the page may do](#what-the-page-may-do)); otherwise they are commands.
- **People › Ways in.** How this browser is signed in, and every browser signed in to the
  board, as the service lists them: when each signed in, when it was last used, and when
  its sign-in ends. Each has a sign-out, this browser's too. Beside them, the three steps
  that sign another browser in with a one-time code. The list is read again each time the
  tab is opened.
- **Settings**, read-only: how the server is set, each with the file or command that changes
  it. Lab: the lab's name and address, whether the door shows the apps, the world the page
  wears, and what root lets the page do. Notifications: each channel alerts go to as
  `bromigos alerts channels` lists it (what it takes, its quiet hours, when it last sent,
  its last problem, a setting the server doesn't use), and the checks with whether each
  could look. Mascot: STATIC's three modes and `bromigos mascot`. No address or key of a
  channel is ever on the page, and nothing here is a switch.
- **Planned, and marked so on the page:** an app's restore points, the Stacks sheet, People ›
  Household, Den, Network, and Settings' Power, Recovery and About; Activity's History,
  Reports and upcoming jobs; and inside
  the built pages: This week, VECTOR's plans, power, system versions, the pool's layout, a
  new disk, replacing a drive, getting files back, a friend's lab, Move in, and the apps'
  updates. A machine's processor, memory, heat and network, its hardware and its trends
  show as "not measured" until the service sends them.

## Where things are

| Path | What |
|---|---|
| `board/web/pages/` | The one page (`index.tsx`), its document and its styles' entry |
| `board/web/shell/` | The rail, the top bar, the strip and its drawer, the Depth drawer, tabs and sheets |
| `board/web/views/` | The door and the sign-in sheet, and one file per place |
| `board/web/components/` | Icons and buttons, the job card, the hologram, the trend chart, the error boundary |
| `board/web/lib/api/` | The API's client (`client.ts`), its reader (`read.ts`), the types the views use (`types.ts`), fixture mode (`fixtures.ts`) |
| `board/web/lib/lab.tsx` | The page's state and its one connection to the server |
| `board/web/lib/words.ts` | The headlines' rules |
| `board/web/lib/routes.ts` | Every route, its tabs and sheets |
| `board/web/lib/holo/` | The hologram renderer |
| `board/web/styles/` | DRIFTGLASS on the web: the worlds' tokens, the parts, a file per place |
| `board/web/tests/` | The Playwright tests; `tests/contract/service.json` holds real answers of the service |
| `board/web/scripts/` | `make-contract.py`, `make-fixtures.mjs`, `postbuild.mjs` |
| `packaging/bromigos-board-web/` | The package: the built page in `/usr/share/bromigos-board/web/` |

## Routes

The page is one `index.html`. The part after `#` in the address says what it shows, so
Caddy needs no rewrite rules. A place is lab-wide. Picking a machine in the rail scopes the
places to it; the chip in the top bar lets go.

| Address | Shows |
|---|---|
| `#home` | Home (the default). `#add-machine` opens the Add a machine sheet over it |
| `#m/NAME`, `#m/NAME/vitals`, `#m/NAME/hardware` | A machine: Overview, Vitals, Hardware |
| `#den`, `#den/library`, `#den/requests`, `#den/play` | Den |
| `#cameras` | Cameras. Its rail entry shows only when a machine runs the Cameras app |
| `#supply`, `#supply/browse`, `#supply/updates` | Supply. `#supply/add/ID` opens the Add sheet over Browse |
| `#app/ID` | One app. `#app/ID/remove` opens the Remove sheet over it |
| `#data`, `#data/backups`, `#data/move` | Data: Drives, Backups, Move in (Shares is planned) |
| `#network` | Network › Devices (Ad blocking and Away are planned) |
| `#people`, `#people/ways` | People: Household (planned), Ways in |
| `#activity` | Activity › Now (History and Reports are planned). `#job/ID` opens one job over it |
| `#settings`, `#settings/lab`, `#settings/mascot` | Settings: Notifications, Lab, Mascot (Power, Recovery and About are planned) |
| `#signin` | The sign-in sheet over the door, when signed out. Signed in, it is Home |

An address the page doesn't know opens Home. So does one that isn't an address at all, such
as `#%`.

## How it reads the server

All requests go to the server that served the page. The session is the service's cookie,
which the page never reads. Every request that changes something carries the header
`X-Bromigos-Board: 1` and a JSON body.

| Request | The page uses it for |
|---|---|
| `GET /api/door` | The door: the server's name, its world, the apps to open, the ways in |
| `GET /api/session` | Whether this browser is signed in, and the signed-in browsers |
| `POST /api/session` `{"code": …}` | Signing in with the one-time code. A refusal's sentence is shown as the server wrote it |
| `DELETE /api/session`, `DELETE /api/session/ID` | Signing this browser out, or another one (People › Ways in) |
| `GET /api/board` | The board: the machines, what needs you, what fixed itself, the jobs as `bromigos activity list` printed them, a tile per catalogue item, and the drive, backup and update documents as their commands print them |
| `GET /api/activity` | The jobs, live: a stream of Server-Sent Events |
| `GET /api/vitals?machine=NAME&range=24h` | A machine's trends. The service doesn't serve it yet, and the chart is marked planned |
| `POST /api/actions` `{"verb": "add", "app": ID}` | Adding an app, on a server that lets the page. `"restart"` and `"remove"` the same way |

### Nothing arrives trusted

Every answer passes through `lib/api/read.ts` before a view sees it. Each field is checked
and given its type. A part that is missing, `null`, or shaped another way becomes "couldn't
be read", with the server's reason when it gave one. That covers a command's error
document and an older or newer service. So one bad document costs its own panel a
sentence, never the page.

Each panel and each part of the shell also sits in an error boundary
(`components/Boundary.tsx`). If a part throws while it draws, that part alone is replaced
by a sentence, and the rest of the page keeps working.

An address the server sends becomes a link only when it is `http:` or `https:`
(`lib/url.ts`).

### The connection

`lib/lab.tsx` holds the page's one connection model.

- **The board** is read every 15 seconds, and **the jobs** arrive on the activity stream.
  Both stop while the tab is hidden, so a forgotten tab doesn't keep the server reading
  itself. When the tab is looked at again they start with an immediate read.
- **The jobs come from two places**: the stream, and the list the board read
  (`activity.jobs`). They are joined, and the newer record of a job wins. With the stream
  refused and the board's list read, the strip and Activity show that list and say "not
  live · reconnecting". With neither read, they say the jobs couldn't be read, and never
  "nothing running".
- **How old a reading is** comes from the server: its `age_s` and `stale`. The page keeps
  the server's time and adds what has passed since the answer came. This browser's clock
  is never compared with the server's, so a wrong clock here changes nothing.
- **A read that fails** is said: the top bar shows "Not answering · trying again", the last
  board stays, and its age keeps growing until the headline reads "NOT READ FOR…". The
  page asks again after 5 seconds, then every 15.
- **A stale answer** is asked for again after 3 seconds. The server's first answer after a
  pause is its last, old one; until a fresh one comes the headline reads "READING THE
  SERVER".
- **The stream** is opened again on a timer whenever it ends, whatever ended it: after 1,
  3, 5, then every 15 seconds. When the server refuses it, the page asks whether it is
  still signed in.
- **A session that ended elsewhere** (a 401, or the stream's `signed-out` event) sends the
  page back to the door.

### Headlines never round up

`lib/words.ts` holds the rules for every status line. "ALL MACHINES NOMINAL", "ALL SYSTEMS
NOMINAL", "ALL DRIVES HEALTHY" and "VITALS NOMINAL" are said only when every part under
them was read and is well. Otherwise the line says the worst thing, in this order: how old
the reading is; what needs you; apps that aren't running; backups that need a look; parts
the server couldn't read; drives on watch or that can't be read. A drive's `watch` and
`unknown` verdicts keep their own words. "Nothing needs you" is said only when both the
alerts and the jobs were read.

### What the page may do

- **Jobs.** The page shows a job's question and its answers, with the command that answers
  it (`sudo bromigos activity answer ID CHOICE`). It has no Answer, Cancel or Retry control:
  the service has no route for them yet. On the Activity page a job that says stopping is
  safe shows `sudo bromigos activity cancel ID`, and one that can be started again shows
  `sudo bromigos activity retry ID`.
- **Adding an app.** The Add sheet's control appears only when the board says the page may
  add (`actions` holds `"add"`) and the app's tile says it can be added. Otherwise the
  sheet shows the command and a planned mark. The service doesn't send `actions` yet.
- **Restarting and removing an app.** The same rule, with `"restart"` and `"remove"`:
  the control is there when `actions` holds the word and the app's tile lists it in `can`.
  Removing keeps the app's data. An app the server won't remove (another app needs it, or
  it is one of the lab's own parts) has no Remove, and its sheet says why.
- **Deleting an app's data** has its own word, `"delete-data"`, as root's `[board] actions`
  has. The sheet then asks for two things: the app's id, typed, and a fresh code from
  `sudo bromigos server board code`. The page sends
  `{"verb": "remove", "app": ID, "delete_data": true, "code": CODE}`, and root checks the
  code and uses it up. The code that signed the browser in doesn't count. Without the
  word, the sheet shows `sudo bromigos lab apps remove ID --delete-data` and no field.

## Holograms and charts

A machine's hero draws its hologram with bromigos.org's renderer (`lib/holo/`, three.js
0.186.1): one WebGL context for the page, drawing only while something moves. The model
turns for 20 seconds, then holds still. Under reduced motion, or without a graphics card's
WebGL, it draws one still frame. Only the rack (servers) and the workstation (desktops)
ship (`public/holo/`); other kinds of machine show their kind's glyph, because their
meshes' licence isn't cleared. Without WebGL the glyph stays. A model that fails to load is
asked for again by the next view.

The trend is ECharts, one series at a time in the world's colour, with a crosshair and its
readings in a table for screen readers. Its tooltip is drawn on the canvas, so the chart
adds no inline style.

## The look

The page wears the server's world: `GET /api/door` names it, and `styles/tokens.css` holds
each world's colours as `themes/<name>/colors.toml` ships them. All eleven are there; a name
the page doesn't know falls back to the Wick. The parts are DRIFTGLASS's
([DRIFTGLASS.md](DRIFTGLASS.md)), taken from the Lab board's mock-ups so a page reads like
its design. With reduced motion turned on in the browser or the system, nothing moves.

Geist Mono comes from the `ttf-geist-mono` package: the page's `fonts/` folder holds links
to its files. The page fetches nothing from another site.

## Rules the page keeps

- **One origin.** No request to another site: no CDN, no remote font or icon, no analytics.
  The page runs under `Content-Security-Policy: default-src 'self'`: it has no inline
  script that runs and no inline style in its HTML. `scripts/postbuild.mjs` fails the build
  if the export breaks either rule.
- **A hint on every control.** Every link, button and field has a `title` that says what it
  is and what it does, and an accessible name.
- **A state is a shape and a word**, never colour alone. A PLANNED mark is a dashed outline
  that never takes a state's colour.
- **Nothing made up.** A reading comes from the server with its time. An old one turns grey
  with its age. A part that couldn't be read says so.

## Building and testing

You need Node 22 or newer and npm. Everything stays in `board/web/`.

```sh
cd board/web
npm ci --ignore-scripts
npm run build             # the page the package installs: out/
npm run build:fixtures    # the test copy: fixtures written, then out/ with ?fixture=NAME
npx playwright install --only-shell chromium
npx playwright test       # headless; nothing opens on the desktop
```

The build's id is the commit it was built from, so two builds of one commit are the same
files.

### The service's real answers

`tests/contract/service.json` holds real answers of the service. Nothing in it is written
by hand. `scripts/make-contract.py` makes it:

- **the commands' documents** come from the libraries behind `bromigos storage health`,
  `bromigos alerts`, `bromigos lab backups status`, `bromigos activity list`,
  `bromigos server status` and `bromigos lab apps list`, run on the stand-in machines their
  own tests use;
- **the board, the door, the session and the stream** come from the service's own reader
  and API, asked over HTTP with its test client.

It holds the answers of each request, and a board for each state the commands can leave it
in: healthy; a drive getting worse with a job asking; a job running; drives on watch and
unreadable; backups that need a look, are off, carry a Go Bag, or aren't a server's; an app
down; nothing installed; a stale reading; alerts with three channels of the server's own;
and each command missing or printing an error.

```sh
python3 board/web/scripts/make-contract.py           # write it again
python3 board/web/scripts/make-contract.py --check   # exit 1 when it differs
```

The script needs `python-starlette` and `python-httpx`, as the service's tests do. It reads
the service from this checkout, or from a git ref with `--ref`.

### Fixture mode

In the test copy, `?fixture=NAME` answers every request from `fixtures/NAME.json`, not from
the server, for example `http://127.0.0.1:4317/?fixture=needs-you#home`
(`node tests/serve.mjs` serves `out/`). `scripts/make-fixtures.mjs` writes the fixtures
from the real answers. A fixture may only install more of the catalogue's apps on the
example server, and add what the page has asked the service for and the service doesn't
send yet. The package's build leaves fixture mode out.

| Fixture | The state |
|---|---|
| `door`, `door-empty` | Signed out, with apps, and with nothing installed. In `door`, the code `KX7-42Q` signs in |
| `unreachable` | The board service doesn't answer |
| `as-served` | Exactly what the service answers today, untouched |
| `cant-read` | The server couldn't read its apps, drives, backups or updates |
| `healthy`, `running` | Everything running, with readings and trends; in `running` a backup finishes while you watch |
| `needs-you`, `alert` | A drive getting worse; a job asking, or only the alert |
| `watch` | One drive on watch and one that can't be read |
| `setup`, `stale` | Nothing installed yet; a reading five minutes old |
| `actions` | The server lets the page add apps |
| `lab`, `cameras` | Four machines in the rail; a machine that runs Cameras |
| `channels` | Alerts go to Discord with quiet hours and to a webhook that needs a look; a third channel is off |

### The tests

All run in headless Chromium against the test copy, served with the board's
Content-Security-Policy.

- **The contract** (`tests/contract.spec.ts`): the page's real client, with no fixture,
  against the service's real answers.
  - The door, signing in and out, and the header and JSON body the service asks for.
  - Every place on every real board, with what each must say and never say.
  - Every part of the board, the whole board, the door and a job replaced by `null`, an
    empty object, a list, a word, a number or an error document: nothing blanks.
  - A 503 while the server first reads itself; a 502, a 500 and the server going away
    mid-session; a 401 mid-session; a stream that is refused, and one that says
    signed-out.
  - A hidden tab asks nothing. A browser clock that is wrong changes nothing.
  - Unsafe addresses never become links. A part that throws costs that part only.
- **Activity** (`tests/activity.spec.ts`): the three groups and what each job says; a job
  that runs and ends; one job by its address; the stream's and the board's lists joined;
  the jobs unread; and that nothing but a GET is sent.
- **One app** (`tests/app.spec.ts`): what the page says of a tile, from the fixtures and
  from the service's real answers; an app that measures nothing is "not measured", never
  zero; restart and remove offered only with the server's leave, and sent as the service
  asks; deleting data only with its own leave, the id typed and a code; a refusal in the
  server's words.
- **Ways in** (`tests/people.spec.ts`): the browsers the service lists; signing another one
  out with the service's `DELETE`, and this one; a browser that signed out by itself
  meanwhile (the service's 404, in its words, and the list read again); the steps for a
  code; and that Household shows no made-up person.
- **Settings** (`tests/settings.spec.ts`): the channels of a real `bromigos alerts` document
  that has three (one with quiet hours, one whose last message didn't go and with a
  setting the server doesn't use, one off); quiet hours only of channels that are on; no
  address on the page; the checks; what the page may do, not claimed until the server
  says, and "not allowed" when it says so; and each of these parts in broken shapes.
- **The shapes** (`tests/shapes.spec.ts`): every fixture document has the service's keys
  and types.
- **The layout** (`tests/layout.spec.ts`): the rail's two small marks on a machine (its
  update arrow, its state) stay small, in their corners and apart; and the activity strip
  never covers the end of a page or of a sheet, at either width.
- **The pages** (`routes`, `a11y`, `motion`, `phone`, `shell`, `home`, `machine`, `data`,
  `supply`), at 1280 and 390 pixels wide: every route in seven page states with no error
  and no request to another site; a hint and an accessible name on every control, and axe;
  nothing animates under reduced motion; nothing scrolls sideways at 390 pixels; and each
  page's own behaviour.

`SHOTS=DIR npx playwright test shots` saves a picture of every route into `DIR`.

CI runs all of it on a pull request that touches `board/web/`
(`.github/workflows/board-web.yml`), and builds the page twice to check the two builds are
the same.

## The package

`bromigos-board-web` is built from `board/web/` with Node at package time, so a server runs
no Node. It installs the export in `/usr/share/bromigos-board/web/`, with `fonts/` linking
to `ttf-geist-mono`'s files, and nothing else. The board's service serves that folder
through Caddy and answers `/api/`.

The package's build gives npm and the build a clean environment, and runs no dependency's
install script: the lock file pins every package by its hash.
