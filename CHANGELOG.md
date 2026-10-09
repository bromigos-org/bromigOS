# Changelog

Every change to bromigOS and VECTOR, release by release: the technical log, made from the commit
subjects by git-cliff (tools/release/cliff.toml) when a release is prepared (docs/release.md).
What a release means for the people using it, in plain words, is the manual's What's new
(manual/src/whats-new.md).

This repository's history starts at 0.1.2. The commits before it, which the links in the
0.1.2 section and below name, are in the archives, `bromigos-org/bromigOS-archive` (and
VECTOR's, `bromigos-org/vector-archive`).

<!-- releases: tools/release/release.py adds each release below this line, newest first -->

## [0.1.3] - 2026-10-09
<!-- release: 0.1.3-rc1 -->

Release candidate v0.1.3-rc1.

Since v0.1.2. In plain words: the manual's What's new (manual/src/whats-new.md).

No changes.

## [0.1.2] - 2026-10-09
<!-- release: 0.1.2-rc2 -->

Release candidate v0.1.2-rc2.

Since v0.1.1. In plain words: the manual's What's new (manual/src/whats-new.md).

### Added

- VECTOR's emergency switch on the desktop: SUPER+CTRL+ESCAPE, a power mark on the bar (a red VECTOR OFF while he's off), and one switch in Settings › VECTOR; bromigos status reads it ([d7b3296](https://github.com/bromigos-org/bromigOS-archive/commit/d7b329696eb06217b24db045b6167dcfec04f47d))

### Core (the bromigos command)

- core: bromigos peripheral: optional peripheral modules, and setup's peripherals section ([0aef1cf](https://github.com/bromigos-org/bromigOS-archive/commit/0aef1cf6f445c322bac2d93741a541793d06f3e1))
- core: bromigos hw: the GPUs and the machine's kind from files, drivers from NVIDIA's and Mesa's own tables, hw setup ([bca146e](https://github.com/bromigos-org/bromigOS-archive/commit/bca146e4a6b26bf5f9242b0010a9a31eb1e76f90))
- core: accessibility: reduced motion and high contrast, set from bromigos accessibility and setup ([2f5ab91](https://github.com/bromigos-org/bromigOS-archive/commit/2f5ab91059297f3fd94a5b82d0fd741d2f6e5f05))
- core: idle and lock as data: idle.toml, `bromigos idle`, hypridle rendered and restarted ([8efee8e](https://github.com/bromigos-org/bromigOS-archive/commit/8efee8ec508e3f151f3756ec66ea322cc890d128))
- core: bromigos idle waits for the compositor to start the new hypridle (2 s at most) ([7241f66](https://github.com/bromigos-org/bromigOS-archive/commit/7241f66cd198fe92a2337bb75b70729ca7bafc51))
- core: bromigos idle start --detach: hypridle started in this session now, unless it runs ([8252b04](https://github.com/bromigos-org/bromigOS-archive/commit/8252b04645bd602398bb08a2e64d0b0338f6ae45))
- core: idle: a file written in the second before hypridle started isn't newer than it ([366645a](https://github.com/bromigos-org/bromigOS-archive/commit/366645a7d78e72b450a4f584e835bf1c7be60554))
- core: the theme switcher's previews drawn in the background after update, ext install/update and theme new ([3037244](https://github.com/bromigos-org/bromigOS-archive/commit/3037244cb5a70cc2b9c0a209ae249aa21597f09d))
- core: pacman's hooks hold Hyprland's auto-reload while a transaction replaces its config, then one verified reload ([d9d2763](https://github.com/bromigos-org/bromigOS-archive/commit/d9d2763b0513594b0dfb1854f50ff082e27e429a))
- core: bromigos peripheral follow ID vector|theme: what a module's lighting follows ([3d94809](https://github.com/bromigos-org/bromigOS-archive/commit/3d94809670ed86e334f32e01514ddd3638355d33))
- core, desktop, live, widgets, homelab: every bromigOS window in the app launcher, listed once in the menu ([35d2c6f](https://github.com/bromigos-org/bromigOS-archive/commit/35d2c6fe060a803495eaaa7e6e5cdc2e3447da79))
- target: check and probe say when a better model would fit the lab's GPUs (the lab model catalog) ([d109c2a](https://github.com/bromigos-org/bromigOS-archive/commit/d109c2a9cd4ace8ca0a3c3dfde284eab6a2f0266))
- core: rollback status says bromigos update makes its own snapshot pair (snap-pac's brackets any other pacman run) ([25f5e4b](https://github.com/bromigos-org/bromigOS-archive/commit/25f5e4bf8aea63383fb81ad4c62f57f218f92593))
- core: setup's module comment says where the monitors go (a bromigos.monitors block in the user's hyprland.lua, the primary in monitors.toml), not a monitors.lua, and lists the extensions section ([0884b52](https://github.com/bromigos-org/bromigOS-archive/commit/0884b523579e8dff6d020d16cea030028f92fc3d))
- core: bromigos whats-new, and the first update after a new release says so ([4e9d20c](https://github.com/bromigos-org/bromigOS-archive/commit/4e9d20c9ee5619aca4901a8fd52fc2842c8232ca))
- core: the AUR: paru at install and through a migration, AUR packages inside bromigos update's snapshot pair, bromigos aur, AUR-only NVIDIA drivers offered by hw setup ([9be878f](https://github.com/bromigos-org/bromigOS-archive/commit/9be878f5937be111f1d366fa5c4e36f39083cf6a))
- core: setup's Homelab page starts on Skip, so Enter goes on; the homelab.toml choice wants a path first ([ea7ccf4](https://github.com/bromigos-org/bromigOS-archive/commit/ea7ccf43af1272862515d9a1f3e4dc32a015f28f))
- install.sh: piped into bash, it asks on the terminal; with no terminal it needs --yes ([676456b](https://github.com/bromigos-org/bromigOS-archive/commit/676456bfd22e2b3e0677d09c291b05fd8e903ca3))
- core: the private overlay is decrypted at login, and again when it changes, as the docs said ([749e38d](https://github.com/bromigos-org/bromigOS-archive/commit/749e38d880d79fac4bb6ee299c4c9e6ee5645f67))
- core: bromigos update --rollback in a snapshot booted from the boot menu makes that snapshot the root ([17247b7](https://github.com/bromigos-org/bromigOS-archive/commit/17247b76c7961f995e6bd83e39dbd7cf2acfb832))
- core: an update from 0.1.1 renders the theme again: the templates default a11y, and an update that replaced bromigos hands the theme to the new one ([0a0791c](https://github.com/bromigos-org/bromigOS-archive/commit/0a0791cc7d15e1ac7288f122dbe8e185456f55aa))
- core: bromigos update holds back the live layer and VECTOR while a new NVIDIA driver or kernel waits for a restart, and ends by asking for one ([b62b79f](https://github.com/bromigos-org/bromigOS-archive/commit/b62b79ff0144b41d9e5948fd1b751c045d896595))

### Desktop

- desktop: peripheral modules: the Hyprland loader, the dial and lighting daemon ([d47c01b](https://github.com/bromigos-org/bromigOS-archive/commit/d47c01b62b2c1c094d255119911853d0974d01bb))
- desktop: laptops: the battery and power profile in the bar, profiles in the menu, tap to click and a workspace swipe ([5bafdf5](https://github.com/bromigos-org/bromigOS-archive/commit/5bafdf5c6babbb8cf1a64b12f9d63614a195de34))
- desktop: accessibility: window animations and borders follow it, the menu's rows, the panels ([aa7368e](https://github.com/bromigos-org/bromigOS-archive/commit/aa7368e6c04d14836c85c04fccd05ea9fde6df21))
- desktop: Settings (bromigos settings, SUPER+,): a page registry, Idle & lock complete ([946cbf9](https://github.com/bromigos-org/bromigOS-archive/commit/946cbf90cdd996b4e21ff6f2e039ceeef54f16cb))
- desktop: the bar's idle eye (stay awake's cup) and the Settings gear ([3db8aae](https://github.com/bromigos-org/bromigOS-archive/commit/3db8aae492cabf8ba0c41367e9ee0b24a1d492de))
- desktop: Settings: the accessibility page reads `bromigos accessibility`; the interaction check ([253a72f](https://github.com/bromigos-org/bromigOS-archive/commit/253a72fcc87043b4e0305e04a80a1a89b3f32884))
- desktop: one safe save for every hyprland.lua change, auto-reload off first ([e112bd4](https://github.com/bromigos-org/bromigOS-archive/commit/e112bd495ae2702a844d67f6ff1cb5af63d87057))
- desktop: bromigos keys, the shortcut picker: press the keys to rebind ([fab4711](https://github.com/bromigos-org/bromigOS-archive/commit/fab47112a2af962d51a48bde0fd107d4756e891c))
- desktop: Settings: Shortcuts opens the key picker (bromigos keys) and counts your own ([ca7b9c3](https://github.com/bromigos-org/bromigOS-archive/commit/ca7b9c3aac38f484a8f51deeb2ee39ac2833e4ff))
- desktop: SETUP › Config files: idle.toml, and an edited idle file is applied ([ae5ac6f](https://github.com/bromigos-org/bromigOS-archive/commit/ae5ac6f326e8a56bd8dec9b58b982df6b819511f))
- desktop: Settings: Idle & lock offers to start hypridle when it isn't running ([025dc5b](https://github.com/bromigos-org/bromigOS-archive/commit/025dc5bc844365690e51970a181abefbfbc7d69b))
- desktop: bromigos keys: undo, list --all, --json outcomes; the capture window opaque ([22f17d2](https://github.com/bromigos-org/bromigOS-archive/commit/22f17d2a5e199f9d8e01826fe3daa8e526c2f546))
- desktop: Settings: the Shortcuts page, complete: every key with Change…, yours, reset ([50379e4](https://github.com/bromigos-org/bromigOS-archive/commit/50379e44f5309cd795f647d0bab663e1e42b8ce2))
- desktop: bromigos keys and peripheral modules: K.exclude's keys spelled as the module does ([cba39c1](https://github.com/bromigos-org/bromigOS-archive/commit/cba39c181ecb2652ca558d34e06e35077d600fe0))
- desktop: Settings: Accessibility, complete: motion, a high-contrast switch, the theme measured ([37e6773](https://github.com/bromigos-org/bromigOS-archive/commit/37e6773e8923032e38b5fa26d7ec8f2659fca7f5))
- desktop: a safe save writes through a symlink: a hyprland.lua kept in dotfiles stays linked ([61e8307](https://github.com/bromigos-org/bromigOS-archive/commit/61e8307a470acf6308fd80cfc836aa1af4ff2d58))
- desktop: Settings: a page's icon may name several, the first the icon theme has ([8b9225c](https://github.com/bromigos-org/bromigOS-archive/commit/8b9225c349529ccade6ddd86187b129693f3ccd7))
- peripherals: the lighting can follow the theme (rgb_follow = "theme"): its primary, changing with the theme ([d3a5e56](https://github.com/bromigos-org/bromigOS-archive/commit/d3a5e5695a1e4b42043190215a014654be5b786e))
- desktop: the theme switcher shows each theme as the desktop wearing it, sized to the monitor ([5b82e7e](https://github.com/bromigos-org/bromigOS-archive/commit/5b82e7e03998a9eeadfab8d976316eccc95d7561))
- desktop: the switcher's tests build without Pillow; the Wick's card says DEN ([f873ac1](https://github.com/bromigos-org/bromigOS-archive/commit/f873ac1f08b32e84acf36e6c1132f9fdfc897ab9))
- desktop: bromigos-wallpaper restarts only its own session's swaybg ([9da347e](https://github.com/bromigos-org/bromigOS-archive/commit/9da347e4ca485af2ce4414b7b681371ba9cc9301))
- desktop: theme previews are screenshots of the real desktop: Hyprland nested in a headless kwin ([ad5bf1e](https://github.com/bromigos-org/bromigOS-archive/commit/ad5bf1e897ac3d602aa66cae8a883d48cc8549d3))
- desktop: Settings › Theme: wear a theme from its preview, what moves in its world, the options around it, more themes ([69a57d1](https://github.com/bromigos-org/bromigOS-archive/commit/69a57d17d37b89240c459af6d78d4576f0857f61))
- desktop: Settings: groups, a search across every setting, one page layout, Advanced lines, Sound ([42db24c](https://github.com/bromigos-org/bromigOS-archive/commit/42db24c8044f8a9a041906e676f30e7553e7b2ba))
- desktop: theme previews: the nested Hyprland writes no log (its runtime directory is in /tmp, often small) ([e8070a4](https://github.com/bromigos-org/bromigOS-archive/commit/e8070a489e3e4c7865ec38a6eb68e9e485a8b007))
- desktop: Settings › Theme in the new Settings shell: its header, the search's entries, keyed rows, Advanced lines ([9d92d97](https://github.com/bromigos-org/bromigOS-archive/commit/9d92d973ee91e609aa126bb9f32563092f4173b9))
- desktop: Settings › Lab in the new shell: the lab group, its explanation, the manual's page, and the search's entries (status, models, jobs, doctor, targets, connect) ([64dcd26](https://github.com/bromigos-org/bromigOS-archive/commit/64dcd26dc41590ec82c245feda25f33e5b07a8c2))
- desktop: Settings: Idle & lock, Shortcuts and Accessibility in the new layout: their settings searchable, Advanced lines, Reset to defaults ([f02cc01](https://github.com/bromigos-org/bromigOS-archive/commit/f02cc01d0634fb41c74d0dbe39bfd933795201f3))
- desktop: Settings: the keyboard, end to end: typing anywhere searches, Enter opens a result on its row, Esc, Ctrl+F, Ctrl+1…6, Ctrl+PgUp/PgDn ([e44b322](https://github.com/bromigos-org/bromigOS-archive/commit/e44b3225d5bedc920292baa75eb9df1fa435ef64))
- desktop: Settings › Displays, Network and Bluetooth (bromigos display, net, bluetooth) ([fd3178c](https://github.com/bromigos-org/bromigOS-archive/commit/fd3178c193ca42939aafc8532a820bb9963f1443))
- desktop: Settings › Power, Keyboard & input, Date & time, Notifications (bromigos power, clock, notifications; setup input) ([44fe33d](https://github.com/bromigos-org/bromigOS-archive/commit/44fe33d0a2cf4724297555f1b04e532f5a26f363))
- desktop: Settings › VECTOR, Creation targets, Account, About, Updates & recovery (bromigos memory, about, avatar) ([c76b084](https://github.com/bromigos-org/bromigOS-archive/commit/c76b084ad9487f08404bd94573e331d492297013))
- desktop: Settings › Default apps, Startup, Widgets, Live layer & holograms, Peripherals, Extensions (bromigos defaults, startup, panels) ([b970a8e](https://github.com/bromigos-org/bromigOS-archive/commit/b970a8ef3b8cd72722c8617b753bf07ab6ad745c))
- desktop: Settings: combo rows show their escaped text, group descriptions escaped, Advanced lines plain; renders as a laptop; the Displays end-to-end steps ([611c77c](https://github.com/bromigos-org/bromigOS-archive/commit/611c77c586056d5be24a9051ad06985e177e6c5f))
- desktop: the extensions window and Settings › Extensions share one list (bromigos_extlist); Settings' terminals are bromigos terminal ([dab836d](https://github.com/bromigos-org/bromigOS-archive/commit/dab836d590780764e8c5eedefb168ed27cf8b72f))
- desktop: Settings end to end in a nested Hyprland, 37/37: Displays applied, left to revert by itself, kept, reset; Keyboard & input live; a combo row no longer locks up ([2cd74b3](https://github.com/bromigos-org/bromigOS-archive/commit/2cd74b3fa4c1897fbb73e526719fc31827f8c24d))
- desktop: Settings › Lab without bromigos-homelab: a row for each thing the search finds (greyed, saying why), Connect your lab, where AI runs ([f48bc0b](https://github.com/bromigos-org/bromigOS-archive/commit/f48bc0ba6b24b495bd03fbe7c1407c3e53514197))
- desktop: Settings › Lab › Models: each capability's switch says what it does for that capability (the plan's switch, Always on); the audit with the recorded lab: 0 unhinted (13 before) ([8b9936b](https://github.com/bromigos-org/bromigOS-archive/commit/8b9936b73094ed61d6e269990b6d14ee7fa372e9))
- desktop: Settings › Theme's grid reflows: three cards to a line, two, then one, so it fits a narrow window ([0221fe8](https://github.com/bromigos-org/bromigOS-archive/commit/0221fe84e538bb578b2378e5317276ef8ab4f00b))
- desktop: the theme switcher's previews show the den in a colour theme's colours, and a new live layer redraws them ([38ce275](https://github.com/bromigos-org/bromigOS-archive/commit/38ce27518e6f705e415a45ee1501cf451bb7810f))
- desktop: a colour theme's card says the den behind it takes the theme's colours (since 75a1285), not that it keeps the Wick's green ([95ae68e](https://github.com/bromigos-org/bromigOS-archive/commit/95ae68e187f5e734dcdcac21aac79aedb29dac53))
- settings/sddm: theme.conf says bromigos-settings' PKGBUILD puts the Wick's pictures in assets/, not a build.py that doesn't exist ([a663022](https://github.com/bromigos-org/bromigOS-archive/commit/a663022c6b0a51d9bb743f58f1f89c7855cd47be))
- desktop: the rofi menus' titles read whole again: one quoted string per line in the title theme (rofi read the title as BROMIGOS"; … font: "Geist Mono Bold 12) ([e1ea131](https://github.com/bromigos-org/bromigOS-archive/commit/e1ea13177be058a438e8bdd0460e27f6a779e988))
- desktop, widgets: theme previews draw any panels where you put them and the terminal you want (--panels, --scene), every reading a demo one: the bar's built-in modules showed this machine's (a fixed demo text now, thresholds out of reach), a made-up player fills its middle, WEATHER, WORKBENCH, CONNECTIONS and LAB (a made-up lab, widgets/demo_lab.py, which the decks see too) have demo data; bromigos menu --filter TEXT ([dd4c4c6](https://github.com/bromigos-org/bromigOS-archive/commit/dd4c4c636ff005c3c81548fba4640528a2caad16))
- desktop: the rofi menus' titles sit above the search box again: the title expands (rofi's default for a textbox); a fixed-height one made rofi 1.7.9 and 2.0.0 skip the header's layout and draw the title under the input, in the menu, keys, extensions, the setup tools, the power menu and the quick note; the menu's picture rendered again ([4a1e203](https://github.com/bromigos-org/bromigOS-archive/commit/4a1e20327e795f909594d5f63f368885813f3d39))
- desktop: Alt+Esc suspends with plain systemctl suspend, which logind allows the active session; sudo failed without a passwordless rule ([58b32b5](https://github.com/bromigos-org/bromigOS-archive/commit/58b32b50f8a19545161877cc57b7673d32fbed56))
- desktop: searching Settings for "dark" finds Themes, not Bluetooth's Look for devices ([558159e](https://github.com/bromigos-org/bromigOS-archive/commit/558159ea522487f31731782c9bbd79c00b04cb88))
- desktop: with mod = "SUPER", no key does two things: bromigOS's own Super key a window key would share moves to Alt ([525a107](https://github.com/bromigos-org/bromigOS-archive/commit/525a10761453e1ec3c9e155062f57ffe0bdbbc61))
- desktop, packaging: Settings' F1 and About open the manual installed here, else <base>/bromigos/manual/, where it's published ([64a3bf2](https://github.com/bromigos-org/bromigOS-archive/commit/64a3bf2ef16ea705065e05df914e95e7ca02f8ab))
- desktop: the mod = SUPER test checks the live layer's keys, not VECTOR's, which only exist where he's installed ([f4fb7fe](https://github.com/bromigos-org/bromigOS-archive/commit/f4fb7fea5ecba6da6dce0277e00e9b9d89429f97))
- desktop, homelab: bromigos memory clears VECTOR's notes in Gnosis too, archived first; undo files them again ([fd5997f](https://github.com/bromigos-org/bromigOS-archive/commit/fd5997f2f9be2c27cdecc362bfd7f31f9eb5b5bd))
- desktop: the theme previews draw nothing while NVIDIA's driver halves differ, and a run gives up after one GPU failure ([9f9ff3c](https://github.com/bromigos-org/bromigOS-archive/commit/9f9ff3c4b793d746ab11e85a67718e2c2ea69627))

### Live layer

- live: reduced motion: calm and still modes for the den, the worlds, the overlays and decks ([3705ee5](https://github.com/bromigos-org/bromigOS-archive/commit/3705ee5ee0e03b328186007cc1886bc9151d75fc))
- live: reduced motion: the intercept's crossfade from the frozen screen runs 0.9 s ([6a1feba](https://github.com/bromigos-org/bromigOS-archive/commit/6a1feba19acb2df8361892bee8f2f3458a640684))
- live: a mouse movement ends the screensaver again (an overlay's motion handler was shadowed) ([fba5688](https://github.com/bromigos-org/bromigOS-archive/commit/fba5688a7889b615d1b6cc314a5aabec5389e6af))
- live: the underlay loads at any screen width (a pixbuf's rows at their own stride; alpha over black) ([321b883](https://github.com/bromigos-org/bromigOS-archive/commit/321b883619b7cccbdfd2aa6835b8ce947f9fe072))
- live: one daemon per user, and stop/restart stop exactly it (by PID and start time, never pkill -f) ([d9872d5](https://github.com/bromigos-org/bromigOS-archive/commit/d9872d52bbb4f5e3ec63dd0292a9759b837858ca))
- live, desktop, homelab: nothing private ships: the lab's name, its nodes, the decks and the fills feed come from config and plugins ([cda67e8](https://github.com/bromigos-org/bromigOS-archive/commit/cda67e8fd93af2ceb214ea7992b06b2078028202))
- live: a zombie isn't a running daemon (stop and the tests, where PID 1 doesn't reap) ([2689bc2](https://github.com/bromigos-org/bromigOS-archive/commit/2689bc2751684c83ecbb710c39dbf6f3ff10ca84))
- live, desktop: the den follows a colour theme: its painted plate, its shaders' own greens, the burn-in, the wallpaper and the lock screen ([75a1285](https://github.com/bromigos-org/bromigOS-archive/commit/75a1285478632f56e5f552d43d65231e6d83f48f))
- live, homelab: the constellation's positions as a list of {node, at}, so an overlay encrypts every host name ([86cd139](https://github.com/bromigos-org/bromigOS-archive/commit/86cd139ea55d60394396acfb1d5c8afddb4b467b))
- live: the Drift map's lore catalog ships with the package and is the default (bromigos.org's public lore export); [driftmap] catalog still names another ([0eb9ddc](https://github.com/bromigos-org/bromigOS-archive/commit/0eb9ddcd295243506fa4c39b0dc8ff5638145834))
- live: the quick-launch ring's NOTES opens the FIELD NOTES panel, ready to type in, not nvim ~/notes ([1e3d023](https://github.com/bromigos-org/bromigOS-archive/commit/1e3d023c25bd1047b49363d26379d1ec29c072e7))
- live: on a software renderer (llvmpipe, softpipe, swrast) the background holds a still frame, decks at 10 fps, and says so once ([b9dec13](https://github.com/bromigos-org/bromigOS-archive/commit/b9dec13689ea2834b77a22e4ca24e09ddf877eda))

### Boot and the ISO

- iso: the installer adds this machine's hardware packages and services from the medium ([1b80a06](https://github.com/bromigos-org/bromigOS-archive/commit/1b80a06b4c7c8a5b7d760e4465a1088e1b7b7a62))
- boot menus: "tuning into the relay": a GRUB theme for installed systems, themed ISO menus ([e92a2c8](https://github.com/bromigos-org/bromigOS-archive/commit/e92a2c82d9c9052a0f767f52750d43d4082def8e))
- settings/grub: the boot theme's helper ignores the firmware's loader name in an install chroot (the live medium's, not the new system's) ([e475829](https://github.com/bromigos-org/bromigOS-archive/commit/e4758297d6f56d6d3f323955e7e3a77ea1a34f30))
- settings/grub: the boot menu's icons get a thin edge in the background colour, so the selected entry's reads on the phosphor bar ([8aec889](https://github.com/bromigos-org/bromigOS-archive/commit/8aec889b5277d831b53ce0eb74521bd96fe1306f))
- iso: the BIOS menu's font goes in the profile's grub/ (mkarchiso copies only syslinux's .cfg and splash); docs: the harness's boot-menu commands ([a03cc70](https://github.com/bromigos-org/bromigOS-archive/commit/a03cc70dec18ddd32fc26cc3289bf8f072a1fb8e))
- iso: Memtest86+ on UEFI again (memtest86+-efi 8 ships memtest86x64.efi, which mkarchiso 91 doesn't copy: the build puts it in grub/); iso/test.sh menu live presses no key ([d52bb6d](https://github.com/bromigos-org/bromigOS-archive/commit/d52bb6d8fa5ed4b4e042cb9ca900b675b4f9c4f4))
- settings/grub: the boot theme's helper syncs grub.cfg and /boot before it returns (a power cut leaves the old or the new); iso/test.sh boots the medium first by bootindex (after an install the firmware's own order puts the disk first) ([f8fdb3e](https://github.com/bromigos-org/bromigOS-archive/commit/f8fdb3eca0881af2ab2b46457f94f8df9f799ddd))
- boot menus: the medium's Boot from disk chainloads the disk's boot loader (else the firmware's next device); a snapshot's kernels say their microcode; docs: GRUB 2.16's firmware entries, the sync ([36933cf](https://github.com/bromigos-org/bromigOS-archive/commit/36933cf380e31e9e6425ecb6a834ef82f8c64f8c))
- settings/grub: on a BIOS the boot theme asks GRUB for 1024x768, then 800x600, before VBE's auto (640x480 without the screen's EDID); an older block is brought up to date by apply and the pacman hook ([bf84135](https://github.com/bromigos-org/bromigOS-archive/commit/bf841355803f97f45c710aad7fe6086f86307400))
- iso: Boot from disk connects the firmware's other disks (connectefi) and chainloads the first boot loader on another disk than the medium, archinstall's removable path too; the test wants the installed theme's bar ([3a8a572](https://github.com/bromigos-org/bromigOS-archive/commit/3a8a572416b553c9e0fb18158c6c0dbc69409b7e))
- iso: Boot from disk on UEFI reads the installed system's grub.cfg (a chainloaded GRUB lost its prefix: grub rescue), then other loaders, then the firmware ([6cf6288](https://github.com/bromigos-org/bromigOS-archive/commit/6cf62887f638daad4dddc45ab90664f69fa76abf))
- iso: the UEFI menu's screen-reader entry is back (the Boot from disk rework took it out) ([58f61dd](https://github.com/bromigos-org/bromigOS-archive/commit/58f61dddf5f3df954e27e51301608e811e20a96a))
- boot menu: the installed system's entries read "bromigOS Linux": GRUB_DISTRIBUTOR in the boot theme's block (10_linux names and classes the entries by it); off takes the block out, so Arch's own name is back, and /etc/os-release stays Arch Linux's; bromigos-settings' pacman hook (refresh) brings an older block up to date whichever theme is in /boot, and a migration retries it where the hook couldn't; status --json says block_outdated; the preview's installed menu named the same ([68ab3b0](https://github.com/bromigos-org/bromigOS-archive/commit/68ab3b06a24fe11a9fbe413f13325549456ccec7))
- boot menu: the VM runs for the entries' names (an installed machine updated, its pacman hook rewriting the block; a fresh install from a test medium, encrypted: live 16/16, installed 76/76, update and rollback 7/7; off and on again after reboots); the docs' picture of the installed menu taken again in Mire; no fallback initramfs on today's installs (one entry per kernel), and grub-install names its EFI folder bromigOS ([4380484](https://github.com/bromigos-org/bromigOS-archive/commit/4380484c1530aa907aec7011bf6292dd744a3451))
- iso: test.sh takes BROMIGOS_ISOTEST_MEM, the VM's memory in MiB (6144 by default) ([b59b6a8](https://github.com/bromigos-org/bromigOS-archive/commit/b59b6a89cd0570d64ae8e810c2edfb4d2c4ebdd2))

### Widgets

- widgets: SHORTCUTS calls Alt+Left and Alt+Right "Move split left" and "Move split right", not Narrower and Wider ([716ca5b](https://github.com/bromigos-org/bromigOS-archive/commit/716ca5b2046939436853119d5496e72f80f13d71))

### Themes and art

- themes: hologram models for the eight worlds, and the shared craft and relay ([50f6ee0](https://github.com/bromigos-org/bromigOS-archive/commit/50f6ee03e75d236010d7d5697ef3eb98c50dbd8a))
- art: create.toml may list several workflows per provider, tried in order ([9e51beb](https://github.com/bromigos-org/bromigOS-archive/commit/9e51beb235858c9a985647b70ed45e662444fcc0))
- art: video.loop on a ComfyUI: Wan 2.2 (TI2V-5B on the lab, I2V-A14B ready), model-agnostic ([ca5f11f](https://github.com/bromigos-org/bromigOS-archive/commit/ca5f11fb0e99630c1a76cf86633d3d37f349550d))
- art: a workflow the ComfyUI lacks files or nodes for, or whose card is too small, is skipped for the next ([e80771f](https://github.com/bromigos-org/bromigOS-archive/commit/e80771f4c5245054354e1791e59fc460306570b9))
- theme: the app launcher's icons: a bold glyph in the burn-in's ring, drawn in code per size ([79fd73f](https://github.com/bromigos-org/bromigOS-archive/commit/79fd73f7824be4c5a7cc0b3339f2c242993e3ab1))
- art, lab: cutouts on Lucida, 3D on Pixal3D (stood upright), and upscales of images and clips on SeedVR2 7B ([947713c](https://github.com/bromigos-org/bromigOS-archive/commit/947713c652b529f7e77e45185212a2631b8ab640))
- theme: mire: the Sleeper's eight clips sharpened with SeedVR2 7B on the lab ([7b111ce](https://github.com/bromigos-org/bromigOS-archive/commit/7b111ce751d089c6b61d55bb61e88f47684e0d58))
- art: a clip upscale asks an idle ComfyUI to unload its models first, so SeedVR2's temporal chunks get the whole free VRAM ([9ed6e44](https://github.com/bromigos-org/bromigOS-archive/commit/9ed6e44fee1299c5b717f3e72fd18f89deccdd23))
- themes, homelab: the hologram previews rendered again with demo readings: no lab name, no likeness ([843a992](https://github.com/bromigos-org/bromigOS-archive/commit/843a9921d78c2fd5328cd411726e5db7a9e928df))

### Homelab

- homelab: the lab console's seams: status cards, doctor checks, job kinds, the job queue ([823f562](https://github.com/bromigos-org/bromigOS-archive/commit/823f5629d891578e8d8c00d90cfb1bcda7c7df79))
- homelab: capabilities for the lab's own services (gpus, logs, routes, certs, ddns, network, storage, apps, games, library, runners, packages, backups, ocr) ([105fffe](https://github.com/bromigos-org/bromigOS-archive/commit/105fffe0b61835a2dcbd514096a1d9cbe889633b))
- homelab: the lab console's dashboard and its tests: status, doctor and the queue against a recorded lab ([3fe0e99](https://github.com/bromigos-org/bromigOS-archive/commit/3fe0e99064454eb6bba526473e847ad55d6dbe28))
- homelab: the lab dashboard's pilot tests and snapshot (Textual 8.2.8) ([091a867](https://github.com/bromigos-org/bromigOS-archive/commit/091a86785bdfbae0c616f1c4df45a9428518b89c))
- homelab: adapters for the rest of a lab: GPUs, logs, the edge, storage, games, the media library, AI services, CI, packages, backups ([5aee3ae](https://github.com/bromigos-org/bromigOS-archive/commit/5aee3ae2ae6f0206ae045c3c1d42c91dc08e688d))
- homelab: tests for the lab adapters and their doctor checks, against recorded (sanitised) answers ([6e49feb](https://github.com/bromigos-org/bromigOS-archive/commit/6e49febc787310d26ede1e8f4a747e3d0e448073))
- homelab: bromigos setup homelab detects the lab's services from its metrics and its cluster ([a7113a1](https://github.com/bromigos-org/bromigOS-archive/commit/a7113a1f6ce21de6ca92db60019ce3bc3b560f8c))
- homelab: the redis adapter counts a command's bytes, not its characters (RESP) ([3bccf53](https://github.com/bromigos-org/bromigOS-archive/commit/3bccf533d5d6f0943b61f064521e9c2c1ac397ab))
- homelab: a test: a kubeconfig that may not proxy to services leaves the source unreachable, saying why ([714385c](https://github.com/bromigos-org/bromigOS-archive/commit/714385c69481c70261d009cf197b1ad6ab122a38))
- homelab: bromigos lab: the console's command, its job queue's service, the Lab deck (SUPER+SHIFT+H), Settings › Lab ([6f0b7e4](https://github.com/bromigos-org/bromigOS-archive/commit/6f0b7e46659abf25f539c0b4012f4cbc4e94a596))
- video loops on the lab: the lab's video kind, the first run's targets, the docs ([2f84cda](https://github.com/bromigos-org/bromigOS-archive/commit/2f84cdaefe6f02e9fcb2f6299eea07ec9518dd5f))
- homelab: the Lab deck keeps its labels in the panel (a narrower orbit, shorter holds on the left) and shows a drilled card's values whole ([2e7605e](https://github.com/bromigos-org/bromigOS-archive/commit/2e7605ee79dd1ee260fb0a2a2b0e9c11036b86cc))
- homelab: the lab model catalog: the best open models per capability and GPU, a planner, upgrades, a weekly refresh ([e7b7d74](https://github.com/bromigos-org/bromigOS-archive/commit/e7b7d7482f52bc8b9289f4648218df8927fe0ebe))
- lab catalog: three licences corrected (GLM-Image, GLM-OCR: MIT; Granite Speech 5.0: Apache 2.0), and a quieter refresh ([e4f2714](https://github.com/bromigos-org/bromigOS-archive/commit/e4f2714e05ef98760a41d6f0a2d14fcdc0730971))
- lab catalog: where Actions can't open pull requests, the weekly refresh commits its tested change and files the report as an issue ([e9d36ff](https://github.com/bromigos-org/bromigOS-archive/commit/e9d36ffecf6ea24f3626583b288616fb0974fc26))
- lab catalog: weekly refresh 2026-10-09 (metadata and pending review entries) ([283c68b](https://github.com/bromigos-org/bromigOS-archive/commit/283c68b5dad0b86b7bd28dea93cacf653e8fcc2b))
- lab catalog: LLM serving figures from published benchmarks on the same hardware; agents' prompts and the server's sequence cap count; the licence region from the time zone ([0b52495](https://github.com/bromigos-org/bromigOS-archive/commit/0b52495a7ed07689547406c2afe8532f2f52fcbf))
- lab catalog: a family's newer member counts only under a pipeline the catalog covers; the three FLUX.3 action robot policies dismissed ([a75ef18](https://github.com/bromigos-org/bromigOS-archive/commit/a75ef185c55854aef84fcecf78c205ef42a934c8))
- homelab: the LAB panel finds the object store's NAS share in the snapshot (the share its claims are bound on), named as the lab names it, or "on the NAS"; no share name in the code, and the private-names check scans homelab/widgets for k8s_ share names ([ef32f7a](https://github.com/bromigos-org/bromigOS-archive/commit/ef32f7a2785af46563428cc2731db68b916fd9d0))
- lab doctor: a homelab target that fails behind the one a service uses is no finding ([b11d6a4](https://github.com/bromigos-org/bromigOS-archive/commit/b11d6a4c9a0ad0d7488f3e6176b0b5f2653ae9f5))
- homelab: bromigos lab moves with the arrows and Vim's keys: j/k between cards and rows, h/l between the STATUS panes, g/G, Ctrl+D/U, ] [ (L H) through the tabs; a tab's list takes the keyboard when it opens ([1bf4c1d](https://github.com/bromigos-org/bromigOS-archive/commit/1bf4c1dd4c05334d23c644af22ad59a2055b3f29))
- homelab: a heavy lab job short of VRAM asks an idle ComfyUI to unload, instead of waiting five minutes for the sidecar ([2d26919](https://github.com/bromigos-org/bromigOS-archive/commit/2d26919b23502a15360801decf217d556a4afdb8))
- homelab: the Proxmox fixture's VMs have made-up names ([71e5a0d](https://github.com/bromigos-org/bromigOS-archive/commit/71e5a0da43785244fdc0738749ef7aba94b164bb))

### Tests and tools

- test/vm: a second VM beside the first, and a faked notebook chassis for the hardware test ([63772cc](https://github.com/bromigos-org/bromigOS-archive/commit/63772cc772e7652d052a11220f6c7ed2baf6a395))
- iso/test.sh: the installed system's channel is checked against the medium's ([1cfa85d](https://github.com/bromigos-org/bromigOS-archive/commit/1cfa85dd64aadf1340e8f0e6ba75af63649f7e59))
- iso/test/live-checks.sh: /boot's mode is reported, not required ([4156364](https://github.com/bromigos-org/bromigOS-archive/commit/415636467e6f9dd182924126a30f3523d24ec2ad))
- desktop/tests: the shortcut picker: unit tests, offscreen renders, a nested end to end ([e85110e](https://github.com/bromigos-org/bromigOS-archive/commit/e85110e6342735bff21429fdab4683a93750a232))
- iso/test.sh: a run beside another (its own port and display), and extra QEMU arguments for a faked laptop ([a089a25](https://github.com/bromigos-org/bromigOS-archive/commit/a089a256bf073d412ab559120df45e2a2e120e8f))
- desktop/tests: the Settings registry's tests skip without GTK 4's bindings (the package builder) ([976d82b](https://github.com/bromigos-org/bromigOS-archive/commit/976d82bb408c7e0c37137b5e0e669b71d45e8166))
- desktop/tests: bromigos keys' undo, --json and list --all; the Settings page, drawn and driven ([98501ec](https://github.com/bromigos-org/bromigOS-archive/commit/98501ec6e99c89e9432a758812527fe517fedaef))
- desktop/tests: bromigos keys' tests pass on the package builder (no VECTOR, no xkbcommon) ([6e45d0e](https://github.com/bromigos-org/bromigOS-archive/commit/6e45d0ef4e2b8be20c7a431f438e8ed02b6c366c))
- test/vm: the fresh machine checks bromigos keys; docs: peripheral modules and the picker ([5f8da6a](https://github.com/bromigos-org/bromigOS-archive/commit/5f8da6a36ac7061c7b636353834e972c02c89f14))
- desktop/tests: bromigos keys' command tests verify with a stand-in Hyprland ([c69aa39](https://github.com/bromigos-org/bromigOS-archive/commit/c69aa39c4b85cc941ca9abb6e6d047d2368078c2))
- test/vm: idle and lock end to end (idle-e2e.sh); docs: idle: the VM run, 30/30 ([844a69e](https://github.com/bromigos-org/bromigOS-archive/commit/844a69e7a705904150a9cec5d0bc1bbeae059176))
- tools/settings/render.sh: the throwaway home gets a new user's hyprland.lua (the Shortcuts page reads it) ([a45c8da](https://github.com/bromigos-org/bromigOS-archive/commit/a45c8dacf172a949f7ee9260771f38444271d5b7))
- test/vm: the keys check reads bromigos keys' own key order (SUPER ALT CTRL SHIFT), and resets even when a step fails ([bd9c5c6](https://github.com/bromigos-org/bromigOS-archive/commit/bd9c5c676341ab509e5a7118783905176e6b678a))
- iso/test.sh: the boot menus: menu ENTRY (the medium's menu, then a channel booted and checked), grub NAME (the installed system's GRUB saved), up ([dfb0bc9](https://github.com/bromigos-org/bromigOS-archive/commit/dfb0bc944743a116f70eeb22c54d03a2be8f9ee7))
- desktop/tests: the stand-in bromigos pretends one built-in per file (fixtures/builtins/), else routes like the real one; renders fall through to the real CLI ([3599558](https://github.com/bromigos-org/bromigOS-archive/commit/35995588327a72eb4e2c5b22069d0c9ef589b04e))
- desktop/tests: Settings end to end in a nested Hyprland with a PipeWire nobody hears: Sound, 11/11 ([f7d5616](https://github.com/bromigos-org/bromigOS-archive/commit/f7d5616c5a159c6c55ff55827c64fff9d4eee4b6))
- desktop/tests: the network stand-in's addresses from the documentation ranges (RFC 5737) ([c62542b](https://github.com/bromigos-org/bromigOS-archive/commit/c62542b66f351cb4961dee87c21942e7313b4951))
- test/vm: Settings against the real services in the fresh-machine VM, 22/22; Breeze's names for five pages' icons ([d5661fc](https://github.com/bromigos-org/bromigOS-archive/commit/d5661fcabad732b7eead95b25bb073c5d27fca97))
- tools/screenshots: the loop's frames complete: Hyprland's animations off for the capture, and each picture taken again until it shows its frame whole ([795a11b](https://github.com/bromigos-org/bromigOS-archive/commit/795a11b56a2fa000ebfe4e8b90b4d56219b2f9b8))

### Docs

- docs: peripheral modules: the doc, the manual's page, the commands and their JSON ([f86bcd0](https://github.com/bromigos-org/bromigOS-archive/commit/f86bcd068de4111018d18f2baaebcab79d2eaf58))
- docs: PLAN: the peripheral modules batch is done ([156a489](https://github.com/bromigos-org/bromigOS-archive/commit/156a489eae3614e3550673d03de305fa78f74c5b))
- docs: ASSETS: the operator's decisions: lab-made holograms on the site, no AI captions ([166f843](https://github.com/bromigos-org/bromigOS-archive/commit/166f843be8c7e1ea0a0e1ded5f9be3e7f16d6e44))
- docs: the README and desktop/README name the peripheral modules ([e91238b](https://github.com/bromigos-org/bromigOS-archive/commit/e91238b0295aa4afaee8946354e9c21d72c52953))
- docs: ASSETS: the Seedream and Seedance assets are cleared by the operator's decision ([64a5d10](https://github.com/bromigos-org/bromigOS-archive/commit/64a5d1098c47092524a32ac319a3ce62bdef5197))
- docs: hardware: bromigos hw, the GPU matrix, laptops, the touchpad, what's proven; PLAN: the hardware batch is done ([6a8b664](https://github.com/bromigos-org/bromigOS-archive/commit/6a8b664f7169c6fac5227cb26bf343f7bae7eba6))
- docs: accessibility: the doc, the manual's page, the commands and their JSON; PLAN: the batch is done ([c487c0a](https://github.com/bromigos-org/bromigOS-archive/commit/c487c0a8a6d4001299a86c01368291ae9ababbeb))
- docs: ASSETS: every bromigOS and brand asset is cleared for shipping and the site (operator) ([99c638e](https://github.com/bromigos-org/bromigOS-archive/commit/99c638eec8320e5ab9ad91fc14fd35fa2efa9c46))
- docs: the v0.1.1 candidate's runs: the ISO (UEFI encrypted, BIOS plain) and the fresh machine ([ee5e5cb](https://github.com/bromigos-org/bromigOS-archive/commit/ee5e5cb56930f634f70cdd662a1dd86480f3e4ba))
- docs: install: the stable v0.1.1 fresh-machine run (install.sh's defaults, 40/40) ([81493c9](https://github.com/bromigos-org/bromigOS-archive/commit/81493c9aa986da7aaf8670e26428d1b72cdf7bbb))
- docs: idle and lock (docs/idle.md), Settings and its page registry (docs/settings.md), the manual's pages ([a9fadfa](https://github.com/bromigos-org/bromigOS-archive/commit/a9fadfa5b887b252f1f38f7c0c010c5415455cfe))
- docs: settings: the interaction check ([0c49e0e](https://github.com/bromigos-org/bromigOS-archive/commit/0c49e0e1f78ee0b981f8ff279382ea601a781d02))
- docs: the shortcut picker: desktop.md's Shortcuts, the manual's own keys, the menu, web apps ([0e1e4d5](https://github.com/bromigos-org/bromigOS-archive/commit/0e1e4d55092df34bb3424c754ed6f9beff2e5dfd))
- docs: README: the hardware batch (bromigos hw), and phase 4's batches done ([c6ace1b](https://github.com/bromigos-org/bromigOS-archive/commit/c6ace1b5ef4147f9a8ed6caacce78597bfdcb04c))
- docs: hardware: the ISO run (a faked notebook installed from a medium built with it) ([314e24b](https://github.com/bromigos-org/bromigOS-archive/commit/314e24b34d435edf86330b4b7f254a04f037ce99))
- docs: Settings' Shortcuts page, bromigos keys undo, list --all and --json ([965ca5a](https://github.com/bromigos-org/bromigOS-archive/commit/965ca5af62e9e33c325dba756bc27b005960c765))
- (withheld by the privacy check) ([b35d3a9](https://github.com/bromigos-org/bromigOS-archive/commit/b35d3a99672c809d73d870335c2e37f4171550e3))
- docs: the README opens on the Wick, and lists Settings, idle and lock, the shortcut picker and the work in progress ([6d19d3c](https://github.com/bromigos-org/bromigOS-archive/commit/6d19d3cbb2067762d01e3efda965e7b85b6a1339))
- docs: accessibility: VECTOR's holograms and construct follow the motion setting (vector ee0c832, bromigos-vector r32) ([7ebd3e0](https://github.com/bromigos-org/bromigOS-archive/commit/7ebd3e021ae1e50128b57092ec50be4ff2137912))
- docs: homelab: the lab's own services: their capabilities, the adapters (what each reads and what it powers), the doctor's checks, the ocr job; the manual's table ([33a5bb5](https://github.com/bromigos-org/bromigOS-archive/commit/33a5bb53e68d9b6316c4595afb70a588cbfd3133))
- docs: the lab console (docs/lab.md, the manual's chapter), provisioning's design (docs/lab-provision.md), the plan's phases 2 and 3 ([5ca9cf4](https://github.com/bromigos-org/bromigOS-archive/commit/5ca9cf4d37db825ff2fccfd9500ee308b6daa8c2))
- docs: lab: video runs on the lab now (Wan 2.2): the video kind, creature-loop, the shared jobs.toml ([2abd6e7](https://github.com/bromigos-org/bromigOS-archive/commit/2abd6e76aefe993b29800cc22454aee5b3ae0aba))
- docs: VECTOR's gallery shows the worlds' holograms, each on its world's shelf in its colours ([33e560b](https://github.com/bromigos-org/bromigOS-archive/commit/33e560b4ea6adecadc772f3fa459b95c88c95d0e))
- docs: the app launcher: every bromigOS window in it, what each entry runs, the menu listing each once, the tests ([d29bf71](https://github.com/bromigos-org/bromigOS-archive/commit/d29bf71db7095a31c9cfe5604b705a26325c4fba))
- docs: settings: the Lab page sits first in the Lab group ([d0819bd](https://github.com/bromigos-org/bromigOS-archive/commit/d0819bde35f50177558a815a792febc06fd1189d))
- docs: the commands reference: bromigos display, net, bluetooth, power, clock, notifications, defaults, startup, panels, memory, about, avatar; setup input's new options ([f27f6e1](https://github.com/bromigos-org/bromigOS-archive/commit/f27f6e1bcc4461a669c691ad94c676a3fc99bde9))
- docs: Settings: the window (groups, the search, the layout, Advanced, Undo, keys, sizes), every page and the command it drives, the API for a page or a section, the tests; the manual's chapter, a section per page (F1 opens it) ([c2cdd15](https://github.com/bromigos-org/bromigOS-archive/commit/c2cdd15ee76e721cc92e7d6d46e1eeddbb3cf36d))
- docs: settings: the VM run, 22/22, and what it can't reach (a virtual Bluetooth controller) ([282fe3b](https://github.com/bromigos-org/bromigOS-archive/commit/282fe3bd032f6112284bec811ca4da55145d7365))
- docs: settings-audit: the After column as built (Ctrl+1…6, narrow rows, the clamp, restyling) ([35ba84d](https://github.com/bromigos-org/bromigOS-archive/commit/35ba84d7ce4ad691c6f7e7397ba0461da6534a48))
- docs: the boot menus' VM runs: UEFI and BIOS, the medium's channels, the installed theme, what they turned up ([58d2616](https://github.com/bromigos-org/bromigOS-archive/commit/58d2616ae1dd3df38c24296754eef54857423fc8))
- docs: install: the fresh-machine run with the keys checks and the live layer's fixes (43/43) ([d64d1aa](https://github.com/bromigos-org/bromigOS-archive/commit/d64d1aac97a344320a3019a8ec3d2096703af1a7))
- docs: README status: the boot menus, the switcher's real previews, the den in colour themes and bromigos lab phase 1 are done; lab phases 2 and 3 planned ([bc78208](https://github.com/bromigos-org/bromigOS-archive/commit/bc782089a3c2658402b30b95448e0b9637a2b454))
- docs: VECTOR's emergency switch in Settings, on the bar and on SUPER+CTRL+ESCAPE; his guard records changes (bromigos vector guard log) instead of switching his terminal off ([06deb5c](https://github.com/bromigos-org/bromigOS-archive/commit/06deb5ce76c9427822c2d47bede57eb9121d03c1))
- docs: add WRITING.md, the guide every doc follows; AGENTS.md points to it ([cb967e9](https://github.com/bromigos-org/bromigOS-archive/commit/cb967e9fda861bd77e159074d9f8943316089e98))
- docs: add CONTRIBUTING.md: layout, build, test, docs and CI ([bf4fc1b](https://github.com/bromigos-org/bromigOS-archive/commit/bf4fc1b5914490fd549d58acb0cdf4299de8d56c))
- docs: rewrite the docs index by topic ([3f85d90](https://github.com/bromigos-org/bromigOS-archive/commit/3f85d906fd624fbb79a32d0e25743ece98edd632))
- docs: images for the README and docs; ASSETS.md as a short checklist with provenance below ([1cab690](https://github.com/bromigos-org/bromigOS-archive/commit/1cab690e257154128f43b40bc10664fbad6ee484))
- docs: rewrite install, update, ISO, encryption and boot pages in plain words ([b4f5cee](https://github.com/bromigos-org/bromigOS-archive/commit/b4f5cee3001896f2e292c77aaaa67eeeacb1037c))
- docs: rewrite theming, worlds and art pages; unbuilt world features marked Planned ([25f2192](https://github.com/bromigos-org/bromigOS-archive/commit/25f2192b86a2fcd9538f91e58f8634c43f3000bf))
- docs: rewrite the desktop, Settings, idle, accessibility, menu and app pages ([a75b92f](https://github.com/bromigos-org/bromigOS-archive/commit/a75b92f103558901c476d77897ba3615fcc9996e))
- docs: rewrite the homelab, lab, model catalog, provisioning and targets pages ([8a6ed48](https://github.com/bromigos-org/bromigOS-archive/commit/8a6ed48743c07652cd1f28978bf0420b4d4a57bc))
- docs: rewrite the extension, plugin, widget, peripheral and hardware pages and the starters' READMEs ([cf35d0a](https://github.com/bromigos-org/bromigOS-archive/commit/cf35d0ab873f94cf45c3aaa9b6ad62b76298da4e))
- docs: rewrite the core, packaging and brand READMEs; add the missing JSON schemas ([3684612](https://github.com/bromigos-org/bromigOS-archive/commit/3684612273dbf9171df3055c8e8874a378eafacb))
- docs: rewrite the live layer, elements and hologram READMEs ([42be161](https://github.com/bromigos-org/bromigOS-archive/commit/42be161d5bbfdb36bb0fc57add6c2c74d4d749f7))
- docs: PLAN.md as a readable plan and decision log ([12bf7f8](https://github.com/bromigos-org/bromigOS-archive/commit/12bf7f8cccfabb1207f9a55cf3a1fc686cd3c1f3))
- docs: README rewritten for someone deciding whether to try bromigOS ([3632acf](https://github.com/bromigos-org/bromigOS-archive/commit/3632acf55c81a99cb14f23de402221e8fbe14e19))
- docs: mark the passages where VECTOR's guard switches his terminal off by itself ([ac10e5b](https://github.com/bromigos-org/bromigOS-archive/commit/ac10e5b4815cc1550c3f68da24ef2f0b899ed691))
- docs: README's hero and theme grid re-exported; the whole LAB widget beside the homelab section ([05ec87c](https://github.com/bromigos-org/bromigOS-archive/commit/05ec87c1a3417d56f66b30b76b5b42efc6a6f55f))
- docs: ASSETS.md: the manual's pictures as one row, listed below the table ([e2e917c](https://github.com/bromigos-org/bromigOS-archive/commit/e2e917c9837ae58d8317c075e101256c756d43f4))
- docs: links follow the manual's new outline: page titles, What gets installed, manual-reference.toml ([ddf7541](https://github.com/bromigos-org/bromigOS-archive/commit/ddf75413a6240b9003085869682ccef405b97fca))
- docs: the Drift map's lore catalogue ships with bromigos-live; its ASSETS.md row in the new layout ([9f596bf](https://github.com/bromigos-org/bromigOS-archive/commit/9f596bf670d6f705c409c9701bf506668674fc2c))
- docs: upscales on SeedVR2, cutouts on Lucida and 3D on Pixal3D in the rewritten art, lab, targets and catalog pages ([0b9c704](https://github.com/bromigos-org/bromigOS-archive/commit/0b9c704ccd3e15c6ce6534810d1e23139d6a10cc))
- docs: VECTOR's emergency switch and the guard's audit log in the rewritten pages ([cc02367](https://github.com/bromigos-org/bromigOS-archive/commit/cc0236733f88ed8e9741bfe5a99c7e7cbfa38e66))
- docs: ASSETS.md: the manual's Welcome picture in the list ([f117a76](https://github.com/bromigos-org/bromigOS-archive/commit/f117a762f8b7ef0ebc895180e4a51d0cd3fcafa3))
- docs: ASSETS.md: the manual's 27 pictures, with the new render set ([35958c6](https://github.com/bromigos-org/bromigOS-archive/commit/35958c62e07f6ee8733f52f7fe2c4082ca7bf1ea))
- docs: README: the full render set, the Tidewell loop near the top, and VECTOR, the menu and bromigos lab in the grid ([5e742f0](https://github.com/bromigos-org/bromigOS-archive/commit/5e742f0314a028324c56dcfb39dfc60b65b2f909))
- docs: the docs index and CONTRIBUTING.md link release.md, CHANGELOG.md and the release workflows ([e730432](https://github.com/bromigos-org/bromigOS-archive/commit/e7304329b5c2d2cd6cc3d51d1519c4cbc7b66fa3))
- docs: README: the loop under the header and the final renders; CONTRIBUTING.md lists tools/screenshots/render.py ([1a87ea4](https://github.com/bromigos-org/bromigOS-archive/commit/1a87ea4a785b5bc5071214899758e34c101ff588))
- docs: the AUR (docs/aur.md): paru, AUR packages in bromigos update's snapshot pair, the review, turning it off, drivers only the AUR has; the VM runs ([c4eb8d5](https://github.com/bromigos-org/bromigOS-archive/commit/c4eb8d52e5f21e83a31b6902268b74adae4465f6))
- docs: the AUR in the rewritten pages: paru at install, AUR packages inside the update's snapshot pair, bromigos aur, AUR-only NVIDIA drivers ([0992673](https://github.com/bromigos-org/bromigOS-archive/commit/0992673779c15079ac625a290ef31a621b2d9d32))
- docs: the package note says 1password repackages 1Password's own download; only herdr and paru are built from source ([028674f](https://github.com/bromigos-org/bromigOS-archive/commit/028674f0c63c2b56bfbd2141d5a453f4af8f43b3))
- docs: release: a known limitation: one web manual, built from main, for every channel; each machine's installed copy matches its packages ([0fecefc](https://github.com/bromigos-org/bromigOS-archive/commit/0fecefc39d3bc44c351248dc83868dc8190068ed))
- docs: the README's Tidewell loop without its flicker: 41 frames the capture rendered without the glow pass, rebuilt from their neighbours ([029b5a3](https://github.com/bromigos-org/bromigOS-archive/commit/029b5a3da5612ecdb568ca135a90c0828eaa473f))
- docs: the README's Tidewell loop deflickered: each frame's lighting matched to the median of the nine around it (some frames were captured brighter than their neighbours too) ([b7bab4e](https://github.com/bromigos-org/bromigOS-archive/commit/b7bab4edaec2b0d57d97a81406159804b3ffbb0a))
- docs: mark the sections bromigos.org reads with <!-- site:… --> comments, so a rewrite can rename them without breaking the site's export ([02e93cb](https://github.com/bromigos-org/bromigOS-archive/commit/02e93cb27d5075b27111e6eec3623753333b98f1))
- docs: SECURITY.md and issue templates ([8374841](https://github.com/bromigos-org/bromigOS-archive/commit/8374841c73ff42f28abe2203a0d9bb5e6dc060f1))
- docs: VECTOR proposes changes as pull requests from his own clones (manual: VECTOR); CODEOWNERS names the operator for the code behind his limits (made from VECTOR's devflow.LIMITS: his merge tool leaves those PRs to you) ([5282cb1](https://github.com/bromigos-org/bromigOS-archive/commit/5282cb1cb526687ff617ebc71852243cc6b0e7ae))
- docs: the README's Tidewell loop rendered again with the capture fixed: every frame whole, no hand repair (120 frames at 960 wide, 1.6 MB) ([d26f41a](https://github.com/bromigos-org/bromigOS-archive/commit/d26f41a5829131062fefff638c296cb3d2956095))
- docs, manual: Mire on the desktop rendered again, with the Sleeper's sharpened clips (7b111ce) ([4b30a91](https://github.com/bromigos-org/bromigOS-archive/commit/4b30a91269fa4e8b34329d979a6ddb8c748e70f1))
- docs: when the kernel or the graphics driver changes: what the update holds back, the live layer's guard, the previews, and the test runs ([60e17ca](https://github.com/bromigos-org/bromigOS-archive/commit/60e17ca354503303320e95dce77b50e71e4019bc))

### Packaging and CI

- ci: iso-check looks for each boot channel's own menu entry, not the word anywhere ([b47009f](https://github.com/bromigos-org/bromigOS-archive/commit/b47009f856414ac777bf5050134224902c0f5236))
- packaging: a tag's publish copies a package another channel has, signed, instead of building it; release tags only from main ([1af68e1](https://github.com/bromigos-org/bromigOS-archive/commit/1af68e1ea70c2588b133a3316ab0d0e7cc08a024))
- ci, docs: releases from GitHub Actions: prepare (notes by the homelab's model, git-cliff's changelog, the release PR), cut on merge, promote rc to stable ([9ce87cd](https://github.com/bromigos-org/bromigOS-archive/commit/9ce87cd63541f891aeefd15b4c382db733920fff))
- packaging: paru, the AUR helper, built into [bromigos] (2.1.0-2, the AUR's recipe with its alpm crates pinned) ([8755140](https://github.com/bromigos-org/bromigOS-archive/commit/875514055fbe6e62b1e03425122aa0a28900bd20))
- ci: the release workflows upload their artifacts with upload-artifact v7 (v4 runs on the deprecated Node 20) ([27a9f07](https://github.com/bromigos-org/bromigOS-archive/commit/27a9f070ba6bb8f26721f5b6d0de04b56bccd553))
- ci: pull requests run on GitHub's hosted runners, never the homelab's ([021ad58](https://github.com/bromigos-org/bromigOS-archive/commit/021ad58214ed84fbeca5265fa9dcd911193c392d))

### Other

- manual: a new outline (getting started, using bromigOS, reference), a glossary, and the Keys and Commands pages grouped by task in plain words ([f52aa31](https://github.com/bromigos-org/bromigOS-archive/commit/f52aa315e13ae877ded5bde1311e586b5174c227))
- manual: getting started rewritten for a new user: Welcome, Install, First run, Getting around, The menu, Windows and workspaces, and a Common tasks page ([579b030](https://github.com/bromigos-org/bromigOS-archive/commit/579b0307d0a704d7df4f84b2e7e5fbf6216f4f96))
- manual: every chapter rewritten in plain words and checked against the code, with new Holograms and Your own shortcuts chapters ([7223bf6](https://github.com/bromigos-org/bromigOS-archive/commit/7223bf6091072ee508ff2e7f350f104350ffb10d))
- manual, docs: pictures next to the steps: the desktop with callouts, the nine themes, the worlds, the screensaver, the gallery, the launcher and eight Settings pages; ASSETS rows for each ([72b00ed](https://github.com/bromigos-org/bromigOS-archive/commit/72b00ed181962499f9ce3825b54db4201b9b1842))
- code comments: the doc sections they cite, by the names the docs rewrite gives them ([da5a0a1](https://github.com/bromigos-org/bromigOS-archive/commit/da5a0a14dc21e233043428540eff1f16dd45404f))
- manual: the desktop on the Welcome page; a colon chain and two semicolons split; VECTOR's brain may not be chosen yet ([6d9123c](https://github.com/bromigos-org/bromigOS-archive/commit/6d9123ce15b39394b868a9da149598b7291a6c3a))
- manual: lab upscale jobs (SeedVR2, built today) and the two upscale services in where AI runs ([1d8c1da](https://github.com/bromigos-org/bromigOS-archive/commit/1d8c1da7eba8d8773908233573ce17af917ba42b))
- manual, docs: the offscreen render set on its pages: the menu, VECTOR, Settings, the theme switcher, Cinder, Mire and Tidewell on the desktop, the holo deck, the timeline, the Drift map, bromigos lab and both boot menus; an ASSETS row each ([04c6ef1](https://github.com/bromigos-org/bromigOS-archive/commit/04c6ef12c41d645ea318bd95dc6b847b0f72406d))
- manual: VECTOR's emergency switch (Super+Ctrl+Esc, the bar's power mark, Settings, bromigos vector off|on) replaces the kill switch; the guard only logs (bromigos vector guard log) ([ba76a56](https://github.com/bromigos-org/bromigOS-archive/commit/ba76a561048bf4758c1103de4b6f9d457b43a2aa))
- manual: What's new's introduction in the manual's style, and linked from Updating and rolling back ([34a06e6](https://github.com/bromigos-org/bromigOS-archive/commit/34a06e675f8520e2fbbe7ef1d0a4dd2c8adb5f03))
- tools: screenshots/render.py, the README's and the manual's pictures drawn offscreen: the desktop in scenes (the hero, the worlds, colour themes), the nine themes as one sheet, VECTOR, the holo deck, the timeline, the Drift map, the menu, Settings, the switcher, bromigos lab and the boot menu, an animated loop of a world behind the panels; every picture read back with tesseract against the words none may show (and the private overlay's names) before it's kept; the switcher's render takes a --backdrop ([a57e121](https://github.com/bromigos-org/bromigOS-archive/commit/a57e121bc4469b0031d31604db66325ddf956fb3))
- test: aur-e2e.sh, the AUR in the fresh-machine VM: a fresh install, an opted-out one, a machine with the AUR's own paru ([1d4c10c](https://github.com/bromigos-org/bromigOS-archive/commit/1d4c10c9dbd6cc87e6278404ab8d239a995af7aa))
- manual: the AUR: installing an app with paru and reading its recipe, AUR packages in bromigos update, the first run's AUR question, --no-aur at install, an older NVIDIA card's driver through hw setup, and a glossary entry ([3de762a](https://github.com/bromigos-org/bromigOS-archive/commit/3de762a7cd8f2c3ca5ab1d4dc515d165af719551))
- test: the VM harnesses' QEMU stops when the session that started it ends ([c491733](https://github.com/bromigos-org/bromigOS-archive/commit/c4917339a82bca3591a4887f891cb29c9f13438e))
- tests, tools: the private-name checks no longer spell the names they look for ([2d80486](https://github.com/bromigos-org/bromigOS-archive/commit/2d80486f0b2dc74aecea4b88dae94f780987d9cb))

### VECTOR (bromigos-vector)

#### Added

- The holograms follow bromigOS's motion setting (accessibility.toml: full, reduced, still) ([ee0c832](https://github.com/bromigos-org/vector-archive/commit/ee0c8321fc8bab2efc52b95abfc638783b340dbf))
- The lab console for VECTOR: lab_console, lab_jobs, lab_job_submit, lab_job_cancel; his terminal reads bromigos lab and refuses what changes the lab ([c5f67cb](https://github.com/bromigos-org/vector-archive/commit/c5f67cb496585edcc2635558b9a997ad33b667d3))
- VECTOR and the hologram gallery in the app launcher: desktop entries with their icons, and gallery-show (opens, never a toggle) ([d6f66cb](https://github.com/bromigos-org/vector-archive/commit/d6f66cbf7cc7b82e64af5ff74a67dfd3b758123c))
- The worlds' holograms in the gallery, shelf by shelf, each in its world's colours ([39145cc](https://github.com/bromigos-org/vector-archive/commit/39145cc46327fe990faf9c1a829a3937934bd9aa))
- The lab's settings are read-only to him: ~/.config/bromigos/lab.toml (the model planner, the upgrade policy, the catalog bench) ([76a1a50](https://github.com/bromigos-org/vector-archive/commit/76a1a50e1afec7901162f871c2ae8f3b5d5ec27e))
- The operator's emergency switch (bromigos vector off|on, SUPER+CTRL+ESCAPE, the bar, Settings); Changed: the guard's sentinel only audits, it never switches VECTOR off ([988f945](https://github.com/bromigos-org/vector-archive/commit/988f945b58402330addabd247667af69179d8c06))
- VECTOR's own clones and pull requests (work_clone, work_status, work_branch, work_commit, work_push, pr_open, pr_watch, pr_merge, pr_close; bromigos-holo work) as his GitHub account bromigodev; pr_merge never merges a PR that touches the code behind his limits (devflow.LIMITS, CODEOWNERS) ([4f6d14e](https://github.com/bromigos-org/vector-archive/commit/4f6d14e09ad7cd2acfbe967dd844b9047e10a918))

#### Changed

- His homelab making follows the lab's new models: cutouts are Lucida, 3D is Pixal3D (shape only, stood upright), and lab_job_submit's upscale takes an image or a short clip (SeedVR2 7B) ([f235825](https://github.com/bromigos-org/vector-archive/commit/f235825cf70c63b3115c16985d0cdc7901da4e12))
- VECTOR names no one's trading system: a user's own system comes in through plugin hooks, and their real money through vector.toml [real_money] ([6f3e202](https://github.com/bromigos-org/vector-archive/commit/6f3e202737c3ea6c2f1926f029fdd52a11599dc0))

#### Fixed

- The state file is written before VECTOR's scene exists (voices and colour empty until then), not a traceback at startup ([09218bf](https://github.com/bromigos-org/vector-archive/commit/09218bfd037aa0777bf0bb319e8f659f54423423))
- A voice change publishes VECTOR's state at once, so a keyboard dial steps through every voice (it read a stale mode and only ever reached the first and last) ([ee3fbdf](https://github.com/bromigos-org/vector-archive/commit/ee3fbdf12bc88a805059547773431b321a0f0d8d))
- The privacy guard reads a list's lists in a sops file (- - ENC[…]) as encrypted, not as plaintext values ([cb51f48](https://github.com/bromigos-org/vector-archive/commit/cb51f48b9377513e3d3a56e8843edcefc2bd368f))
- The guard's notice says his terminal stays off until you run bromigos-holo shell on, not until he's restarted (a restart leaves it off) ([897ab9e](https://github.com/bromigos-org/vector-archive/commit/897ab9e74b49bf73bbd4a31032a95324f7a31ec0))
- Bromigos-holo stop now stops at once (the launcher dropped "now"); stop and restart [now] return once the daemon has gone, so restart during a turn starts a new one; a started daemon no longer holds the caller's output open; the usage names the real verbs (history, voice by its key) and evals has no timer ([9c05dd4](https://github.com/bromigos-org/vector-archive/commit/9c05dd42db6dd4716be2b976d4f4e6e4027d288d))
- Pr_merge merges by rebase, so his commits land on main authored by bromigodev's noreply address (a squash merge was authored with the account's own email) ([4375763](https://github.com/bromigos-org/vector-archive/commit/437576378bf2b9365c050f03cc94ff193f310e80))
- The privacy guard's sops test uses made-up node names ([1a26563](https://github.com/bromigos-org/vector-archive/commit/1a2656334df76c65bdbf67cd5558eaabf1f47b91))
- Test-plugin-systems.py's child keeps this user's pip packages (CI installs them with --user) ([8cff3a7](https://github.com/bromigos-org/vector-archive/commit/8cff3a7983246e1392cc2a546081ddfc4eb85e38))

#### Docs

- docs: reduced motion in the holograms: what each setting changes, how still frames are drawn, the tests ([49a21e9](https://github.com/bromigos-org/vector-archive/commit/49a21e91846f2e9c7df22ca0c8f7a1806e153f69))
- docs: VECTOR for a newcomer: a task-first README with a console render, and docs/ pages for safety, configuration, tools, holograms, interfaces and development ([9f8b5d7](https://github.com/bromigos-org/vector-archive/commit/9f8b5d77ebf29f3cfcb602ee385194c4d95b528f))
- docs: the emergency switch (where it is, what off does, why it works with VECTOR hung, why only you switch him on, its files) and the guard as an audit log ([f04a3b8](https://github.com/bromigos-org/vector-archive/commit/f04a3b83b55b12f5ec80f57b3e489bd43e1f3277))
- docs: CHANGELOG.md, the technical log release by release (v0.1.0, v0.1.1 from the tags) ([806bab0](https://github.com/bromigos-org/vector-archive/commit/806bab071023af5e21cfb73be5a2c811b3490e78))
- docs: SECURITY.md, issue templates and the brand assets' licence ([db5ce4a](https://github.com/bromigos-org/vector-archive/commit/db5ce4a890180edbb0fd8daa34109747234c76ed))
- docs: his pull requests (safety.md: his clones, his account, what his merge tool never merges and why it's the enforcement; tools.md; development.md: test-devflow.py and the PR checks; README) ([3a51b95](https://github.com/bromigos-org/vector-archive/commit/3a51b9594e8944a595f9df1c408a9b4c193a0b31))
- docs: README: the guard audits his safety code, it doesn't switch him off (#3) ([fadb522](https://github.com/bromigos-org/vector-archive/commit/fadb522a870efa7f11c2ce50d40932ae99c52667))
- docs: propose-a-change: when his terminal refuses a test script for what its text names, he says so and lets CI run it ([67f98a8](https://github.com/bromigos-org/vector-archive/commit/67f98a8a0e3a9716ef8af5d0a7bcc7e502529681))
- docs: the hologram previews rendered again over the empty den with made-up readings (offscreen.py OFF_DEMO=1) ([ef1a550](https://github.com/bromigos-org/vector-archive/commit/ef1a5502091165d36d462f4f9d9259016332e94a))

#### Packaging and CI

- packaging: ship every docs page in /usr/share/doc/bromigos-vector, not only plugins.md ([b80b2dd](https://github.com/bromigos-org/vector-archive/commit/b80b2dd438e9795699d5b8680feee2ed856e4cef))
- packaging: a tag's publish copies bromigos-vector from another channel, signed, instead of building it; release tags only from main ([ac0863a](https://github.com/bromigos-org/vector-archive/commit/ac0863ace01293fdb00c87050091b925e2621758))

## [0.1.1] - 2026-10-08
<!-- release: 0.1.1 -->

Since v0.1.0.

### Core (the bromigos command)

- core: bromigos update starts the OSD when it's installed but not running, and restarts it when stale ([d7e3d77](https://github.com/bromigos-org/bromigOS-archive/commit/d7e3d775d3733de8afc640a21d75923ee98e6072))
- install: the rollback step's pacman doesn't stop to ask under --yes ([23d9d59](https://github.com/bromigos-org/bromigOS-archive/commit/23d9d59ebdf588dbad900e18242a3585cfd5a775))
- cli: bromigos update --check prints the OSD's 'start' (fixes the build after d7e3d77) ([e77713a](https://github.com/bromigos-org/bromigOS-archive/commit/e77713a3ae2f7caa9686777c13f5ff82d443411d))
- core: bromigos ext, extensions from git (manifest, ledger, trust, updates, starters) ([8047425](https://github.com/bromigos-org/bromigOS-archive/commit/804742565c628ebc93cfed162071c974a796a7ce))
- core: a channel switch drops the old channel's sync database ([cdc78af](https://github.com/bromigos-org/bromigOS-archive/commit/cdc78af001f4b43f0e6efe27ba289b3422b8a111))
- core: rollback: GRUB seen without /boot, wheel may list root's snapshots, the overlay hook, an install chroot ([88556a2](https://github.com/bromigos-org/bromigOS-archive/commit/88556a234ecb7814d7f5513420074b4949deb610))
- core: rollback status: a systemd initramfs can't take the overlay hook, so setup isn't asked for it ([6903a3f](https://github.com/bromigos-org/bromigOS-archive/commit/6903a3f5dc604ddff1a9f00babb5f58e589e2209))
- core: rollback setup sees an arch-chroot: its root mount isn't PID 1's ([db950b8](https://github.com/bromigos-org/bromigOS-archive/commit/db950b8b7ba8e6831ee1aafdadae93c7bbc18bd7))

### Desktop

- desktop: the theme switcher asks bromigos ext for catalog themes directly (it's a built-in, not an executable) ([72e3a15](https://github.com/bromigos-org/bromigOS-archive/commit/72e3a15b9ebc658448fbed43b865756463c763a2))

### Boot and the ISO

- iso: GRUB, LUKS2 by default, btrfs with snapper, the stable channel; the install tested end to end ([7b730d9](https://github.com/bromigos-org/bromigOS-archive/commit/7b730d9bbca938afb53799a765b883e6a9ddb825))
- iso: the installer sets up rollback with `bromigos rollback setup`; the harness proves it as the user ([c4ab3be](https://github.com/bromigos-org/bromigOS-archive/commit/c4ab3be9effb5731df919d6792ff9e54a09e3f94))

### Tests and tools

- test/vm: the app bundle's checks run (they sat after the exit) ([d85c321](https://github.com/bromigos-org/bromigOS-archive/commit/d85c321f0382f94d8405b3ff0c201c5bb8491632))
- test/vm: shellcheck: ext_repo is called through check (declare -f) ([d703de2](https://github.com/bromigos-org/bromigOS-archive/commit/d703de29e8192d731bc9d1b37bd4ee8fdbe25873))

### Docs

- docs: extensions (the author's guide), the manual's page, plugins, theming, PLAN ([39603df](https://github.com/bromigos-org/bromigOS-archive/commit/39603dfcea148e0c227b4d3b7c8aab230cd85bac))
- docs: the command reference, key table and package tables are generated, and CI checks them ([91a3448](https://github.com/bromigos-org/bromigOS-archive/commit/91a344857625c26e8eec764105b41efb9a445e24))
- docs: a whole documentation run: the README, docs/ by topic, the manual, the folder READMEs ([5f05a5a](https://github.com/bromigos-org/bromigOS-archive/commit/5f05a5a1cd00629516536c2dee2c54d4c48777b7))
- docs: PLAN: phase 3 is complete; the update -> rollback VM run is done (the ISO's) ([6c3d163](https://github.com/bromigos-org/bromigOS-archive/commit/6c3d1634dd792f5d9da6c2b7139ce20c1c3635f1))
- (withheld by the privacy check) ([c05e6d9](https://github.com/bromigos-org/bromigOS-archive/commit/c05e6d9c28863275ca21dfb6280ea786b1a1dc0c))
- docs: ASSETS: the world art, den and holograms are cleared under their model terms; the ByteDance clips are not ([36a3c48](https://github.com/bromigos-org/bromigOS-archive/commit/36a3c4821e231f20f01397f13846f5e2e6883a9a))

### Packaging and CI

- ci: docs: build the CLI with two jobs and no debug info (the small runner ran out of memory) ([555a28d](https://github.com/bromigos-org/bromigOS-archive/commit/555a28d9114713d35d016efd72f6275ed0376680))
- ci: docs: the command reference's cargo build runs on the package builder with its own cache ([c286208](https://github.com/bromigos-org/bromigOS-archive/commit/c286208246b761592dd370d30df2a2939b2dd1b1))

### VECTOR (bromigos-vector)

#### Added

- His state file names his voices and the colour of the one in use ([afc7592](https://github.com/bromigos-org/vector-archive/commit/afc75921634700644bfe838974b6987bf9187456))

#### Changed

- VECTOR's guard knows extensions: it accepts only what bromigos ext recorded, and he can't install them ([cfa24e2](https://github.com/bromigos-org/vector-archive/commit/cfa24e2f87388272ead7b08780fc0f5b3be76808))

#### Docs

- docs: VECTOR as a product: the README, the guard as it is, the skills index ([8682f23](https://github.com/bromigos-org/vector-archive/commit/8682f23423fd498ef3e8ed0172f8c7d319ddf5b9))
- docs: the guard watches extensions' plugin and homelab links, not skills ([437b771](https://github.com/bromigos-org/vector-archive/commit/437b77160b03ea9152fee43076adbe92455bde61))

#### Packaging and CI

- ci: one packages concurrency group per channel, so a tag's stable publish isn't cancelled by pushes to main ([bbf4da4](https://github.com/bromigos-org/vector-archive/commit/bbf4da48e1710b8d30a61b85752a863b6eed694e))

## [0.1.0] - 2026-10-08
<!-- release: 0.1.0 -->

The first release.

### Added

- BromigOS plan, asset checklist and agent rules ([529eeb2](https://github.com/bromigos-org/bromigOS-archive/commit/529eeb2306fe4c1ce344dc9ae9f2d9b29f5f186d))

### Changed

- Audience is the Bromigos community first; no feature regressions on the operator's desktop ([d1f20dc](https://github.com/bromigos-org/bromigOS-archive/commit/d1f20dccda96932eb0c85be51c574da23700c726))
- PLAN.md and ASSETS.md against the desktop as it is today — an inventory of every piece (VECTOR's brain, memory, voices, read/desk/shell/act/Vault/herdr tools, change tracking, skills, the holograms, the Razer module) split into core and plugin; status line (planning, nothing moved yet); memory, web search and default voice as open decisions; asset rows for the starship, avatar, sound cues, designed caretaker voices, skills and Razer files, with the Brodec cast as a personal plugin; README target rows ([a36354a](https://github.com/bromigos-org/bromigOS-archive/commit/a36354a8d822fd8be533ea72713eef2b921e4878))

### Core (the bromigos command)

- core: Rust core library and bromigos CLI ([0bacbae](https://github.com/bromigos-org/bromigOS-archive/commit/0bacbaea70ecd37fe3dd42045f51ccc207a7faf3))
- core: end quietly on a closed pipe (SIGPIPE default); ci: set PACKAGER ([c0c10ed](https://github.com/bromigos-org/bromigOS-archive/commit/c0c10ed472369515d9ab96cacdd5b705ff333d03))
- core: bromigos profile, who the user is and what VECTOR calls them ([87bb360](https://github.com/bromigos-org/bromigOS-archive/commit/87bb3604c2696b43af48d8c0072923aad17f9614))
- core: profile values edited by hand that break the rules read as absent ([ab63e9f](https://github.com/bromigos-org/bromigOS-archive/commit/ab63e9f85642e507825789c7bafcdc1cb8239449))
- core: bromigos theme list|current|set renders the theme with minijinja and swaps it in atomically ([c05892b](https://github.com/bromigos-org/bromigOS-archive/commit/c05892b4640690b58ca3806b3f2ef1494450b5ea))
- core: theme set brings a world's backgrounds/ and live/ into current/ and tells the live layer ([4262030](https://github.com/bromigos-org/bromigOS-archive/commit/42620308b10f553cbd5bd56bd5619b8b2baeaed0))
- core: bromigos art plans, makes and tracks a world's art through the nolgia SDK ([80c4a6a](https://github.com/bromigos-org/bromigOS-archive/commit/80c4a6aadd87d69144c837569f9c2c635247bb1f))
- core: the nolgia SDK on the system's OpenSSL, so the package builds with makepkg's flags ([9969b24](https://github.com/bromigos-org/bromigOS-archive/commit/9969b24073075014b086217ec781af1a80e41e95))
- core: theme set recolours everything: palette.json, the bar's icons, hooks ([c00ccbd](https://github.com/bromigos-org/bromigOS-archive/commit/c00ccbd639c8f205ef88ae468a644df446be1759))
- core: the worlds test reads a flyby's sprites from its craft ([40bde0e](https://github.com/bromigos-org/bromigOS-archive/commit/40bde0eda914931139b1a75fb9dba29e35665b12))
- core: bromigos vector uses the packaged bromigos-holo (bromigos-vector) when installed ([a0e8f01](https://github.com/bromigos-org/bromigOS-archive/commit/a0e8f01242e7a13cf7d98beba2e22f2d77db4fc6))
- install: install.sh, bromigos install, bromigos setup, and the bromigos meta-package ([2442459](https://github.com/bromigos-org/bromigOS-archive/commit/2442459105e5062c3446243c4b72b0ac7f77971d))
- core: bromigos setup homelab runs bromigos-homelab's detector; with --homelab/--answers FILE the built-in copy ([e57b70d](https://github.com/bromigos-org/bromigOS-archive/commit/e57b70dfd10285e9129973b3ca8af7b88ab00857))
- core: bromigos private, secrets and emblem; the brand's shareable sources in brand/ ([4c7a926](https://github.com/bromigos-org/bromigOS-archive/commit/4c7a9261f47358da8df11085b1070ff92458bf23))
- core: the session tests wait for their fake process to exec (a flaky check() broke a publish) ([6668f44](https://github.com/bromigos-org/bromigOS-archive/commit/6668f44949ed232900f9ba89c8672743efc4bfd4))
- setup: monitors (primary, order, scale, refresh) in the user's hyprland.lua; creation tools (create.toml format 1) ([d17847f](https://github.com/bromigos-org/bromigOS-archive/commit/d17847f8d134c9b9c9d5b45f3809c58af4b54025))
- update: replace the hand-installed theme files bromigos-settings now ships, instead of failing ([0026b20](https://github.com/bromigos-org/bromigOS-archive/commit/0026b2086ce52f844fc9223193f26a4d87c79b51))
- core: bromigos update no longer hangs after restarting a daemon ([9bb349f](https://github.com/bromigos-org/bromigOS-archive/commit/9bb349f3246bc7716a696c5c244faecc351c26b9))
- core: bromigos update restarts VECTOR's voice server too ([1cf3208](https://github.com/bromigos-org/bromigOS-archive/commit/1cf3208681be0381b2e7e90323b3638d7c581973))
- setup: nolgia sign-in without a terminal (--nolgia-token-file / nolgia_token_file) ([3e91596](https://github.com/bromigos-org/bromigOS-archive/commit/3e915960e72e722a487b790c7578b50da38f3c92))
- core: where AI runs: targets.toml (homelab, local, cloud) and bromigos target ([0e80938](https://github.com/bromigos-org/bromigOS-archive/commit/0e80938c0be34def9f9ef8db2a097b2d58d4e2c3))
- migrations: the start page waits for an old user unit to go, then enables the packaged timer ([b8515bd](https://github.com/bromigos-org/bromigOS-archive/commit/b8515bd1973d6646c02262ed1d3812603b73f87c))
- core: theme set and bromigos update restart waybar instead of reloading it ([ede8fb0](https://github.com/bromigos-org/bromigOS-archive/commit/ede8fb05a897210ffbb6cc0b98705864289dc211))
- core: bromigos theme install <git url|dir> and remove; bromigos mute says it on the OSD ([b0aca7c](https://github.com/bromigos-org/bromigOS-archive/commit/b0aca7c5059372d098df5cb28af17d29c1d932d2))
- update: a snapshot around every update and --rollback; channels (stable, rc, edge, dev); the manual ([10788b4](https://github.com/bromigos-org/bromigOS-archive/commit/10788b4d78e85a93c0896df04e50d8d2bd5e09a8))
- core: bromigos channel aligns its channel list ([6d1dd8e](https://github.com/bromigos-org/bromigOS-archive/commit/6d1dd8e5d11ce2c6eddf830930735fb795a3ec45))

### Desktop

- desktop: the desktop's configs ship as defaults (bromigos-desktop); bromigos update with migrations ([a824c16](https://github.com/bromigos-org/bromigOS-archive/commit/a824c1665836c7e7bde3ce9a80e2d788ab158ccf))
- desktop: the hooks, the wallpaper tool and the Wick's den ship; the session's plumbing is declared ([0cb44e1](https://github.com/bromigos-org/bromigOS-archive/commit/0cb44e197906e31e2cfec11a9e1d9929bf5bb1b0))
- settings: bromigos-settings, what exists before a user does ([4545204](https://github.com/bromigos-org/bromigOS-archive/commit/45452046a83ee8c43d73aed155be7fcb5bb1a1c4))
- settings: the login screen is Bromigos's (zz-bromigos.conf, read after sddm's own default.conf) ([9a1491a](https://github.com/bromigos-org/bromigOS-archive/commit/9a1491a38e6e548e6b9fd160991a2328cc56f352))
- desktop, live, widgets: monitors are plug and play ([df61095](https://github.com/bromigos-org/bromigOS-archive/commit/df61095302f2977e44d34803c23fcf26c498e906))
- wallpaper: one swaybg restart at a time (login's apply and monitor.added raced: two per output); test/vm: --heads N, shot NAME [HEAD] ([79e9fc0](https://github.com/bromigos-org/bromigOS-archive/commit/79e9fc0fe7332a86689f06a567fe09afeaa97c49))
- desktop: hotplug, tested: workspaces split in place and fold back; the wallpaper follows unplugs ([693855c](https://github.com/bromigos-org/bromigOS-archive/commit/693855cf9aeae77214e48bb9b41e30fc4e499d8d))
- desktop: the start page ships (bromigos-desktop): a self-contained per-user folder, the lab from bromigos-homelab, links from startpage.toml ([c58b622](https://github.com/bromigos-org/bromigOS-archive/commit/c58b622ca2debef536a6c06f7a74422e448c0857))
- desktop: the lock screens name the packaged emblem hook's path ([c09f19f](https://github.com/bromigos-org/bromigOS-archive/commit/c09f19f3b8f5eef787d614760fb1c8637460756b))
- desktop: the start page's folder can be set in startpage.toml (dir), so an existing browser setup keeps its path ([ae2f9e1](https://github.com/bromigos-org/bromigOS-archive/commit/ae2f9e1ecb7f76a4bae36d563e861b050bcc186f))
- desktop: one mute for the whole desktop (bromigos mute): the theme's sounds and VECTOR's voice together ([84901ef](https://github.com/bromigos-org/bromigOS-archive/commit/84901efdd03ceac365946509dd23539e1062e25a))
- desktop: the bar pip's middle-click is the desktop mute (theme + VECTOR) ([b913e28](https://github.com/bromigos-org/bromigOS-archive/commit/b913e281b92d812fa5e21a391b82852fcccf6d18))
- desktop: the bar pip's middle-click mutes VECTOR alone again; bromigos mute is the keys' and the dial's ([d33ffc3](https://github.com/bromigos-org/bromigOS-archive/commit/d33ffc3af21a47ca6f11be3a312548ee44bdf59d))
- settings: the Bromigos boot splash (a Plymouth theme from the emblem kit) ([891a8e7](https://github.com/bromigos-org/bromigOS-archive/commit/891a8e744d5ee12f7d58fbccfa93de77fed23d82))
- desktop: the bar's VECTOR pip says MUTED, not VOICE MUTED, when the desktop mute is on ([eacb286](https://github.com/bromigos-org/bromigOS-archive/commit/eacb286ae35ee7a6b32b781d260ab09be6d42a25))
- desktop: floating windows go back where they were, per workspace and app (bromigos windows) ([7e8eb45](https://github.com/bromigos-org/bromigOS-archive/commit/7e8eb4506916eca760f44ce70700ce62a04dcd04))
- desktop: the menu (SUPER+SPACE), the theme switcher, web apps, setup menus and the OSD ([917d0c8](https://github.com/bromigos-org/bromigOS-archive/commit/917d0c882bc28f54ae3991e33a91ab5e2df97d3a))
- desktop: a command places itself in the menu (bromigos:menu=, bromigos:prompt=); the switcher lists a catalog's themes ([ab8dca2](https://github.com/bromigos-org/bromigOS-archive/commit/ab8dca2fa864038a62e8589a4a7bfa191ac26731))
- desktop: the start page snapshot copies through a private temporary name ([48d4779](https://github.com/bromigos-org/bromigOS-archive/commit/48d477952dc3c476cf2264553d3f61237b158d02))

### Live layer

- live: worlds -> Wick: the den's glyph rain came up in the last theme's colour ([47c66b2](https://github.com/bromigos-org/bromigOS-archive/commit/47c66b29bff949c5c72b1d84598ad5cd4d6e83f6))
- live: a crowd's per-member art (sprites = [...]) is glow art too: no box around it ([82ff2d9](https://github.com/bromigos-org/bromigOS-archive/commit/82ff2d9f633279ccc01314e09f8a1ba68401b001))
- live: VECTOR from the installed package (bromigos-vector) or the dotfiles' copy, and steps aside without him ([cccf789](https://github.com/bromigos-org/bromigOS-archive/commit/cccf789a56c19475ae2297659382be87943f2e0e))
- live, widgets, wallpaper: the output is this machine's, not a hard-coded DP-1 ([b4e4fcb](https://github.com/bromigos-org/bromigOS-archive/commit/b4e4fcb84fd06f596b12510ac2b9bb6884796c07))
- live: no DP-1 fallback for the activity watcher (the resolved output, or none) ([f1e9767](https://github.com/bromigos-org/bromigOS-archive/commit/f1e976709baa60e089e79ddb1964651fe2611db6))
- live: config.toml layers merge (packaged, then the user's thin file); menus and screenshots in the theme's colours ([2cf0e09](https://github.com/bromigos-org/bromigOS-archive/commit/2cf0e097e2dbdb8873fdc2a235b41b2980e11b86))
- live: screens that aren't 16:9 get the scene cropped to cover them, never stretched ([42d6a66](https://github.com/bromigos-org/bromigOS-archive/commit/42d6a6656ac927c02fda04b3ca415e1e1ad071a5))

### Boot and the ISO

- iso: the bromigOS live and install medium (archiso's releng with bromigOS on top) ([e4fc4a1](https://github.com/bromigos-org/bromigOS-archive/commit/e4fc4a182a03d13143576c7bb7710353a6607129))
- iso: the install is btrfs on LUKS2 by default, Limine boots it, snapper's snapshots in its menu ([c3c85e0](https://github.com/bromigos-org/bromigOS-archive/commit/c3c85e0e8e2a4d185aac39181b17198b881c8d00))
- iso: the installer reads find's limine.conf paths with a while loop (shellcheck SC2044) ([9208d96](https://github.com/bromigos-org/bromigOS-archive/commit/9208d96c15a7f9906b61a60aa15776b33aa25208))
- iso: the offline repository's sign options as archinstall names them (Optional, TrustedOnly) ([c2ddfc1](https://github.com/bromigos-org/bromigOS-archive/commit/c2ddfc1a02612536aa329988e867c24d642703be))
- iso: no second [bromigos] section for pacstrap; the offline copy carries what archinstall straps on its own ([b6a4679](https://github.com/bromigos-org/bromigOS-archive/commit/b6a4679acf307477ac704855be924bd2628af789))

### Widgets

- widgets: a weather panel (Open-Meteo) and a NetworkManager panel, off by default ([5be597c](https://github.com/bromigos-org/bromigOS-archive/commit/5be597c301585b9686e51bb616a52414346c09a7))

### Themes and art

- theme: wick, the first theme, as data; templates for waybar, gtklock, rofi, kitty, dunst, Hyprland, KDE ([756efc4](https://github.com/bromigos-org/bromigOS-archive/commit/756efc4a45450ce5cbff6981a86a1cccdff8b778))
- theme: mire and tidewell, the first worlds, with placeholder art; the world format ([e94125c](https://github.com/bromigos-org/bromigOS-archive/commit/e94125cf0912eb638cf4da9e6c9240fdebcd4c7f))
- theme: tidewell seen from under the surface; mire's keeper clear of the lantern ([4a4c403](https://github.com/bromigos-org/bromigOS-archive/commit/4a4c403fc33a761a55d6763a7c3f09656b2c7533))
- theme: mire and tidewell fitted to the approved comps; Sleeper heads in Mire's foreground; worlds.md mapping ([c68874c](https://github.com/bromigos-org/bromigOS-archive/commit/c68874c25da13f779c97695b7c897738c70b1ceb))
- theme: mire and tidewell describe their art in art.toml, seeded from the first pass ([2afef00](https://github.com/bromigos-org/bromigOS-archive/commit/2afef00af4a01bb5dc176c8b8ec3b9b5137a8f2b))
- theme: mire's Sleepers rise and submerge with their agents; live fireflies; one-shot clips in the format ([9689b30](https://github.com/bromigos-org/bromigOS-archive/commit/9689b30855864f765aff76c3e897133b933c7152))
- theme: mire and tidewell real art: approved comps, layers, actors, loops and Sleeper clips ([3ba639a](https://github.com/bromigos-org/bromigOS-archive/commit/3ba639ab397043f6752a7cd251224c8d1f2f8c79))
- theme: mire and tidewell run on the real art; the placeholders go ([0a92993](https://github.com/bromigos-org/bromigOS-archive/commit/0a929937c8ec097fa0e75a9ccf7cf43af8db880a))
- theme: mire's art log records the hand clips and Hollis's loop as made ([de6cfe8](https://github.com/bromigos-org/bromigOS-archive/commit/de6cfe86b1054795ed336a0c2c1b07c8f3e3632a))
- theme: mire keeps Hollis's loop on the GPU at half size (it is drawn at 204x221) ([28fc415](https://github.com/bromigos-org/bromigOS-archive/commit/28fc41550b88e0c4c054786033b866eeabe33457))
- theme: tidewell: the nets trail behind the trawlers, real silver fish, no moored ship ([3ad0946](https://github.com/bromigos-org/bromigOS-archive/commit/3ad0946f393032d8fb1bbe83fce2b870bae4389a))
- theme: mire and tidewell: craft overhead, now and then, sooner with network traffic ([dbdd549](https://github.com/bromigos-org/bromigOS-archive/commit/dbdd549a700bf0fac679f55f28531aed1d9778c2))
- theme: each world's post has its own emblem (Mire's and Greywater Light's marks) ([fa791c0](https://github.com/bromigos-org/bromigOS-archive/commit/fa791c0beb4fd77cd00f6cd5658939160c8d60c8))
- theme: tidewell: every craft overhead passes behind Greywater Light, sized and hazed as farther off ([f50869f](https://github.com/bromigos-org/bromigOS-archive/commit/f50869ff22e41fc74d9c5eeb8e4059b4c30f0ba1))
- theme: tidewell: the Choir waits under the water and breaches now and then, not every 8 s on top of it ([904d473](https://github.com/bromigos-org/bromigOS-archive/commit/904d473d103c0735eea6c09d50ba02fa5b0c2405))
- theme: mire: rain from the work going on: agents drizzle, the homelab's models rain, CPU pours ([0d5f08f](https://github.com/bromigos-org/bromigOS-archive/commit/0d5f08f4331d707e88c1f2ab461258c4e41b99c2))
- theme: tidewell: its own sea life (lampfry, veilwings, burrs) instead of fish; the painted fish painted out ([38955b1](https://github.com/bromigos-org/bromigOS-archive/commit/38955b19e2ac6cae81a78c7dce65805027513967))
- theme: tidewell: the lampfry spread into three loose shoals, drifting slower ([3750190](https://github.com/bromigos-org/bromigOS-archive/commit/3750190c62923bb198d9667929fbea225cbb6463))
- theme: mire and tidewell: the unlock intercept takes the world's look ([64d9481](https://github.com/bromigos-org/bromigOS-archive/commit/64d9481ca1cb02773f23b218a08bd2300f9ddcaf))
- theme: tidewell: the whole water to the Sliver's flank, resident jellyfish, linebloom ([d13f2a7](https://github.com/bromigos-org/bromigOS-archive/commit/d13f2a779886eee6e7109391e1c4514ec3ff44e6))
- theme: tidewell: the Choir glows: brighter at work, brightest when it needs you, dim when done ([c9c99bd](https://github.com/bromigos-org/bromigOS-archive/commit/c9c99bd1315d7488be2cad3258be41610f97a6b6))
- theme: tidewell: the resident jellyfish in pink, orange, violet, cyan, mint and gold ([80c57eb](https://github.com/bromigos-org/bromigOS-archive/commit/80c57eb45d94e8d57dffe0ed50aaa48efa069852))
- theme: tidewell: linebloom in its own colours: violet, pink, orange, gold and cyan, calmer ([25913ed](https://github.com/bromigos-org/bromigOS-archive/commit/25913ed96db59a29c5aed5d704dbff8d83c25121))
- theme: tidewell: the healthy linebloom bright enough for its colours to read ([0f50f2c](https://github.com/bromigos-org/bromigOS-archive/commit/0f50f2c3ed41cee8350a0e93fc3cb230312e4050))
- theme: tidewell: the linebloom holds steady instead of throbbing ([5f18189](https://github.com/bromigos-org/bromigOS-archive/commit/5f1818935f070000195b90d7f26cf3d8858869b4))
- theme: tidewell: the healthy linebloom's own breathing barely there (±4%) ([739f7f9](https://github.com/bromigos-org/bromigOS-archive/commit/739f7f99e998a216454df5968319ee71c9dc6978))
- theme: tidewell: the resident jellyfish are two-tone: a primary and a contrasting accent ([cb25658](https://github.com/bromigos-org/bromigOS-archive/commit/cb256584973d7e1a6881d79aa2e7acdace62294f))
- theme: tidewell: the rose jellyfish's cyan arms hang down its centre ([0a88ff6](https://github.com/bromigos-org/bromigOS-archive/commit/0a88ff6142609764af46057b6c428c65335a8da2))
- art: a homelab backend: model = "homelab:qwen-image-2.1" runs on the user's ComfyUI for no credits ([f9227aa](https://github.com/bromigos-org/bromigOS-archive/commit/f9227aa9a9bb625d95b36d00fddb60343a1594a7))
- theme: the bar icons' builder (theme/tools/build-icons.py) moves in from the operator's dotfiles ([60f677a](https://github.com/bromigos-org/bromigOS-archive/commit/60f677a67a44140eac4f7e01b4ad8db47eeb40b0))
- art: creation providers (create.toml), local cutout and 3D, bromigos art make ([9f515e9](https://github.com/bromigos-org/bromigOS-archive/commit/9f515e944552ab30aa7f42ee7872f08c2d0e59e3))
- art: a nolgia 3D job has no paid texture pass unless asked; art make --extra KEY=VALUE ([da3a879](https://github.com/bromigos-org/bromigOS-archive/commit/da3a879c9ed5424332018c3e21d0a182eca5638e))
- theme: reaches neovim, btop, tmux, Chromium, Firefox and the OSD; six colour themes from the Drift ([6fa1327](https://github.com/bromigos-org/bromigOS-archive/commit/6fa132746ee6687baae0ebe67f3a48e2d9d9e7e4))
- theme: the OSD's stylesheet is swayosd.css (the shell batch's); the duplicate osd.css template goes ([cee6cfa](https://github.com/bromigos-org/bromigOS-archive/commit/cee6cfac553612c035cc80c771a6e0e6b5e32528))

### Homelab

- homelab: bromigos-homelab: connect any homelab to the desktop (capabilities, adapters, setup, declared panels) ([cd80dc4](https://github.com/bromigos-org/bromigOS-archive/commit/cd80dc4cc188ab978f89a26753b33bfa6d39e49f))
- homelab: the rack hologram ships with bromigos-homelab (shown with a homelab configured) ([bb078ea](https://github.com/bromigos-org/bromigOS-archive/commit/bb078ea34b6e8405098e420c0d926c1f14102665))
- homelab: voice and media capabilities (bromigos-voice and comfyui adapters) ([4cc43c1](https://github.com/bromigos-org/bromigOS-archive/commit/4cc43c10290437c0ea3e39a6d601f5bccfc4c8ad))
- homelab: Proxmox and Netdata adapters (hosts, workloads; metrics, hosts), tested on recorded answers ([42c14b5](https://github.com/bromigos-org/bromigOS-archive/commit/42c14b5f04e3da9bf4c52cd478c376903bdd0d8b))

### Apps

- apps: bromigos-apps, the app bundle: LazyVim, tmux, lazygit, mise, Chromium, Spotify, Signal (1Password built into the repo) ([9a8e1b0](https://github.com/bromigos-org/bromigOS-archive/commit/9a8e1b0f8c2f60a70dc8be4c917b54dd20f9afcd))

### Tests and tools

- test/vm: the CA copied writable (a second up), the SDDM check passes shellcheck ([e8d1894](https://github.com/bromigos-org/bromigOS-archive/commit/e8d18949880754b9922918101ebfbe5d467d6e4d))
- test/vm: --heads N gives N outputs (a virtio GPU each: QEMU leaves a second head of one GPU disconnected without a display client) ([5e6282f](https://github.com/bromigos-org/bromigOS-archive/commit/5e6282fda2ba0821e82edeb5be4e9236707e4603))
- test/vm: the fresh-machine test can install optional packages (BROMIGOS_VM_WITH) and checks the app bundle ([ac09278](https://github.com/bromigos-org/bromigOS-archive/commit/ac09278736e69218d1c7cb0d34df32ccf27d0c77))

### Docs

- docs: the repo is bromigOS ([71fb0d9](https://github.com/bromigos-org/bromigOS-archive/commit/71fb0d971223034520ba6ba7e2a92c01b3cfda78))
- (withheld by the privacy check) ([2f60731](https://github.com/bromigos-org/bromigOS-archive/commit/2f607315cc831c5092defcda56cd4f6c89a293f6))
- docs: decisions: MIT OR Apache-2.0, local-first brain, designed default voice, configurable SearXNG, SQLite memory; licenses added ([87e06e6](https://github.com/bromigos-org/bromigOS-archive/commit/87e06e6bb3ee8a60ec3a395546f29c83e48bd699))
- (withheld by the privacy check) ([a5c1bf6](https://github.com/bromigos-org/bromigOS-archive/commit/a5c1bf64f67fc4099703f2a8f55f4982a1a22300))
- docs: worlds: the view from each post, its keeper, and the real data every inhabitant shows ([59ae2fd](https://github.com/bromigos-org/bromigOS-archive/commit/59ae2fdfaf2b09be55dd11185434fea9bde71a15))
- docs: worlds: Tidewell is mostly underwater, Greywater Light small on the Sliver ([4cc07c1](https://github.com/bromigos-org/bromigOS-archive/commit/4cc07c18234c7d2f426679456480793d635cee3a))
- docs: worlds: Mire centres on the shack, with a crashed gunship and wreckage ([084e3be](https://github.com/bromigos-org/bromigOS-archive/commit/084e3be594ec34f3ffe6532268c9289e14f6e2be))
- docs: PLAN: VECTOR is packaged (bromigos-org/vector, bromigos-vector); what stays in his core ([905ce41](https://github.com/bromigos-org/bromigOS-archive/commit/905ce41565a086e4e0fd2b65d71e27bb6722a71f))
- docs: what bromigOS is about (holograms, homelab integrations, themes, widgets); bromigos-homelab closes phase 1 ([43f5c97](https://github.com/bromigos-org/bromigOS-archive/commit/43f5c97a9f812b6b33e29535de533290d8184806))
- docs: install.md (install.sh, bromigos install and setup, the packages, the VM test); the VM script passes shellcheck ([144305f](https://github.com/bromigos-org/bromigOS-archive/commit/144305f1e3d010102c2ea48f381ad5d98c734af0))
- docs: art: create.toml (format 1): capabilities, provider ids, endpoints and references, workflows, art make ([dd86d0f](https://github.com/bromigos-org/bromigOS-archive/commit/dd86d0f7336c2b88ac3fa7c1df59e0b9980db414))
- docs: monitors are plug and play (desktop.md); setup monitors and create, and the VM run's results (install.md) ([e788e99](https://github.com/bromigos-org/bromigOS-archive/commit/e788e99cf3bf59ad690e72497af03306e4ea85e1))
- docs: PLAN: phase 2's progress (a fresh install works end to end; what's left) ([fd81679](https://github.com/bromigos-org/bromigOS-archive/commit/fd8167945adfb0a754e5451610463fb6921667c3))
- docs: what the fresh-machine VM test needs to run in CI (KVM, ~8 GiB) and why it waits ([63178f3](https://github.com/bromigos-org/bromigOS-archive/commit/63178f3c48a8d4d7f1dfa142d66ceebebd3f339b))
- docs: PLAN: phases 1 and 2 complete (lock screens and live config thin, start page packaged, cover fit, unattended nolgia, Proxmox/Netdata); follow-ups listed ([39a21a2](https://github.com/bromigos-org/bromigOS-archive/commit/39a21a2d6988abc86eb56993091129120ec7f99c))
- (withheld by the privacy check) ([97f218c](https://github.com/bromigos-org/bromigOS-archive/commit/97f218c49279a3d84ecf249e8486799a5f6b3e60))
- docs: the theme's new outputs and colour themes, the weather and connections panels, windows, the app bundle ([4508a54](https://github.com/bromigos-org/bromigOS-archive/commit/4508a54e3a5acc30cb9d489c78a6841901da637b))
- docs: PLAN: the reach batch is done (themes past the desktop, six colour themes, weather and connections, windows, the app bundle) ([c8cd137](https://github.com/bromigos-org/bromigOS-archive/commit/c8cd13729c844ef7c8954af926a6c95f1fa790c8))

### Packaging and CI

- packaging: bromigos-keyring, bromigos-core, publish and setup scripts ([5376b0e](https://github.com/bromigos-org/bromigOS-archive/commit/5376b0ec91c15d8a97ee4bfe624376172eddd618))
- ci: build, sign and publish packages on push to main ([28249ef](https://github.com/bromigos-org/bromigOS-archive/commit/28249ef538f41549d6e862609999318020cb35c8))
- packaging: the live layer and the widgets move into bromigOS (bromigos-live, bromigos-widgets) ([bba3164](https://github.com/bromigos-org/bromigOS-archive/commit/bba31645254aa8f3cada5e7919280bba6b6e8337))
- packaging: CI installs only build-time dependencies (bromigos-live depends on bromigos-core) ([e75d3ee](https://github.com/bromigos-org/bromigOS-archive/commit/e75d3eea2b4953ac233c6f769c08b30b9110a193))
- packaging: bromigos-live and bromigos-widgets make no -debug package ([3b7cb10](https://github.com/bromigos-org/bromigOS-archive/commit/3b7cb10a9502c532d977d039440a9faafa31f372))
- packaging: one publisher at a time across repositories (a lease in the bucket) ([a186b60](https://github.com/bromigos-org/bromigOS-archive/commit/a186b6038c620dd12eec042f6b5169c38cb610b9))
- packaging: Geist Mono, built into bromigOS's repository (ttf-geist-mono) ([73db314](https://github.com/bromigos-org/bromigOS-archive/commit/73db31440260bfb843f1454ee43669cbf3ea13a6))
- packaging: bromigos-settings builds again (gresource is glib2-devel's; Pillow for the cursors) ([488b8d2](https://github.com/bromigos-org/bromigOS-archive/commit/488b8d2c2fc15fcad8c962c55c5ae3de98453eb6))
- ci: install.sh's smoke test; publish on settings/ and install.sh; the fresh-machine VM test ([dfb8a20](https://github.com/bromigos-org/bromigOS-archive/commit/dfb8a2004c74a4d9a88653940dda18646df22877))
- packaging: herdr, built into bromigOS's repository ([a77dcaa](https://github.com/bromigos-org/bromigOS-archive/commit/a77dcaae16cd50918d39cb975cbff55eca8aae31))
- ci: cargo's registry and bromigos-core's target persist in the runners' node cache ([ab0c68d](https://github.com/bromigos-org/bromigOS-archive/commit/ab0c68d7a7980cd0207b23778052a039ccf8cd88))
- ci: iso-check's bash steps run in bash (the runner's default shell is sh), with file_permissions declared as mkarchiso does ([0d90324](https://github.com/bromigos-org/bromigOS-archive/commit/0d9032474e26e60ce1a905b4adf9fc8930143076))
- packaging: bromigos-desktop ships bromigos-windows and starts it at login; bromigos-apps is an option of the meta-package; CI builds on apps/ ([16e99d0](https://github.com/bromigos-org/bromigOS-archive/commit/16e99d04ada9372526cb92958ca7b8c743b73f6f))
- packaging: bromigos-desktop ships bromigos-windows and starts it at login; CI builds on apps/ ([8658815](https://github.com/bromigos-org/bromigOS-archive/commit/8658815e26c30fc0890e93c12230b08d7c9a466a))
- ci: one packages concurrency group per channel, so a tag's stable publish isn't cancelled by pushes to main ([4ae00b5](https://github.com/bromigos-org/bromigOS-archive/commit/4ae00b54673f00122f0ebb23ab2a1f6dbd6a130a))

### VECTOR (bromigos-vector)

#### Added

- Bromigos-vector, VECTOR as a bromigOS package ([95dd61b](https://github.com/bromigos-org/vector-archive/commit/95dd61b1c0d980c3f183d34644a9f6d3204cddc6))
- VECTOR's hologram models ship with him; the tools take a collection (--root) ([b4ce347](https://github.com/bromigos-org/vector-archive/commit/b4ce3478555a3cd605cc41d442cab05ed0578f08))
- VECTOR speaks and listens through the lab first (engine lab), his own GPU only as the fallback ([4b7a3ad](https://github.com/bromigos-org/vector-archive/commit/4b7a3adb7ddf23f8f51bca51f138e951cdbbd953))
- VECTOR makes images, cutouts, 3D meshes and holograms on the homelab, never a paid provider on his own ([a1b448e](https://github.com/bromigos-org/vector-archive/commit/a1b448e87fa2a5b4dd0392e0842aff177cedbe8a))
- VECTOR's voice, hearing, brain and creation follow bromigOS's targets.toml (homelab, local, cloud) ([bb26d64](https://github.com/bromigos-org/vector-archive/commit/bb26d644238d5e07ef3580001b1d5b8cafccb34e))
- VECTOR's input box grows with what you type (up to 8 lines, then scrolls) ([1834fde](https://github.com/bromigos-org/vector-archive/commit/1834fde9bbe1b1bc4eb65c5cb851a21b16172cc3))
- VECTOR's mute takes on|off|toggle|status (for bromigos mute, the desktop's one mute) ([c627475](https://github.com/bromigos-org/vector-archive/commit/c6274751be15868529c751022728125493bd9cec))

#### Changed

- VECTOR from the operator's dotfiles (linux/.config/bromigos/holo at c136274) ([4ef0b1e](https://github.com/bromigos-org/vector-archive/commit/4ef0b1e365463732e8eba7a485ddca8cff86ce36))
- The operator's voice-cast tool (make-refs.py) from the package; it lives in his dotfiles ([b602414](https://github.com/bromigos-org/vector-archive/commit/b6024149d7053d3db8c204435704b044436b7369))
- The homelab read tools out of VECTOR's core into bromigos-homelab's VECTOR plugin ([c11de54](https://github.com/bromigos-org/vector-archive/commit/c11de548a4f254a67ca527f2077c5e07ea7e9938))
- VECTOR keeps his connections to the lab voice alive (a small pool), so a line doesn't pay a TLS handshake ([959b468](https://github.com/bromigos-org/vector-archive/commit/959b468409f499fd7ee58319dc4dcc2b66dd90e3))
- VECTOR's mute tooltip: the pip's middle-click mutes all sound (theme + VECTOR) ([9b7776f](https://github.com/bromigos-org/vector-archive/commit/9b7776f6ebfeb56fe71c4b3cfe4e4d74532362ff))
- VECTOR's mute tooltip: the bar pip mutes him alone; the keys mute all sound ([87d21d7](https://github.com/bromigos-org/vector-archive/commit/87d21d74e6a5b8c534e9e193e446c13e1da7b722))

#### Fixed

- The guard names paths.py and llm.py by path only (common names elsewhere) ([63300f1](https://github.com/bromigos-org/vector-archive/commit/63300f15c2bf87de639a595f2716f525eac9d6a6))
- Bromigos-holo's help lists evals and setup ([40cd472](https://github.com/bromigos-org/vector-archive/commit/40cd4725595045aa91107e9f24184ad5b8f87eba))
- The hyprland-config skill describes bromigos-desktop's layout (defaults in /usr/share, the user's thin hyprland.lua) and the auto-reload rule ([9662820](https://github.com/bromigos-org/vector-archive/commit/966282017f0b49b4b1d719cd07ed69074a199d0a))
- The build loop changes Hyprland's config without tripping its emergency mode ([92342ee](https://github.com/bromigos-org/vector-archive/commit/92342ee321bd321e0e60466c1bd39116a51e6702))
- A reading whose name has a digit (wick.solar2) is known to make-holo and the gallery's source map ([7515bc0](https://github.com/bromigos-org/vector-archive/commit/7515bc0ed71b589accf919c6667baebb4f63b548))
- With the lab voice up, the local cast voice no longer loads onto his GPU ([164e9bf](https://github.com/bromigos-org/vector-archive/commit/164e9bf48a10ae590aa61a153634c0fe31a8cecf))
- The guard's tripwire watches what VECTOR runs, and accepts verified package updates ([521a3b0](https://github.com/bromigos-org/vector-archive/commit/521a3b0e1e0885ff2bda5fe10f8c4159a3b7dfeb))

#### VECTOR

- holo: the hologram's output is bromigOS's primary, not a hard-coded DP-1 ([f381d67](https://github.com/bromigos-org/vector-archive/commit/f381d6724641a0513efd2240b944cca0e83c5429))

#### Tests and tools

- tools/holo: gen3d.py runs on bromigOS's creation providers (bromigos art make model3d.generate) ([49fb85d](https://github.com/bromigos-org/vector-archive/commit/49fb85d5c1f5ad0cbd81725898398a6d75d9f423))

#### Packaging and CI

- packaging: channels: a version tag publishes bromigos-vector to stable (vX.Y.Z) or rc (-rcN); main stays edge ([cf333d4](https://github.com/bromigos-org/vector-archive/commit/cf333d47e6c213d80bebb61c12ff6d9040a6ee64))
