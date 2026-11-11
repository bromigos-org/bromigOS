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
- **Home.** The hero is [Lamplight](#lamplight-the-station): the lab as a living station,
  with the lab's one status line. Under it, what needs you (each item with its machine and
  a link to where it is fixed), and a tile per machine.
- **A machine.** Overview: the machine on its deck tray, pulled out of the station, then
  its status line with a module per catalogue group, what needs you and what fixed itself, the Storage, Backups and Updates
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
- **Planned, and marked so on the page:** an app's restore points, the Stacks sheet, People,
  Den, Network and Settings; Activity's History, Reports and upcoming jobs; and inside
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
| `board/web/components/` | Icons and buttons, the job card, Lamplight's two heroes, the trend chart, the error boundary |
| `board/web/lib/api/` | The API's client (`client.ts`), its reader (`read.ts`), the types the views use (`types.ts`), fixture mode (`fixtures.ts`) |
| `board/web/lib/lab.tsx` | The page's state and its one connection to the server |
| `board/web/lib/words.ts` | The headlines' rules |
| `board/web/lib/routes.ts` | Every route, its tabs and sheets |
| `board/web/lib/lamplight/` | Lamplight, the station: a module with no React in it, and its stylesheet |
| `board/web/lib/lamplight-assets.ts` | What the station may draw: its models and STATIC's crew |
| `board/web/lib/holo/` | The hologram renderer |
| `board/web/styles/` | DRIFTGLASS on the web: the worlds' tokens, the parts, a file per place |
| `board/web/tests/` | The Playwright tests; `tests/contract/service.json` holds real answers of the service |
| `board/web/scripts/` | `make-contract.py`, `make-fixtures.mjs`, `art.mjs`, `postbuild.mjs` |
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
| `#people`, `#people/ways` | People: Household, Ways in |
| `#activity` | Activity › Now (History and Reports are planned). `#job/ID` opens one job over it |
| `#settings`, `#settings/mascot` | Settings: Notifications, Mascot (Lab, Power, Recovery and About are planned) |
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
| `DELETE /api/session`, `DELETE /api/session/ID` | Signing this browser out, or another one |
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

## Lamplight, the station

Home's hero draws the lab as a station: a relay station of the Wick's class, cut open so
its decks show. It is never the Wick itself, which is BLACKFLAME's own post. Everything on
it comes from the board's document.

- **Each machine is a compartment on a deck.** Servers ride the rack room (D2), storage
  the hold (D1), a desktop the docking ring. A server and a desktop stand as their
  holograms. A kind with no cleared model (storage, a small server) stands as its icon on
  the deck tray. The list beside the station names every compartment with its state and
  one reading, and the deck plan under it shows the same boxes in side elevation. Press
  a machine anywhere to open its page.
- **The line is the page's own.** The station says the same status line as the rest of the
  page (`lib/words.ts`), with when the server read itself. Three lit readouts count the
  machines that answer, what needs you, and the time of the reading.
- **What needs you lights where it is.** A drive or volume alert lights the hull; any
  other lights the rack room. The alarm bar names the machine and the alert, flashes three
  times when it starts and then stays lit. Pressing it, or the lit part, opens the page
  that owns the fact.
- **The crew stands where something real happens.** OWL keeps the watch on the mast.
  LINEMAN stands at the machine that needs you until it is fixed. The shells with nothing
  to do wait in quarters. Nobody is placed for decoration.
- **An old reading shows no signal.** When the server's reading is older than it allows,
  the station dims, no machine is shown as known, and the alarm is withdrawn: the page
  can't vouch for it.
- **A first run is its own state.** A server with nothing installed reads SET UP, with no
  alarm.

A machine's Overview shows that machine pulled out of the station on its deck tray, at
full detail, with the part that is the cause lit and the shell at work beside it. **DOCKS
AT** goes back to the whole station.

The station is a module with no React in it (`lib/lamplight/`). The page hands it the
board's document (`fromBoard`), the manifest of what it may draw
(`lib/lamplight-assets.ts`) and the page's status line, and calls `update` with each new
reading. A reading that changed only its time rewrites the head and the readouts, and
nothing else. The module and three.js load only when a hero is on screen. Until they
have, or if they can't, the hero's frame shows the lab's plain state.

It draws with bromigos.org's renderer (`lib/holo/`, three.js 0.186.1): one WebGL context
for the page, drawing only while something moves. The station turns for 20 seconds after
a change or the pointer, then holds still. Under reduced motion it draws one still frame.
Without WebGL the words stand: the line, the readouts, the alarm, the deck list and the
deck plan need no hologram. A model that fails to load is asked for again by the next
view.

What ships (`public/holo/`, [ASSETS.md](ASSETS.md)): the station, the rack and the
workstation, each as a lighter bake for the station, and the rack and the workstation in
full for a machine's page. The storage, node, router and battery meshes aren't shipped,
because their licence isn't cleared. When a clean one lands, it is added to the manifest
and nothing else changes.

The crew's paintings come from the repository's `mascot/` at build time
(`scripts/art.mjs`, into `public/lamplight/`, which isn't committed): the five cut-outs
in `mascot/crew/`, and a portrait for each of those shells lifted from its loop in
`mascot/static/`, used only where a cut-out is missing. A build outside the repository
names the folder in `BOARD_MASCOT`.

The module adds no `<style>` element and no style attribute, so it works under the
board's content policy. Its stylesheet (`lib/lamplight/lamplight.css`) is scoped under
`.lp`.

Everything the station is handed is treated as untrusted, because much of it is some
command's output: a drive's model string, a share's name, a job's words.

- **The shape is checked at the door** (`lib/lamplight/sane.ts`). A state, kind or tone
  that isn't one of the allowed words becomes "unknown" or "other". A field that should
  be text or a number and isn't is left out. So no word from the data picks a shape, a
  colour or a class.
- **Text is only ever text.** Markup is made in one way, `` html`…` `` (`base.ts`), which
  escapes every value where it lands, and reaches the page in one place. No other file
  writes markup. Addresses of pictures and models come only from the manifest.
- `tests/hostile.spec.ts` holds this: it replaces every string in the example labs and in
  the board's fixtures with a payload that would show if it were ever read as markup,
  then also the ids and state words, then the numbers, and draws Home with every panel,
  a machine's hero and a bare hologram.

## Charts

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

Home and every machine's page draw a hologram, and on Chromium's software renderer (all
CI has) each one costs seconds of processor. So only the specs that test what the
holograms draw run in a browser with WebGL: they say `test.use(WEBGL)` (`tests/webgl.ts`).
Every other spec runs with WebGL off, where the station stands as words, which is all
those specs read.

On a machine with a graphics card, a local run can draw on the card instead, still
headless and with no window. Then every spec has WebGL:

```sh
BOARD_TEST_GPU=1 npx playwright test --workers=2
```

The run prints which renderer it got (`WebGL renderer: …`) before the first test. With
the switch on, it stops there if the browser fell back to software, rather than quietly
using the processor. The switch uses `--enable-gpu --use-angle=vulkan
--enable-features=Vulkan --ignore-gpu-blocklist` in place of `--enable-unsafe-swiftshader`
(`tests/webgl.ts`, `tests/renderer.ts`). No test compares pictures against a stored one,
so the suite means the same on either renderer. On the card the holograms turn, where the
software renderer holds them still. CI is the reference, and it has no card.

The build's id is the commit it was built from, so two builds of one commit are the same
files. Both builds first run `scripts/art.mjs`, which copies STATIC's crew for the station
from the repository's `mascot/` folder.

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
down; nothing installed; a stale reading; and each command missing or printing an error.

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
install script: the lock file pins every package by its hash. It builds a copy of
`board/web/`, so it names the repository's `mascot/` folder in `BOARD_MASCOT` for the
station's crew.
