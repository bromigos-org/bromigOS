# The Lab board

The Lab board is bromigOS Server's own web page. You open it in any browser at home, at the
server's name (`https://myserver.local`). Before you sign in it is **the door**: the
household's apps, to open. After you sign in it is the whole board: Home, the machines,
Den, Supply, Data, Network, People, Settings, and the activity strip along the bottom.

This page covers both halves. First the web app: the files in `board/web/`, how it reads
the server, how it is built and packaged, and how it is tested. Then
[the service](#the-service), the `bromigos-board` package: the API, sign-in, the reader that
gathers the readings, the Caddy site, and what the page never shows.

## What is built

- **The shell.** The rail on the left: the lab's name, Home, the machines and **+**, the
  places, and Settings at the foot. The top bar: where you are, Ask or search, Depth and
  You. The activity strip along the bottom, which rises into the drawer of jobs. At phone
  width the rail becomes a bar along the bottom with the places only.
- **Activity.** The hero is [the post](#the-post): a small station whose crew walk to each
  job that runs or asks and work there. Under it, every job the page knows, from the live
  stream and from the list the board read: the ones that ask, the ones that run or wait,
  and the ones that ended. Each shows
  its steps, what it asks, how it ended, and the command that looks closer
  (`bromigos activity show ID`). A job that an AI agent asked for says which one, as "by
  agent ledger", from the record's `requested_by.agent`
  ([activity.md](activity.md#the-record)). `#job/ID` opens one job. A job's answers, Stop
  and Start again are controls on a server that lets the page: see
  [What the page may do](#what-the-page-may-do). The lab's creation jobs show here too:
  see [The lab's jobs](#the-labs-jobs). So do the tasks of a fleet of coding agents: see
  [A fleet's tasks](#a-fleets-tasks).
- **The door and signing in.** Signed out, every address shows the door: the ways in and
  the apps to open, nothing else. **Sign in** takes the one-time code that
  `sudo bromigos server board code` prints at the server.
- **Home.** The hero is [Lamplight](#lamplight-the-station): the lab as a living station,
  with the lab's one status line. Under it, what needs you (each item with its machine and
  a link to where it is fixed), what fixed itself (each job by its own title, with its
  machine, opening the job), and a tile per machine.
- **A machine.** Overview: the machine on its deck tray, pulled out of the station, then
  its status line with a module per catalogue group, what needs you and what fixed itself, the Storage, Backups and Updates
  tiles, its apps as tiles with Open, and the always-on parts. Vitals: four gauges and one
  trend chart. Hardware: the cores, the memory and the graphics card as the app manager's
  scan has them (`machines[].hardware`), the drives as the drive-health report lists them,
  and the free space for apps' data. When the scan didn't answer, the page says so with the
  server's reason, and calls no part missing. Set-up stands in for Overview on a first run.
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
  updates. A machine's cores, memory and graphics card come from the service. How busy its
  processor and memory are, its heat, its network and its trends show as "not measured"
  until something on the server measures them.

## Where things are

| Path | What |
|---|---|
| `board/web/pages/` | The one page (`index.tsx`), its document and its styles' entry |
| `board/web/shell/` | The rail, the top bar, the strip and its drawer, the Depth drawer, tabs and sheets |
| `board/web/views/` | The door and the sign-in sheet, and one file per place |
| `board/web/components/` | Icons and buttons, the job card, Lamplight's two heroes, the post's hero, the trend chart, the error boundary |
| `board/web/lib/api/` | The API's client (`client.ts`), its reader (`read.ts`), the types the views use (`types.ts`), fixture mode (`fixtures.ts`) |
| `board/web/lib/lab.tsx` | The page's state and its one connection to the server |
| `board/web/lib/words.ts` | The headlines' rules |
| `board/web/lib/routes.ts` | Every route, its tabs and sheets |
| `board/web/lib/lamplight/` | Lamplight, the station: a module with no React in it, and its stylesheet |
| `board/web/lib/lamplight-assets.ts` | What the station may draw: its models and STATIC's crew |
| `board/web/lib/post/` | The post, Activity's station: a module with no React in it, and its stylesheet |
| `board/web/public/post/` | The post's art: its paintings, clips and loops, `post.json` (where everything stands) and `provenance.jsonl` |
| `board/container/` | The board as a container image, for a lab that is a cluster: the image's recipe, its start script, its Caddy file and its test |
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
| `POST /api/session` `{"code": …}` | Signing in with the one-time code. A refusal's sentence is shown as the server wrote it. Its 503 `busy` (many codes being checked at once) is shown in the service's own words, and the code stays in the field: it wasn't checked, so it works when sent again. A coded deletion's or a coded answer's `busy` is the same |
| `DELETE /api/session`, `DELETE /api/session/ID` | Signing this browser out, or another one (People › Ways in) |
| `GET /api/board` | The board: the machines, what needs you, what fixed itself, the jobs as `bromigos activity list` printed them, a tile per catalogue item, and the drive, backup and update documents as their commands print them |
| `GET /api/activity` | The jobs, live: a stream of Server-Sent Events |
| `GET /api/vitals?machine=NAME&range=24h` | A machine's trends. The service doesn't serve it yet, and the chart is marked planned |
| `POST /api/actions` `{"verb": "add", "app": ID}` | Adding an app, on a server that lets the page. `"restart"` and `"remove"` the same way |
| `POST /api/activity/ID/answer` `{"question", "choice"[, "code"]}`, `/cancel` `{}`, `/retry` `{}` | A job's answer, Stop and Start again, on a server that lets the page. A choice that can't be undone carries a fresh code |

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

- **Jobs.** On every job card (the drawer, Activity, a job's own sheet), a job's answers,
  **Stop** and **Start again** are controls when two things agree: the board's `actions`
  holds the word (`"job.answer"`, `"job.cancel"`, `"job.retry"`), and the job's own record
  lists it in `can` (it asks now; it says stopping now is safe; it ended badly and was started
  as safe to start again). They send the service's
  [job actions](#a-jobs-own-actions), and show its words: "Answered.", "Stopped.", "Started
  again." with a link to the new job, or a refusal as the service wrote it.
  - **A choice that can't be undone** (`danger` in the question) opens a field for a fresh
    code from `sudo bromigos server board code` first; the answer goes with that code. A
    wrong, used or late code is the service's 403 `danger-needs-code`, in its words, and the
    field stays for another. **Back** sends nothing.
  - **Without the server's word**, a card shows the command instead:
    `sudo bromigos activity answer ID CHOICE`, and on Activity
    `sudo bromigos activity cancel ID` or `sudo bromigos activity retry ID` when the job
    allows it. An upgraded server may list none of them ([An upgrade never widens
    it](#what-a-session-can-do-and-how-to-turn-it-off)).
- **Adding an app.** The Add sheet's control appears only when the board says the page may
  add (`actions` holds `"add"`) and the app's tile says it can be added. Otherwise the
  sheet shows the command and a planned mark. `actions` is root's `[board] actions`, as the
  service read it ([Actions](#actions)).
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
  the hold (D1), a desktop the docking ring. Each stands as its kind's hologram: the rack,
  the storage server, the small node, the workstation, the router and the battery backup.
  A machine of a kind the board doesn't know stands as its icon on the deck tray. The
  list beside the station names every compartment with its state and one reading, and
  the deck plan under it shows the same boxes in side elevation. Press a machine
  anywhere to open its page.
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

What ships (`public/holo/`, [ASSETS.md](ASSETS.md)): the station, the rack, the
workstation, the storage server, the node, the router and the battery backup. Each has a
lighter bake for the station. All but the station and the battery backup also keep a full
mesh for a machine's own page; the battery backup is one small bake that serves both. A
kind of machine with no model is drawn as its icon.

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

## The post

Activity's hero is a small space station, seen from above with its roofs off. Its three
crew are the lab's jobs: when a job runs, a crew member walks to the room where that kind
of work is done and works there. Everything on it comes from the job records
([activity.md](activity.md#the-record)). It only shows: nothing on it starts, answers or
stops a job.

- **A job that runs has a crew member working at its place.** A ring of light under the
  crew member fills with the job's own share done (`pct`). A job that never said a share
  gets a short arc that turns, never a number.
- **A job that waits for your answer has a crew member standing at its place**, not
  working, on an amber ring.
- **A queued or waiting job isn't drawn.** Nobody is working on it yet.
- **A job that ends while you watch is shown once.** When it ended well, its room plays
  its finish and a ring bursts where it was worked. When it failed, was put back or was
  interrupted, the room's floor flashes red. A stopped job's crew member just walks home.
  Nothing that ended before the page was open is replayed.
- **There are three crew: LINEMAN, OWL and EXO.** A job keeps the crew member it was
  given. With a fourth job at once, that job's room and machine run with nobody standing
  there. A job that asks with nobody free gets the amber ring alone at its place.
- **With no job, the crew rest in the quarters**, and the rooms play their quiet clips.
- **Every room wears its name.** A plate over each room says what it is (QUARTERS,
  CONTROL ROOM, GREENHOUSE, WORKSHOP, PRINT SHOP, GALLEY), and one under the pad says
  LANDING PAD. A plate turns green while a job runs in its room, with a line under the
  name that fills with the job's own share done, and amber while a job there asks.
- **Those names are the only words on the picture, and there are no numbers.** Hover
  over a crew member, a machine or a room to read what it is. One with a job says the
  job's own title, its step and its share done. Press it to open that job, as the list
  under it does. A job's words are never drawn on the picture.

### Which job goes where

A job's place comes from its kind, and from whether an AI agent asked for it. The first
row that fits wins. The whole table is one file, `lib/post/places.ts`, and each row's
sentence there is also the hover hint on the page.

| A job | Is worked at | The crew member |
|---|---|---|
| The lab's creation jobs: a kind that starts with `lab.` | The server rack, in the control room | Scans the rack |
| A job an AI agent asked for, and a kind that starts with `agent.`, `plan.`, `ask.` or `vector.` | The hologram table, in the control room | Works the hologram |
| Updates of the system and downloads: a kind that starts with `server.`, `system.`, `package.`, `update.` or `download.`, and `app.models` | The landing pad. A shuttle lands for it | Unloads the shuttle, a crate at a time |
| Any other kind that starts with `app.` | The print bench, in the workshop | Welds |
| Backups, snapshots and restores: a kind that starts with `backup.`, `snapshot.` or `restore.` | The press, in the print shop | Packs |
| Drives, storage, power and hardware: a kind that starts with `drive.`, `pool.`, `storage.`, `disk.`, `power.`, `ups.`, `hardware.` or `salvage.` | The power core, in the workshop | Turns the core's wheel |
| Anything else | The terminal, in the greenhouse | Types |

A job that is a part of another, such as one app's update inside "update every app", is
drawn as the whole job, not beside it. Two jobs at one place stand apart: the second crew
member takes the room's own spot.

At a machine the crew member stands beside it, facing it, in that work's own loop. On the
pad the work is carried. Once the shuttle is down, the crew member reaches into it with
their back to you, walks a crate over to a stack, bends to set it down and goes back for
the next. The trips go on for as long as the job runs. They say nothing about how far it
is: the ring still shows the record's own share. When the job ends, the crate in hand is
set down first, and the shuttle waits for that. With two jobs at the pad, one crew member
carries and the other stands by.

The layout is fixed. There is no way to move a room or a machine, because placing a
machine doesn't change what the lab may do.

### How it is built

The post is a module with no React in it (`lib/post/`), like Lamplight. The page hands it
the jobs it has (`fromJobs`) and where its art is served, and calls `update` with each new
list. An update re-sends the crew in place. It remounts nothing and fetches no art again.

| File | What |
|---|---|
| `places.ts` | The table above, the states, and their sentences |
| `floor.ts` | Where each room sits, and where the crew can walk |
| `model.ts` | Which job has which crew member, where everyone is, what each room and machine does |
| `post.ts` | The page: the paintings, the crew, the rings, what the pointer reaches |
| `sane.ts`, `from-jobs.ts` | The door for the jobs and for the station's drawing |
| `post.css` | Its stylesheet, scoped under `.post` |

- **Rooms are separate paintings.** Each room module was painted on its own grid. The
  module places it at its doorway (`post.json`). On the corridor it wasn't painted for, a
  room is the same picture mirrored.
- **One depth order.** Rooms are drawn far to near, each with its machines and whoever is
  inside it. The corridors and anyone in them come last. So a nearer room's walls cover a
  crew member standing behind them.
- **The crew walk only where there is floor.** Every spot someone can stand is a stop.
  Stops are joined only where floor lies between them: along a corridor, through a
  doorway, across a room. A walk is the shortest chain of stops. Someone re-sent part-way
  goes on to the stop ahead or back to the one behind, so nobody crosses a wall or open
  space.
- **What moves.** Each crew member has two walking loops, mirrored to face the way they
  walk, and a standing loop for each kind of work. Each room has three clips cut to its
  own outline: quiet, busy and a finish. Machines have idle, running and finished loops.
  The shuttle flies with its legs folded away and unfolds them as it lands. The crates it
  brought stay stacked on the pad until it leaves.
- **Art is fetched when it is first needed.** A lab that only makes backups never fetches
  the welding loop or the shuttle.
- **It stops when nobody is looking.** The loop and the clips pause while the hero is off
  screen and while the page is hidden.
- **Reduced motion holds it still.** Nobody walks and no clip plays. Each crew member
  stands at its job, and each loop is held on one frame.

The module loads only when the hero is on screen. Until it and the station's drawing have
loaded, or if they can't, the hero's frame says how many jobs run and how many need you.

It works under the board's content policy the way Lamplight does: no `<style>` element,
no style attribute in markup, no inline handler and no `data:` URL. Every position is set
through the CSSOM. A job's words reach the page only as a hint's text, never as markup.

What it is handed is treated as untrusted (`sane.ts`). A state that isn't one of the
record's nine is never drawn. A share done that isn't a number from 0 to 100 is left
out, so the ring turns. The station's drawing is checked the same way: a room or a
machine whose name could reach another file's address stops the whole drawing, and the
plain state stands. `tests/post-hostile.spec.ts` holds this.

What ships (`public/post/`, [ASSETS.md](ASSETS.md)): 95 files, about 13 MB. All of it was
made on the lab with Apache-2.0 models, and `provenance.jsonl` has a line for each file.

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
  `bromigos server status`, `bromigos lab apps list` and `bromigos lab apps budget`, run on
  the stand-in machines their own tests use;
- **the board, the door, the session and the stream** come from the service's own reader
  and API, asked over HTTP with its test client.

It holds the answers of each request, and a board for each state the commands can leave it
in: healthy; a drive getting worse with a job asking; a job running; drives on watch and
unreadable; backups that need a look, are off, carry a Go Bag, or aren't a server's; an app
down; nothing installed; a stale reading; alerts with three channels of the server's own; a
box with a graphics card; jobs that ask with a choice that can't be undone, run and may be
stopped, or failed and may be started again, with the service's real refusals of each job
action; and each command missing or printing an error.

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
| `jobs` | A disk asks with a choice that can't be undone, a backup runs and may be stopped, one failed and may be started again; the server lets the page answer, stop and start again |
| `post` | Four jobs for the post's three crew: a disk asks, a backup runs, the lab makes a picture and a pipeline runs |
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
  that runs and ends; a job that names the AI agent that asked for it, and a name that
  isn't one left out; one job by its address; the stream's and the board's lists joined;
  the jobs unread; and that nothing but a GET is sent.
- **The post** (`tests/post.spec.ts`, `tests/post-unit.spec.ts`,
  `tests/post-hostile.spec.ts`):
  - On the page: a crew member at each job that runs or asks, with the record's own
    share done on its ring and its title in the hint; every room's name on its plate,
    inside the picture, and no other word on it; a figure, a machine and a room
    opening the job; a job that finishes or fails while the page is open, shown once;
    nothing replayed on load; four jobs for three crew; the loop stopping off screen and
    while the page is hidden; reduced motion; and the plain state when the script or the
    drawing doesn't arrive.
  - The walk: the crew's positions are read from the page while jobs start, end and
    re-send them part-way. No crew member may ever be off the floor.
  - Without a browser: the table, kind by kind; the door; every walk a chain of joined
    stops; and the model run through random job churn. After every step nobody is off the
    floor, and every job that runs has a crew member or a lit room.
  - Hostile jobs and a hostile drawing stay text, and no file of the module writes markup.
  - Every file the post can ask for ships, with its line of provenance.

  The test browser can't decode the rooms' clips (H.264). So the tests check which clip a
  room shows, not that it plays.
- **A job's controls** (`tests/jobs.spec.ts`): the answers, Stop and Start again as
  controls with the server's word and the job's, and the commands without; a choice that
  can't be undone asking for a code, with Back; and against the service's real refusals
  (`danger-needs-code`, `ended`), the bodies sent, a busy answer that keeps the code, and
  the new job's link after Start again.
- **The lab's jobs** (`tests/lab.spec.ts`): the generation that runs now with its picture,
  ring, stage and queue, moved on by the stream; the filter; stopping (a running one asks
  first); what ended jobs made, a 3D model on the table; the estimate without the relay
  node, with the commands where the page may not act; a media name the follower doesn't
  make never reaching a URL; every control's hint; and the phone. The fixtures `making` and
  `making-estimate` are the service's own `activity_lab` answer, with the repository's art
  as the pictures.
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
install script: the lock file pins every package by its hash. It builds a copy of
`board/web/`, so it names the repository's `mascot/` folder in `BOARD_MASCOT` for the
station's crew.

## The service

The service is the server's side of the board: the `bromigos-board` package. It is the API
the page reads, sign-in with a one-time code, the reader that gathers the readings as root,
and the site Caddy serves. The page's files come from `bromigos-board-web`. Until that
package is installed, Caddy serves a placeholder page that lists the door's apps.

The manual's [bromigOS Server](../manual/src/server.md#the-lab-board) page is the user's
side.

### What gets it

The provisioning catalogue's `board` item installs the `bromigos-board` package and sets it
up. The Home services, Media, Storage and Game server roles tick it. "Just a server" and
"Lab node" leave it off. The item needs Caddy, which the catalogue adds when it isn't
ticked ([lab-provision.md](lab-provision.md#the-catalogue)).

The board replaces the old start page (Homepage). Both answer at `home-<server>.local`, so
the catalogue lists them as conflicting, and the start page is no longer ticked for new
servers. A server that already runs the start page keeps it. Moving those servers to the
board is a later change.

### In a container

A lab that is a cluster has no server whose own page the board could be. There the board
runs as a workload: the image `ghcr.io/bromigos-org/bromigos-board`, behind the lab's own
ingress. It is the same board. The image holds the published packages `bromigos-board`
and `bromigos-board-web` and builds nothing, and a start script
(`board/container/bromigos-board-container`) does what a server's systemd units do, with
the same users and the same folders:

| Part | As | When |
|---|---|---|
| The API | `bromigos-board`, on `/run/bromigos-board.sock` | Always |
| Caddy, with the package's own site | `caddy`, on port 8080, plain HTTP | Always |
| The reader | root | When the page asks, as on a server |
| The lab follower | `bromigos-labjobs` | While a browser is signed in, when `/etc/bromigos/labjobs.toml` is there |

The action helper isn't started, and the settings the script writes allow no action:
there is no server under a container for the page to act on. If any part ends, the
container ends, and the cluster starts it again.

```sh
docker run -p 8080:8080 -e BOARD_ADDRESS=board.mylab.example \
  -v board:/var/lib/bromigos-board ghcr.io/bromigos-org/bromigos-board:edge
```

What to give it:

- **Its address.** `BOARD_ADDRESS` is the name people open (`board.mylab.example`). It
  becomes `[board] address` (below). Without it nobody can sign in through the ingress.
  Or mount your own `/etc/bromigos/server.toml`.
- **Its sessions.** A volume at `/var/lib/bromigos-board`, so browsers stay signed in when
  the container is replaced. It holds a few small files.
- **The lab's ComfyUIs.** Mount `/etc/bromigos/labjobs.toml` ([activity.md](activity.md#lab-jobs))
  for the lab's creation jobs to show on Activity and on the post. A relay token is a
  reference there (`@env:NAME` or `@file:/path`), never the token itself.
- **A fleet's status mirror.** In the same `labjobs.toml`, a `[[fleet]]` table with the
  mirror's address shows a fleet's tasks on Activity, on the post and on Home
  ([A fleet's tasks](#a-fleets-tasks)). The mirror must let the board's pods connect.

  ```toml
  [[fleet]]
  name = "tasks"
  url = "http://status-mirror.mylab.example:8082/v1/feed"
  ```
- **HTTPS at the ingress.** The session cookie is for HTTPS only. The ingress holds the
  certificate and sends plain HTTP to port 8080.

Signing in is the same code, asked for inside the container:

```sh
kubectl exec deploy/board -- bromigos-board code
```

**What it shows.** Activity and the post are whole: they are drawn from job records, and
the follower reads those from the lab's ComfyUIs and from a fleet's status mirror. The
pages about a server (its drives,
its apps, its updates) read the container itself, which has none, so they show their empty
states. Reading a cluster's own nodes and apps into those pages is not built yet.

**Who can reach it** is the ingress's to decide, not the board's. Behind an ingress every
request arrives from the ingress's own address inside the cluster, which is a private one,
so the board's "home network only" checks pass for everyone the ingress lets through.
Give the board an entry point that only your home network or your lab's private network
can reach. Wrong sign-in codes are counted for the ingress as one device: five in a
minute, for everyone together.

`[board] address` also suits a server behind a reverse proxy of your own:

```toml
[board]
address = "board.mylab.example"
```

It is one whole DNS name in lower case. The board then accepts a sign-in and every other
change sent to that name as well as to its own two, tells the page that the lab lives
there, and `bromigos server board code` names it. Only root's file can add a name: nothing
a browser or a proxy sends can. A value that isn't a plain name is ignored.

`board/container/test.sh IMAGE` starts the image and uses it: the page and the post's art,
the door, a sign-in at the address and at no other, the signed-in board and its jobs, a
stand-in ComfyUI followed, a stand-in status mirror followed and its tasks on the board,
each part as its own user, and a restart. CI runs it on every
pull request that touches the board's library or the image, and again before it publishes
(`.github/workflows/board-image.yml`). The image is built after `packages` has published
a main build, tagged `edge` and with the two packages' versions (the service's, then the
page's revision: `0.1.5.r21.gefb41ad-web.r23`), and signed with cosign. A tag with versions
never names two images; pin a deployment to it, or to the digest in the run's summary.

### Who can reach it

Only the home network and the lab's private network. Two places refuse any other address
with 403, so a mistake in one doesn't open the other:

- Caddy's site (`/usr/share/bromigos-board/caddy/site.caddy`) checks the address that
  connected, never a header.
- The API checks again (`bromigos_board/net.py`).

The addresses always let in are private ones (`10.0.0.0/8`, `172.16.0.0/12`,
`192.168.0.0/16`), link-local (`169.254.0.0/16`, `fe80::/10`), IPv6's unique-local range
(`fc00::/7`) and loopback. That holds even when the firewall's public `web` rule set is open
for something else.

The lab's private network ([lab-network.md](lab-network.md)) hands out addresses from
`100.64.0.0/10`. Some internet providers give their customers addresses from the same range.
So an address from that range says nothing by itself: it is let in only when the request came
in on the lab network's own interface, `tailscale0`.

- Caddy tells the API which of this server's addresses the connection came in at
  (`X-Bromigos-Local`, set by Caddy whatever the browser sent), and asks it each time
  (`GET /api/local`). The API says yes only when that is one of `tailscale0`'s addresses,
  which it asks the kernel for (rtnetlink). A neighbour in the provider's range comes in at
  the uplink's address, and is refused even while the lab network is up.
- The firewall decides by the interface too: the range is let in only on `tailscale0`
  ([server.md](server.md#the-firewall)).

The roles that set the board up open the web ports to the local network only (the
`web-lan` rule set). The page answers one more name, `home-<server>.local`, the old start
page's. That name tells browsers to use HTTPS only from then on (HSTS). `<server>.local`
doesn't: apps without a name of their own answer at `http://<server>.local:<port>`, and
that header would turn their links into `https`.

### Root and the board's user

Two users work for the board, and each stays out of the other's folder.

| Who | Does what | Writes where |
|---|---|---|
| `bromigos-board` | Runs the API | `/var/lib/bromigos-board`, its own (0700): sessions and codes |
| root | Runs the reader, the helper for [actions](#actions), and `bromigos server board code` and `sessions` | `/run/bromigos-board`, root's (0750, group `bromigos-board`): `board.json`, and the helper's answers in `results` |

- **Root never writes where the board's user can.** The board's user can read
  `/run/bromigos-board` and can't put a file, a link or anything else in it. The two files it
  marks there, `wanted` and `door`, are made by tmpfiles, as root's. One folder inside it is
  the board's user's, `requests`: root only reads and deletes there.
- **Root becomes the board's user before it touches the board's folder.**
  `sudo bromigos server board code` and `sessions` drop root for good first: no extra
  groups, then the board's group, then its user. A link planted where `codes` or `sessions`
  should be is refused, and nothing is deleted.
- **Where root writes, it trusts nothing in the folder.** A file gets a random temporary
  name, made exclusively and without following a link. Its mode and group are set on the
  open file, never by path. Then it's renamed into place (`paths.write_at`).
- **Each unit has only what it needs.** The API can write its own folder and mark the two
  files, in 256 MB of memory at most. The reader has `/usr`, `/boot` and `/etc` read-only.

The tests' stand-in switches (`BROMIGOS_ROOT`, `BROMIGOS_BOARD_HOSTNAME`,
`BROMIGOS_BOARD_NOW_MS`, `BROMIGOS_BOARD_CLI`) aren't honoured by a process that is root.
On a server, root's reader runs `/usr/bin/bromigos` by its whole path.

### Signing in

Signing in needs no account and no password. Run this at the server, at its console or over
SSH:

```bash
sudo bromigos server board code
```

```text
Sign-in code for the Lab board:  K7QM-3XPD

Open https://myserver.local on your home network and type it in.
It works once, until 2026-11-10 14:32 (10 minutes). Another code doesn't cancel this one.
```

Type the code on the board's page. The code works once and for ten minutes. A browser that
signs in stays signed in for 30 days.

To see the browsers signed in, and sign one out:

```bash
sudo bromigos server board sessions
sudo bromigos server board sessions --end 3f9a0c1d2e4b5a67
sudo bromigos server board sessions --end-all
```

Each command takes `--json`. `sessions` exits 1 when `--end` names no session.

#### For power users: sessions and codes

- A code is 8 letters from a 32-letter alphabet with no I, O, 0 or 1. It's shown as
  `ABCD-EFGH`. Case, spaces and dashes don't matter when you type it.
- Each code is kept as the SHA-256 of the code, in `/var/lib/bromigos-board/codes/`, with
  when it runs out. Signing in deletes the file, so a code works once even when two browsers
  send it at the same moment.
- Wrong codes are slowed, and nobody is locked out by someone else's:
  - one address may try five codes a minute. A try counts from the moment it is made, so
    five sent at once are five, and the sixth waits a minute (429), right or wrong. A right
    code doesn't count. An IPv6 address counts with the rest of its `/64`, since one device
    can take any address in it;
  - codes are checked one at a time, and after a wrong one the next check waits 200 ms. So
    at most five wrong codes a second are checked, from everyone together;
  - a right code is never refused because of another device's wrong ones. Under a flood of
    them it waits its turn: ten seconds at most, then the answer is 503 `busy`, and the door
    says "The server is busy: many codes are being tried at once. Your code wasn't used. Try
    it again in a moment." That try counts for nothing, and the code is still good.

  The same holds for a code typed to delete an app's data, or to answer a job's question
  that can't be undone. A code is 40 bits and lives ten minutes. At five guesses a second for
  all ten minutes, the chance of hitting one is about 3 in a billion.
- A session is a random 256-bit token. The browser keeps it in the cookie
  `__Host-bromigos-board`, which is `HttpOnly`, `Secure`, `SameSite=Strict` and lasts 30
  days. The server keeps only its SHA-256, in `/var/lib/bromigos-board/sessions/<id>.json`,
  with the browser's name ("Firefox on Linux") and when it was made. The file's own time is
  when the session was last used. Deleting that file ends the session at once, and an ended
  session never comes back.
- Every request that changes something passes a check against cross-site request forgery
  (CSRF), where another site makes your browser send a request:
  - it must carry the header `X-Bromigos-Board: 1`. A page on another site can't add a header
    without the API's permission, which the API never gives;
  - it must be sent to one of the board's two names, `<server>.local` or
    `home-<server>.local`, and its `Origin`, when the browser sends one, must be that same
    name;
  - its `Sec-Fetch-Site`, when sent, must be `same-origin`;
  - its body must be JSON, which a plain HTML form can't send.

### The door

Before sign-in the page is the door: the server's name and the household's app tiles. A tile
has an icon, the job ("Photos"), the app's name ("Immich") and the link that opens it. The
door also says which world the page wears and which ways to sign in there are. It never shows a state, a reading, a version, an address other than an app's link, or
anything from the server's own commands.

The door is built key by key from an allow-list (`bromigos_board/door.py`), so a new field in
the apps list never reaches it by itself. A tile is left out when:

- the app isn't installed;
- it's marked as not for the household (`household: false`; `null` counts as for it);
- it has no page;
- its link isn't a plain `http` or `https` address with a `.local` name.

To turn the door off, so the page shows nothing before sign-in, add this to
`/etc/bromigos/server.toml`:

```toml
[board]
door = false
```

`world` in the same table picks the world the page wears, by its theme's name, such as
`world = "tidewell"`. It's the Wick when left out.

### Where the readings come from

The board runs no command and reads no app itself. One reader does, as root:

1. While a signed-in browser has the page open, the API marks `/run/bromigos-board/wanted`.
2. `bromigos-board-snapshot.path` sees that and starts `bromigos-board-snapshot.service`.
3. The reader runs the commands below, all at once, and writes what they said to
   `/run/bromigos-board/board.json`. Only the board's group can read that file.
4. It reads again every 15 seconds. When nobody has looked for 45 seconds, it stops.

The door asks through a file of its own, `/run/bromigos-board/door`, for one reading, and
only when the last is more than two minutes old. So a device that isn't signed in can't
keep the reader running, and the door's tiles can be two minutes behind.

| Part | Command |
|---|---|
| `system` | `bromigos server status --json` |
| `storage` | `bromigos storage health --json` |
| `backups` | `bromigos lab backups status --json` |
| `activity` | `bromigos activity list --server --json` |
| `alerts` | `bromigos alerts --json` |
| `apps` | `bromigos lab apps list --json` |
| `budget` | `bromigos lab apps budget --json` |

A command that exits 1 with its JSON has still answered: 1 means it found a problem. A
command that is missing, fails or prints no JSON leaves its part `null`, and `sources` says
why. The page then says it can't check, rather than guessing.

`bromigos lab apps list --json` is the apps list, one tile per catalogue app
([lab.md](lab.md#apps-on-a-server)). On a server whose `bromigos` doesn't have it yet, the door
lists the catalogue's web apps that `bromigos lab provision --local` set up, as the start page
did.

`bromigos lab apps budget --json` is read for its `hardware`: the cores, the memory, the free
disk where apps keep their data, and whether there is a graphics card. It is the scan the
app manager fits apps against, and the only shipped command that prints it. Nothing the
reader runs measures how busy the machine is, so the board sends no such reading.

**The filter is the second line, and best effort.** The first line is that these commands
don't print secrets, and that only a signed-in browser sees `board.json`. The reader still
filters what it writes, a failed command's error line included:

- a value is dropped when its name says it's a secret: a password, a passphrase, a secret, a
  token, a key, a PIN, a seed, a cookie, a recovery or join code. Only `true`, `false`,
  `null` and the words `"set"` and `"not set"` stay under such a name: `"passwords": false`
  says SSH takes no passwords, and holds none. A drive's `key` in the drive reports stays: it's the drive's id;
- a name is read by its words, and its last word says what the value is. `api_key`,
  `DB_PASSWORD` and `token_b64` are secrets. `last_test_passed`, `key_count`, `token_ttl`,
  `secret_store` and `public_key` are a result, a count, a time, a place and a public key,
  and they stay;
- `{"name": "admin_token", "value": "…"}` loses its value;
- in text, a `user:password@` part of an address is cut, and `NAME=value`, a secret in a
  link's query, an option such as `--password` with the word after it, and tokens with a
  known shape are masked. The activity records' own filter does most of this
  (`bromigos_activity.redact`);
- under any name and in any text, a PEM private key (`-----BEGIN … PRIVATE KEY-----` to its
  end line) and a JSON Web Token are masked. `pin_code` is a code that lets someone in, like
  `join_code`.

It can't recognise a secret written out in a sentence, or under a name that says nothing.

### The API

The API is Starlette on uvicorn. It listens on `/run/bromigos-board.sock`, which systemd
opens (`bromigos-board.socket`) and only Caddy's group can use. It runs as its own user,
`bromigos-board`, with no capabilities and no network of its own
(`bromigos-board.service`). Caddy serves the page's files from
`/usr/share/bromigos-board/web` and passes `/api/` to the socket.

No request to the board is big. Caddy refuses a body over 8 KB, and the API one over 4096
bytes: by its `Content-Length` without reading it, and after 4096 bytes when it gave none.
The API takes 64 connections at once (more get 503) and 256 MB of memory.

Every answer is JSON with `Cache-Control: no-store`. An error is
`{"error": {"code": "…", "words": "…"}}`, where `words` is a sentence for a person.

| Request | Who | Answer |
|---|---|---|
| `GET /api/door` | anyone it lets in | The door |
| `GET /api/local` | anyone it lets in | 204, and nothing else. Caddy asks it for the lab network's addresses |
| `GET /api/session` | anyone it lets in | Whether this browser is signed in, and the browsers that are |
| `POST /api/session` `{"code": "K7QM-3XPD"}` | anyone it lets in | Signs in, sets the cookie |
| `DELETE /api/session` | signed in | Signs this browser out |
| `DELETE /api/session/<id>` | signed in | Signs that browser out |
| `GET /api/board` | signed in | The board, worked out from the reader's `board.json` |
| `GET /api/activity` | signed in | The jobs, live, as server-sent events |
| `GET /api/fleet` | signed in | A fleet's tasks, business by business ([A fleet's tasks](#a-fleets-tasks)) |
| `POST /api/actions` | signed in | Restarts, adds or removes an app, as a job ([Actions](#actions)) |

The status codes:

| Code | `error.code` | Means |
|---|---|---|
| 401 | `signed-out` | Sign in first |
| 403 | `not-local` | The address isn't the home network's or the lab's |
| 403 | `csrf` | The request didn't come from the board's own page |
| 401 | `bad-code` | The code is wrong, or was used already |
| 401 | `expired` | The code is older than 10 minutes |
| 404 | `no-session` | No browser is signed in with that id |
| 413 | `too-big` | The body is over 4096 bytes |
| 415 | `not-json` | The body isn't JSON |
| 429 | `too-many` | Too many wrong codes from this address. `Retry-After` says when to try again |
| 503 | `gathering` | The first reading isn't there yet. `Retry-After: 5` |
| 503 | `busy` | (signing in) Many codes were being checked at once, and this one waited ten seconds without its turn. `Retry-After: 5` |

`GET /api/door`:

```json
{"schema": 1, "lab": {"name": "myserver", "address": "https://myserver.local"},
 "server": {"name": "myserver"}, "world": "wick", "door": true,
 "tiles": [{"id": "photos", "job": "Photos", "app": "Immich", "holo": "photos", "group": "home",
            "open": {"url": "https://photos-myserver.local"}},
           {"id": "uptime", "job": "Uptime", "app": "Uptime Kuma", "holo": "uptime", "group": "home",
            "open": {"url": "http://myserver.local:3001/dashboard"}}],
 "signin": {"code": true, "phone": false, "account": false}}
```

A single server is its own lab, so `lab` names the server. `signin` says which ways in this
server offers: only the console code, for now.

`GET /api/session`, before and after sign-in:

```json
{"schema": 1, "signed_in": false, "role": null, "browser": null, "expires_at": null, "browsers": []}
{"schema": 1, "signed_in": true, "role": "owner",
 "browser": {"id": "3f9a0c1d2e4b5a67", "name": "Firefox on Linux"}, "expires_at": 1796882000000,
 "browsers": [{"id": "3f9a0c1d2e4b5a67", "name": "Firefox on Linux", "signed_in_at": 1794290000000,
               "last_seen_at": 1794290000000, "expires_at": 1796882000000, "current": true}]}
```

`GET /api/board` passes the cards' commands through unchanged, and works out what the page
draws first from those same documents:

```json
{"schema": 1, "at": 1794290000000, "max_age_s": 45, "age_s": 4, "stale": false,
 "lab": {"name": "myserver", "address": "https://myserver.local"},
 "server": {"name": "myserver", "kind": "server", "roles": ["home-services"]},
 "status": {"state": "needs-you", "words": "1 thing needs you.", "checked_at": 1794290000000},
 "machines": [{"name": "myserver", "kind": "server", "here": true, "page": true, "state": "warn",
               "state_word": "needs you", "roles": ["home-services"], "updates": null, "readings": null,
               "hardware": {"cpu": 4, "ram_gb": 16, "disk_gb": 512, "gpu": false, "gpu_kind": null,
                            "gpu_name": null, "gpu_vram_gb": 0},
               "apps": 6}],
 "needs_you": [{"id": "update.restart", "machine": "myserver", "subject": null, "severity": "warn",
                "words": "A restart finishes the update",
                "detail": "The kernel was updated. Restart when it suits you.",
                "since": 1794200000000, "go": "supply/updates", "job": null}],
 "fixed": [{"id": "20261110-0530-app.update-photos-1a2b", "machine": "myserver", "title": "Updating Photos",
            "words": "Photos didn't answer after the update, so it was put back.", "at": 1794260000000}],
 "apps": ["… bromigos lab apps list --json's apps"],
 "storage": "… bromigos storage health --json",
 "backups": "… bromigos lab backups status --json",
 "updates": {"updates": "… bromigos server status --json's updates", "rollbacks": []},
 "ups": {"found": false},
 "actions": ["restart", "add", "remove", "delete-data", "job.answer", "job.cancel", "job.retry"],
 "sources": {"storage": {"command": ["bromigos", "storage", "health", "--json"], "at": 1794289999000, "ok": true, "rc": 1},
             "apps": {"command": ["bromigos", "lab", "apps", "list", "--json"], "at": 1794289999000, "ok": false, "rc": 2,
                      "why": "bromigos lab: no command apps"}},
 "system": "… bromigos server status --json", "activity": "… bromigos activity list --server --json",
 "alerts": "… bromigos alerts --json", "host": "myserver", "settings": {"door": true, "world": "wick"}}
```

- `status` is the one line for the whole server, and it never says more than was read.
  `status.words` is "Everything is running." only when every part was read and nothing in
  them says otherwise. In order, worst first:

  | `status.state` | When | `status.words`, for example |
  |---|---|---|
  | `unknown` | the reading is more than 45 seconds old (`stale`) | Can't check right now: the last reading is old. |
  | `needs-you` | something is in `needs_you` | 2 things need you. |
  | `needs-you` | an installed app is `down` or `degraded` | Photos isn't running. |
  | `needs-you` | the backups' health is `attention` | the backups' own verdict |
  | `setup` | the apps list was read and nothing is installed | Nothing is set up yet. |
  | `unknown` | a part couldn't be read: the alerts, the jobs, the apps, the drives' health, the backups or the system's status | Can't say everything is running: the alerts couldn't be read (bromigos: no such command). |
  | `ok` | none of the above | Everything is running. |

  The reason in brackets is `sources.<part>.why`, or what the command's error document said.
- `machines[].state` is the machine's own row: `unknown` when the reading is old, `warn` when
  something on it is in `needs_you`, else `ok` ("online"). A machine that answered is never
  "can't check" because one part couldn't be read: that is the status line's to say.
- `machines[].hardware` is what is in the box, from the app manager's scan: `cpu` (cores),
  `ram_gb`, `disk_gb` (free where apps keep their data), `gpu` (true or false), `gpu_kind`
  (`"nvidia"`, `"amd"` or null), `gpu_name` (null: the command doesn't print it yet)
  and `gpu_vram_gb`. It is null when `bromigos lab apps budget` didn't answer. The drives
  aren't repeated there: `storage.drives` has them.
- `needs_you` lists the alerts a person must act on (severity `needs_you`, shown as `warn`,
  or `critical`), then the jobs waiting for an answer. `go` names the part of the page that
  owns the fact: `data`, `data/backups`, `supply/updates` or `activity`.
- `fixed` lists the jobs that failed and put things back by themselves (`rolled-back`):
  `title` is the job's own ("Updating Photos"), `words` what became of it.
- `actions` lists what the page may ask for on this server: root's `[board] actions`
  ([What a session can do](#what-a-session-can-do-and-how-to-turn-it-off)), and `[]` when
  actions are off or aren't set up. The page shows a control only for a word that is there.
  The list is for the page's sake: root's helper decides again on every request.
- `readings` and `updates` in `machines` are null: nothing the reader runs measures how busy
  a machine is, or counts its waiting updates, yet.

Times are milliseconds since 1970, UTC.

`GET /api/activity` is a stream of server-sent events:

| Event | Data |
|---|---|
| `snapshot` | First: `{"schema": 1, "jobs": [...]}`, at most 50 records as `bromigos activity list --json` gives them |
| `job` | A record that is new or changed ([the record](activity.md)) |
| `gone` | `{"id": "…"}`: a record that was pruned |
| `signed-out` | The session ended. The stream stops |

A comment line, `: keep-alive`, comes every 20 seconds.

### Actions

Signed in, the page can restart an app, add one, or remove one. Each is an activity job
([activity.md](activity.md)), so it carries on when the page closes, and the strip shows its
steps. The page asks:

```json
POST /api/actions
{"verb": "restart", "app": "photos"}
```

#### What a session can do, and how to turn it off

A signed-in browser can do all of this until its session ends, 30 days later at most:

- see everything the board shows;
- restart any app this server runs;
- add any app in the catalogue, file sharing and game servers included;
- remove an app, keeping its data;
- answer the question a job asks, stop a job that says stopping is safe, and start again a
  job that ended badly and was started as safe to start again
  ([A job's own actions](#a-jobs-own-actions)).

It can't delete an app's data, run a command, read a file or change a setting. Deleting
data needs a fresh code from the server each time ([below](#deleting-an-apps-data)), and so
does an answer that a job marks as can't be undone
([A job's own actions](#a-jobs-own-actions)).

So a stolen session cookie can add and remove apps. If that is more than you want from a
browser, say which actions the page may use, as root, in `/etc/bromigos/server.toml`:

```toml
[board]
actions = ["restart"]        # only restarts; [] turns every action off
```

Left out on a new install, it means `["restart", "add", "remove", "delete-data",
"job.answer", "job.cancel", "job.retry"]`. With `[]` the page only shows what the server is
doing, and you add and remove apps with `sudo bromigos lab apps`. The board's document
carries the list as `actions`, so the page offers only what the server allows.
`sudo bromigos server board sessions --end-all` signs every browser out at once.

**An upgrade never widens it.** Browsers already signed in were let in for what the board
could do then. So when the package is upgraded on a server whose `server.toml` doesn't say
`[board] actions`, the upgrade writes in the list the board allowed before, and says so:

- from a board that could only look: `actions = []`;
- from a board with the app actions but not the job actions:
  `actions = ["restart", "add", "remove", "delete-data"]`.

To have the new default, remove that line (or list the words you want). A server that names
its own list keeps it, and a new install writes nothing, so it gets the new default.

#### How a request reaches root

The API runs as an ordinary user. It can't do any of this itself, and it has no right to
start anything: there is no polkit rule and no `sudo`. Two folders carry a request across
and its answer back, and each side writes only one of them.

| Folder | Whose | Holds |
|---|---|---|
| `/run/bromigos-board/requests` | the board's user's | `<id>.json`, a request, where `<id>` is 16 random hex digits |
| `/run/bromigos-board/results` | root's; the board's group reads it | `<id>.json`, root's answer |

1. The API checks the request's shape and writes it, whole, into `requests`.
2. `bromigos-board-act.path` sees that the folder isn't empty and starts
   `bromigos-board-act.service`: `bromigos-board act`, as root, in a sandbox.
3. The helper takes every request out of the folder, one at a time. It reads each once and
   deletes it, then checks it again:
   - it's a plain, small file that the board's user wrote, at most a minute old. A link is
     never followed and a FIFO never waited on;
   - the verb is one of `restart`, `add` and `remove`, the commands of `bromigos lab apps`;
   - the app is an id in the provisioning catalogue;
   - root's `[board] actions` lists the verb.
4. It builds the command itself, from those checked words only, and starts it as a job:

   ```bash
   /usr/lib/bromigos/bin/bromigos-activity run --kind app.restart --title "Restarting Photos" \
     --subject app:photos:Photos --lock apps --via board --device "Firefox on Linux" --detach --json \
     -- /usr/bin/bromigos lab apps restart photos
   ```

5. It writes its answer into `results`, and the API passes it on. The answer's words are
   fixed for each outcome: nothing the request said is ever quoted in it.
6. It waits three seconds for more requests, then ends. A request that arrives while it
   runs is handled in the same run. One that arrives as it ends starts it again, because
   the path unit looks at the folder when the service stops. Each request is handled once,
   since reading it deletes it.

No word of the request reaches a shell, and there is no "run this" request. Anything else
the helper finds in the folder is removed: a link, a folder, a request left half-written a
minute ago. So is anything named like a request that isn't a plain file of the board's user,
once it has been refused: a folder named `<id>.json` included.

**The helper's sandbox.** It is root, and the unit lets it write five places only: the two
folders above, the board's own folder and root's (for the codes, below), and the activity
records (`/var/lib/bromigos/activity`, or `/var/lib/bromigos/server/activity` on a Server,
where that folder lives). `/etc`, `/usr` and the rest of the system are read-only to it,
and `/home` and `/root` are out of sight. It has no network but the socket it tells systemd
to start the job with. The job itself runs in a unit of its own, outside this sandbox.

**A refusal is an answer, not a failure.** The helper ends with status 0 once its answers
are written, and its unit isn't kept once it has ended (`CollectMode=inactive-or-failed`).
A failed unit would count against the next update's health check
([server.md](server.md#how-health-is-judged)).

#### Deleting an app's data

Removing an app keeps its data. To delete the data too, the request carries
`"delete_data": true` and a code from `sudo bromigos server board code`, typed again for
it. The session alone isn't enough.

Root keeps its own note of every code it makes, in `/var/lib/bromigos-board-root/codes`,
which only root can read or write. The board's own record of the code is in
`/var/lib/bromigos-board/codes`. The helper takes a code for a deletion only when both
records are there, and removes both. So:

- a code the board's user made itself deletes nothing, because root never noted it;
- a code that signed a browser in deletes nothing, because signing in removed the board's
  record;
- a code works for one deletion, and can't sign a browser in afterwards.

Then the helper runs `bromigos lab apps remove <app> --delete-data --yes`.

One limit: root can't see a sign-in. It trusts the board's record to say a code is unused.
If the API itself were taken over, it could keep a code that you typed to sign in and
spend it on a deletion instead. It could never make a code of its own.

#### A job's own actions

The page can also act on a job that is already there, whoever started it:

```json
POST /api/activity/20261110-1904-drive.replace-bay-2-7c1e/answer
{"question": "swapped", "choice": "swapped"}

POST /api/activity/20261110-0300-backup.run-myserver-4f1a/cancel
{}

POST /api/activity/20261110-0530-app.update-photos-1a2b/retry
{}
```

These go to root the same way as an app's action: the API writes a request, and root's
helper takes it out and checks it again. For a job the check is against root's own record
of it ([activity.md](activity.md)):

1. The id must be a job's whole id, and a record with exactly that id must be there. A part
   of an id, which names a job at the terminal, names none here.
2. `[board] actions` must list `job.answer`, `job.cancel` or `job.retry`.
3. The job must be in a state that allows it. An answer needs the job to be asking the
   question the request names, and the choice to be one of that question's. The question's
   id is in the request so that an answer to a question that was since replaced is refused.
   Stopping needs the job to say that stopping now is safe. Starting again needs a job that
   ended failed, put back, cancelled or interrupted, and was started as safe to start again.
   **A choice the job marks as can't be undone** (`[wipe!]` in its `::ask` line, `"danger":
   true` in the record) also needs a fresh code from `sudo bromigos server board code`, sent
   as `"code"` with the answer, exactly as deleting an app's data does: root takes it only
   when its own note of the code is there, uses it up, and a code that signed a browser in
   doesn't count. It doesn't matter who started the job: one started at the terminal with
   `sudo` asks the page for the code too. Wrong codes are counted and slowed as at sign-in.
4. Then the helper runs `bromigos activity answer JOB CHOICE`, `cancel JOB` or
   `retry JOB --via board`, with the id and the choice it checked. Nothing else in the
   request reaches the command.

The command checks once more as it acts, and what it refuses comes back as the same codes.

| Code | `error.code` | Means |
|---|---|---|
| 202 | | Done, or passed on: `{"ok": true, "job": "<id>", "words": "Answered."}`. For `retry`, `job` is the new job's id. When root hadn't answered within 10 seconds, the words say to watch the job's card, and `job` is null for a retry |
| 404 | `no-job`, `unknown-verb` | No job has that whole id; or the last word isn't `answer`, `cancel` or `retry` |
| 409 | `not-asking`, `bad-choice` | The job isn't asking that question now; or that isn't one of its answers |
| 403 | `danger-needs-code` | That choice can't be undone, and no fresh code came with it (or a wrong, used or late one) |
| 429 | `too-many` | Too many wrong codes from this address |
| 409 | `not-safe` | The job hasn't said that stopping it now is safe. Its record's `cancel_note` says why |
| 409 | `ended` | The job has already ended |
| 409 | `cant-retry` | The job didn't end badly, or wasn't started as safe to start again |
| 409 | `not-taken` | The job didn't take the answer or the stop in time. Look at its card and try again |
| 403 | `not-allowed`, `too-old`, `bad-request` | `[board] actions` doesn't list it; or root's helper refused the request |
| 503 | `no-actions` | The requests folder isn't there: actions aren't set up |

Every refusal's words are the board's own, fixed sentences. They never repeat what the
request said, or what the job said.

Stopping a job can take as long as the job takes to stop: up to 25 seconds. While root's
helper waits for it, other requests wait their turn.

#### The answers

| Code | `error.code` | Means |
|---|---|---|
| 202 | | Started: `{"ok": true, "job": "<activity id>", "words": "Restarting Photos."}`. `job` is null when root hadn't answered within 10 seconds; the job still shows in the activity stream |
| 400 | `unknown-verb`, `unknown-app`, `needs-code`, `bad-request` | The request isn't one the board makes |
| 403 | `unknown-app` | The app isn't in the catalogue |
| 403 | `not-allowed` | `[board] actions` doesn't list it |
| 403 | `needs-code` | The code for deleting data is wrong, used, out of date, or one that signed a browser in |
| 403 | `too-old`, `bad-request`, `job-failed` | Root's helper refused the request, or the job didn't start |
| 429 | `too-many` | Too many wrong codes from this address |
| 503 | `no-actions` | The requests folder isn't there: actions aren't set up |

A wrong code for a deletion is counted and slowed like a wrong code at sign-in.

### The lab's jobs

Activity also shows what the lab is making: each ComfyUI generation and each run of a tool
that writes a job feed ([activity.md](activity.md#lab-jobs) has the sources, the record and
the feed format).

**On the page.**

- **MAKING NOW.** The generation that runs now is the page's hero:
  - the picture as ComfyUI makes it, on glass, with a progress ring;
  - its stage (`Sample · 21 of 50 steps`) and its stages;
  - how long it has taken, and how long that workflow usually takes;
  - the prompt, and the queue behind it on the same ComfyUI.
- **The other jobs.** A queued generation and a pipeline run are cards in GOING. An ended
  one shows what it made: a picture, a clip that plays without sound, or a 3D model. A 3D
  model turns on the projection table in the shipped hologram renderer (`lib/holo`, read
  with three.js's GLTFLoader).
- **The filter.** Three toggles over the list pick all jobs, this server's, or the lab's.
- **The ComfyUIs.** A line names each ComfyUI the follower reads. "live" means its progress
  and pictures come live. "queue and results" means the relay node isn't installed there,
  so progress is an estimate, and the card says ESTIMATE.

Stopping a generation is the job's own Stop (`job.cancel` in `[board] actions`). A queued
generation leaves the queue at once. A running one is interrupted, and the card asks first,
because what it made so far is lost. A pipeline run can't be stopped from the page: the
program that writes it stops it.

**On the server.** The API has no network, so a follower of its own reads the lab:

- `bromigos-board-lab.service` runs `bromigos activity follow --system` as its own user,
  `bromigos-labjobs`. When the API marks `wanted`, `bromigos-board-lab.path` starts
  `bromigos-board-lab-start.service`, as root. That writes the follower's addresses (below)
  and starts it. It stops when nobody has looked for 45 seconds.
- It reads the ComfyUIs in `/etc/bromigos/labjobs.toml`, and only those: this machine's own
  too must be named there (`url = "http://127.0.0.1:8188"`). Setting up the Creation studio
  writes that file once, naming the studio; after that it is yours. It reads the system's feed
  folder, `/var/lib/bromigos/activity/feed`, too.
- It may connect to those ComfyUIs' exact addresses and nowhere else. The starter writes them
  to `/run/systemd/system/bromigos-board-lab.service.d/50-allow.conf` (`IPAddressAllow`,
  resolved from labjobs.toml; `bromigos activity follow --allow-dropin`), and systemd reloads
  when they changed. With no labjobs.toml it may connect nowhere. It follows no redirect. It
  can't bind a socket, so it opens no port. It writes only its two folders.
- With the relay node's token (labjobs.toml's `relay_token`, a file the `bromigos-labjobs`
  user can read, such as `/etc/bromigos/comfyui-relay.token`, 0640, group
  `bromigos-labjobs`), it gets every prompt's progress and pictures live.
- It writes `/run/bromigos-labjobs/jobs.json`, and keeps previews, thumbnails and outputs in
  `/var/cache/bromigos-labjobs/` (512 MB at most). Both folders are setgid
  `bromigos-board`, so the API's group reads them.

The API passes these on:

| Route | What |
|---|---|
| `GET /api/activity` | The lab's records join the stream, from `jobs.json` only. A feed's own paths are never in them |
| `GET /api/lab` | `{following, at, instances: [{name, state, words, live, relay}]}`: the follower's word on each ComfyUI |
| `GET /api/lab/media/NAME` | One of the follower's files. NAME must be one the follower makes (`pv-`, `th-`, `of-`, `fm-`, 16 hex digits, a picture, clip or model type). The file is opened once without following a link, must be a regular file owned by `bromigos-labjobs`, and is sent from that open file; anything else is 404. Served with its own type, `nosniff`, a sandboxing policy, and kept by the browser (the name is the content) |

A Stop goes the existing way: the page, the requests folder, root's helper, then
`bromigos-activity cancel ID --json`. That command has no network inside the helper's
sandbox, so it hands the request to the follower through root's folder
`/run/bromigos-labjobs-asks/`, which the follower only reads. The follower checks ComfyUI's
queue again, acts on that one prompt (`POST /queue {"delete": [ID]}`, or `POST /interrupt
{"prompt_id": ID}`), and answers in `/run/bromigos-labjobs/answers/`.

```bash
sudo systemctl status bromigos-board-lab.service       # the follower
sudo cat /run/bromigos-labjobs/jobs.json | head         # what it last wrote
bromigos activity list --lab                            # the same jobs at a terminal
```

### A fleet's tasks

A *fleet* is a set of coding agents that work through the issues of one business's
repositories by themselves ([lab.md](lab.md#tasks)). Its *tasks* show on the board as jobs:
on Activity, on the post, and in Home's "what needs you". The service has it all. The page
has no Tasks page of its own yet, so it shows each task with the job card it already has.

**Where the tasks come from.** The fleet's scheduled job writes a *feed*: one JSON
document that says what every task is doing. The follower reads it from one of two places,
named in `/etc/bromigos/labjobs.toml`:

```toml
[[fleet]]
name = "tasks"
url = "http://status-mirror.mylab.example:8082/v1/feed"
```

| Option | What it does |
|---|---|
| `url` | Your lab's *status mirror*: a small service of the fleet's own, inside the lab, that holds each business's newest feed. bromigOS doesn't ship one. |
| `file` | A feed file on this machine instead, as an absolute path. It holds a mirror's answer, or one feed. |
| `business` | Keep one business of the mirror's, by the mirror's name for it. Without it, every business. |
| `name` | The source's name. Give each `[[fleet]]` table its own. |

A table has `url` or `file`, not both. The board itself holds no GitHub login and asks
GitHub nothing.

**How the follower reads it.**

- It asks each source once a minute at most, and sends the last answer's `ETag` back. An
  unchanged answer is a 304 with no body.
- It keeps the last report in `/run/bromigos-labjobs/fleet.json`, beside `jobs.json`. A
  mirror is empty for up to ten minutes after its own restart, until the fleet's next run.
  The board then still shows the last report, and says the mirror has no report yet.
- The same holds when the mirror doesn't answer. The follower says so once in its log.
- It reads a mirror with no proxy, no redirect, a whole deadline of 15 seconds and a cap
  of 2 MB. It reads a feed file as it reads a job feed: never through a link, and only
  when root or the folder's owner owns it.
- On a server, the follower's unit may connect to the mirror's exact addresses, added to
  the same drop-in as the ComfyUIs' (`bromigos activity follow --allow-dropin`).
- It asks no more often because tasks are running. A fleet's own run takes ten minutes.

The lab console's library reads the feed, checks it and cleans every text in it
(`bromigos_homelab.fleet`, from `bromigos-lab`). The follower and the API use that one
reader, so the board says the same words as `bromigos lab tasks`.

**A task as a job record.** The follower makes one record of kind `agent.task` per task,
and writes them into `jobs.json` with the lab's other jobs
([activity.md](activity.md#a-fleets-tasks) has every field):

| The task's lane | The record's state | On the page |
|---|---|---|
| Needs you | `needs-you`, with no question | A card marked NEEDS YOU, in the list of jobs that ask |
| Working | `running` | A card in the going list, and a crew member on the post |
| Waiting | `queued` when its phrase says Queued, else `waiting` | A card in the going list |
| Done, merged today | `succeeded` | A card in the ended list |

Proposed tasks, and work that ended without a merge, have no record. `GET /api/fleet` has
them.

A record carries the task's *phrase* ("Stuck · …", "Fixing · round 2") as its stage and as
its one step, so the card shows it. Its notes hold the task's links as words, which the job's
sheet lists. The record says "by agent" and the business's name, as every job an AI agent
asked for does. A task that needs you has no question, because it is answered in its
repository and not on the page. So the card offers no answer and no command.

**What the page shows today.** This is read from the page's code, not from a browser:

- **Activity.** `components/JobCard.tsx` draws a record that has no `lab` object as a
  server's job: the title, a line with the state, the kind, when it started and "by agent
  example", the one step with the phrase, and the state's chip. The job's sheet (`#job/ID`)
  adds the notes, where the links are, as text. The filter counts tasks among "This
  server's jobs", since that is every job without a `lab` object.
- **The post.** A kind that starts with `agent.` goes to the hologram table
  ([Which job goes where](#which-job-goes-where)), and so does any job an agent asked for.
  A running task has a crew member working there. One that needs you has one standing on
  an amber ring. A queued or waiting task isn't drawn, like every such job.
- **Home.** Each task that needs you is a row under "what needs you": its title, its
  phrase, and the business where a machine's name stands. It opens the job's sheet. The
  status line counts it. It doesn't count against the server's own row, because a task is
  on no machine.

**A report that is old.** The feed says when it goes stale, 90 minutes after it was
written. Past that, the fleet's job isn't running. The records then say so rather than
vanish:

- A task that needed you still does. Its step says the report is old.
- A task that was running or waiting reads `interrupted`, with why: "The fleet hasn't
  reported since 12:40 (1 h 40 min ago). It was: Writing." Nothing says it still runs, so
  the post draws nobody for it.
- A day past stale, the report has no records any more. `GET /api/fleet` still has it.

A task that leaves the feed loses its record at the next look.

**The API.** `GET /api/fleet`, signed in, answers the fleets' document from `fleet.json`.
It is the document `bromigos lab tasks --json` prints ([lab.md](lab.md#the-command)), with
three things more:

```json
{"schema": 1, "generatedAt": 1795866720, "configured": true, "state": "warn", "following": true,
 "fleets": [{"source": "tasks", "mirror": "example", "received_at": "2026-11-28T11:40:09Z",
             "business": "Example", "state": "fresh", "fresh": true,
             "headline": "3 need you · 2 proposed · 3 working · 1 waiting · 4 merged today",
             "lanes": [{"id": "needs_you", "title": "Needs you", "count": 3, "rows": [{"label": "app#41", "…": "…"}]}],
             "accounts": [{"number": 2, "state": "resting", "phrase": "Resting until 15:45"}],
             "schedules": [{"id": "weekly-review", "last_words": "filed a digest and 1 ticket"}],
             "warnings": []}],
 "errors": {},
 "sources": [{"name": "tasks", "state": "ok", "words": "", "checked_at": 1795866720000, "read_at": 1795866720000}]}
```

- `fleets[].mirror` and `received_at` are the mirror's name for the business and when it
  got the feed.
- `sources` is the follower's word on each `[[fleet]]` table: `ok`, `empty` (no report
  yet) or `down`, and when it last asked and last read.
- `following` is false while the follower hasn't written for 15 seconds. The report is
  then the last one it kept.

`state` is `ok`, `warn`, `unreachable` or `empty`, and `errors` says in words what couldn't
be read. With no `[[fleet]]` table, `configured` is false and `fleets` is empty.

`bromigos-board`, `bromigos-core` and `bromigos-lab` are three packages. A board that is
newer than the other two answers `GET /api/fleet` with no fleets and says which package to
update. It never fails.

**Text other people wrote.** A task's title and a reason come from whoever wrote the
issue. The feed's reader removes escape sequences, control characters and invisible
characters, puts each text on one line and cuts it, before anything is kept. So
`fleet.json`, the records and the API's answers hold plain text. An address that isn't a
plain `http` or `https` one is left out. The page then draws every string as text, as it
does all its data.

```bash
sudo cat /run/bromigos-labjobs/fleet.json | head       # the last report of each fleet
bromigos activity list --lab                           # the tasks, with the lab's other jobs
bromigos activity show task.example.app.41             # one task, with its links
```

### The files

| Path | What |
|---|---|
| `/usr/lib/bromigos/board/bromigos-board` | The board's own command: `serve`, `snapshot`, `code`, `sessions`, `act`, `keep-actions` |
| `/usr/lib/bromigos/lib/bromigos_board/` | Its library |
| `/usr/share/bromigos-board/caddy/site.caddy` | The site's rules, imported by the server's Caddy site |
| `/etc/caddy/conf.d/bromigos-board.caddy` | The site, written by the catalogue's `board` step for `<server>.local` and `home-<server>.local` |
| `/usr/share/bromigos-board/web/` | The page's files (`bromigos-board-web`) |
| `/usr/share/bromigos-board/placeholder/` | The placeholder Caddy serves until the page is installed |
| `/run/bromigos-board/board.json` | The reader's last reading |
| `/run/bromigos-board/wanted`, `door` | The two files the API marks to ask for readings |
| `/var/lib/bromigos-board/` | Sessions and codes, the board's user's only |
| `/run/bromigos-board/requests/` | The page's actions, waiting for root's helper. The board's user's |
| `/run/bromigos-board/results/` | The helper's answers. Root's |
| `/var/lib/bromigos-board-root/codes/` | Root's own note of each code it made. Root's only |
| `/run/bromigos-labjobs/` | The lab follower's `jobs.json`, its answers, and `fleet.json`, each fleet's last report. The `bromigos-labjobs` user's, read by the board's group |
| `/var/cache/bromigos-labjobs/` | The lab's previews, thumbnails and outputs. The same |
| `/run/bromigos-labjobs-asks/` | What root's helper asks the follower (stopping a generation). Root's |
| `/etc/bromigos/labjobs.toml` | The ComfyUIs, feed folders and fleets the follower reads ([activity.md](activity.md#which-comfyuis)) |

### The service's tests

```bash
cd board
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests
```

They need `python-starlette`, `uvicorn` and `python-httpx`. With `caddy` installed, they
also check that Caddy reads the site and puts its 403 first. With `systemd-analyze`, they
have systemd check the units' text. The `board-tests` workflow runs them on every pull
request that touches `board/`.

`test_fleet.py` covers a fleet's tasks: `GET /api/fleet`, the tasks on the stream, Home's
count, a stale report, hostile titles, and a server whose other packages are older. The
follower in it is the real one, reading a recorded feed with made-up names.

The same workflow runs `board/tests/board-integration.sh` on a throwaway machine, as real
root under its real systemd. It installs the board where the package puts it, then checks
what a stand-in root can't show: who owns each folder once tmpfiles made them, that the
board's user can put nothing in root's folder, that root's files in the board's folder are
the board's user's, that a link planted there is refused, and that each unit works inside
its sandbox. For actions it checks that the board's user can start nothing, that a burst of
requests is each handled once with none lost, that a refusal fails no unit, and that a code
the board's user made deletes nothing. Never run it on a computer you use.

### Not built yet, on the server's side

- A Tasks page for a fleet's tasks. The service answers `GET /api/fleet`; the page doesn't
  ask it yet, and shows each task as a job ([A fleet's tasks](#a-fleets-tasks)).

- Updating an app or putting its last version back: `bromigos lab apps` doesn't do those yet.
- Signing in from the phone, or with a Bromigos account.
- The lab's own address, and the lab's other machines on one server's page.
- Moving servers that run the start page onto the board.
