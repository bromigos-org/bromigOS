# Web apps

A web app is a website opened in its own window. It appears in the launcher like any other
app, and it can have a key of its own. `bromigos webapp` makes them.

This page is for someone changing how web apps work. For using them, read the manual's
[Web apps](../manual/src/webapps.md) page.

## Commands

```bash
bromigos webapp add gmail https://mail.google.com --hotkey "SUPER + SHIFT + G"
bromigos webapp add --from-catalog youtube
bromigos webapp list
bromigos webapp launch gmail
bromigos webapp remove gmail
bromigos webapp catalog
```

In the menu, INSTALL › Web app… asks for the name and then the URL. The catalog's web apps
sit under INSTALL as `Web app: …`, and REMOVE lists yours.

## What `add` does

1. It records the web app in `~/.config/bromigos/webapps.toml`, as an `[[app]]` with a
   name, title, URL, icon and hotkey. The name may use `a-z`, `0-9` and `-`. It names the
   window and the desktop entry.
2. It writes `~/.local/share/applications/bromigos-webapp-<name>.desktop`. So the site
   shows in the menu's LAUNCH group and in `rofi -show drun`.
3. It fetches the site's icon into `~/.local/share/bromigos/webapps/`. It tries
   `apple-touch-icon.png` first, then `favicon.ico`. `--icon FILE|URL` picks one instead.
4. With `--hotkey`, it writes the key into a marked block at the end of your
   `~/.config/hypr/hyprland.lua` (`-- >>> bromigos webapps`), using the defaults' bind
   helper.

Hyprland then takes the new key the safe way. Auto-reload goes off before the write, the
config is verified, Hyprland reloads once, and no new config errors may appear. If
anything fails, the old file comes back. `remove` takes the key out again.

You can also set the key by pressing it. Use SETUP › Shortcuts… › WEB APP in the menu, or
`bromigos keys bind --webapp NAME`. It's the same key, kept in the same place, and a clash
with any other key is caught there. See
[desktop.md](desktop.md#shortcuts-you-set-by-pressing-the-keys).

## The window

`launch` opens the site in the first browser it finds.

- **A Chromium-family browser** opens it with `--app=<url>`, as a frameless window with its
  own class, `bromigos-webapp-<name>`. So Hyprland rules can place it. The browsers it
  looks for are Google Chrome, Chromium, Brave, Vivaldi and Microsoft Edge.
- **LibreWolf, Firefox or Zen** open a new window instead, since they have no app mode.

The web app shares the browser's profile. So sign in to the site in your browser first.

## The catalog

The catalog has a few web apps ready to add: ChatGPT, YouTube, GitHub, Gmail, Google
Calendar, Google Maps, Google Messages and Google Photos. None is added until you add it.
