# The Lab board's page

The Lab board is bromigOS Server's own web page. You open it in any browser at home, at the
server's name (`https://myserver.local`). Before you sign in it is **the door**: the
household's apps, to open. After you sign in it is the whole board: Home, the machines,
Den, Supply, Data, Network, People, Settings, and the activity strip along the bottom.

This page covers the page itself: the files in `board/web/`, what it reads from the
server, how it is built and packaged, and how it is tested. The service that answers it
(`bromigos-board`, the API on a Unix socket behind Caddy) has its own page once it lands.

## What is built

- **The shell.** The rail on the left: the lab's name, Home, the machines and **+**, the
  places, and Settings at the foot. The top bar: where you are, Ask or search, Depth and
  You. The activity strip along the bottom, which rises into the drawer of jobs. At phone
  width the rail becomes a bar along the bottom with the places only.
- **The door and signing in.** Signed out, every address shows the door: the ways in and
  the apps to open, nothing else. **Sign in** takes the one-time code that
  `sudo bromigos server board code` prints at the server.
- **The data layer.** Typed clients for the four things the page reads, and a fixture mode
  for building and testing pages before a server answers.
- **Home.** The hero's frame with the lab's one status line (ALL MACHINES NOMINAL, N
  MACHINES NEED YOU, NOTHING INSTALLED YET, or how old the reading is), NEEDS YOU with each
  item's machine and a link to where it is fixed, and a tile per machine with its processor,
  memory and hottest drive, grey once older than the server says they may be. Lamplight, the
  living station, mounts in the hero once its module lands; This week and VECTOR's plans
  are marked planned.
- **Not built yet.** The places' own pages (a machine, Data, Supply, Activity,
  People, Den, Network, Settings) show their tabs and a PLANNED mark. They come one change
  at a time. Nothing is ever shown as a reading unless the server measured it.

## Where things are

| Path | What |
|---|---|
| `board/web/pages/` | The one page (`index.tsx`), its document and its styles' entry |
| `board/web/shell/` | The rail, the top bar, the strip and its drawer, the Depth drawer, tabs and sheets |
| `board/web/views/` | The door, the sign-in sheet, and one file per place |
| `board/web/components/` | Icons and buttons, the job card, the icon sprite |
| `board/web/lib/api/` | The API's types (`types.ts`), the client (`client.ts`), fixture mode (`fixtures.ts`) |
| `board/web/lib/routes.ts` | Every route, its tabs and sheets |
| `board/web/styles/` | DRIFTGLASS on the web: the worlds' tokens, the parts, the shell |
| `board/web/fixtures/` | One JSON file per page state, written by `scripts/make-fixtures.mjs` |
| `board/web/tests/` | The Playwright tests |
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
| `#supply`, `#supply/browse`, `#supply/updates` | Supply |
| `#app/ID` | One app |
| `#data`, `#data/backups`, `#data/move` | Data: Drives, Backups, Move in (Shares is planned) |
| `#network` | Network › Devices (Ad blocking and Away are planned) |
| `#people`, `#people/ways` | People: Household, Ways in |
| `#activity` | Activity › Now (History and Reports are planned) |
| `#settings`, `#settings/mascot` | Settings: Notifications, Mascot (Lab, Power, Recovery and About are planned) |
| `#signin` | The sign-in sheet over the door, when signed out |

An address the page doesn't know opens Home.

## What it reads from the server

All requests go to the same server that served the page. The session is the service's
cookie, which the page never reads. Every request that changes something carries the header
`X-Bromigos-Board: 1`, which a page on another site can't send.

| Request | Gives |
|---|---|
| `GET /api/door` | The lab's and the server's names, the server's world, the door's app tiles, and which ways in it offers. The only request before sign-in |
| `GET /api/session` | Whether this browser is signed in, and the signed-in browsers |
| `POST /api/session` `{"code": …}` | Signs in with the one-time code. A wrong, used or old code answers 401 with a sentence the page shows |
| `DELETE /api/session` | Signs this browser out. `DELETE /api/session/ID` signs another browser out |
| `GET /api/board` | The board: machines, what needs you, what fixed itself, the app tiles, and the drive, backup and update documents as their commands print them. Read again every 15 seconds |
| `GET /api/activity` | The jobs, live: a stream of Server-Sent Events. A `snapshot` event on connect, then a `job` event for each change |

A tile is the JSON `bromigos lab apps list --json` prints. A job is the record
`bromigos activity show ID --json` prints ([activity.md](activity.md)). The page shows the
job that most needs a look on the strip: one that asks you, then an alert that needs you,
then one that runs, then one that ended badly in the last day, then the last one.

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
- **Nothing made up.** A reading comes from the server with its time; one older than its
  `max_age_s` turns grey with its age. A part that couldn't be read says so.

## Building and testing

You need Node 22 or newer and npm. Everything stays in `board/web/`.

```sh
cd board/web
npm ci
npm run build             # the page the package installs: out/
npm run build:fixtures    # the test copy: out/ with fixtures/, for ?fixture=NAME
npx playwright install --only-shell chromium
npx playwright test       # headless; nothing opens on the desktop
```

**Fixture mode.** In the test copy, `?fixture=NAME` answers every request from
`fixtures/NAME.json` instead of the server, for example
`http://127.0.0.1:4317/?fixture=needs-you#home` (`node tests/serve.mjs` serves `out/`). A
fixture is one page state: the door, the session, the board, the jobs, and a stream of job
changes played back after the page connects. `node scripts/make-fixtures.mjs` writes them
all from one example lab. The package's build leaves fixture mode out.

| Fixture | The state |
|---|---|
| `door`, `door-empty` | Signed out, with apps, and with nothing installed. In `door`, the code `KX7-42Q` signs in |
| `unreachable` | The board service doesn't answer |
| `healthy`, `running` | Signed in, everything running; in `running` a backup finishes while you watch |
| `needs-you`, `alert` | A drive getting worse; a job asking you, or only the alert |
| `setup` | Nothing installed yet |
| `stale` | The board's snapshot is 20 minutes old |
| `lab`, `cameras` | Four machines in the rail; a machine that runs Cameras |

**The tests** (`tests/`), in headless Chromium at 1280 and 390 pixels wide, against the
test copy served with the board's Content-Security-Policy:

- Home's verdict, NEEDS YOU, the machines' tiles and their stale readings, and first run;
- every route renders in four page states, with no error, no policy violation and no
  request to another site;
- every control has a hint and an accessible name, and axe finds nothing, on every route,
  at the door and with the drawers open;
- with reduced motion, nothing animates, even while a job runs and under the pointer;
- at 390 pixels nothing scrolls sideways, and the rail is the bar along the bottom;
- the door, signing in with the code and out again, the eleven worlds, the rail and its
  scope, the strip following the stream, the drawers, the tabs and search.

`SHOTS=DIR npx playwright test shots` saves a picture of every route into `DIR`.

CI runs all of it on a pull request that touches `board/web/` (`.github/workflows/board-web.yml`),
and the package build builds the page once a change is on `main`.

## The package

`bromigos-board-web` is built from `board/web/` with Node at package time, so a server runs
no Node. It installs the export in `/usr/share/bromigos-board/web/`, with `fonts/` linking
to `ttf-geist-mono`'s files, and nothing else. The board's service serves that folder
through Caddy and answers `/api/`.
