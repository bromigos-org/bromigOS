# Web apps

A web app is a website in a window of its own, without the browser's tabs and address bar.
It's in the app launcher like any other app, and it can have its own key.

## Add a web app

1. Open the menu (<kbd>Super</kbd>+<kbd>Space</kbd>) and choose **INSTALL › Web app…**.
2. Type a name for it, such as `gmail`.
3. Type the site's address, such as `https://mail.google.com`.

The web app is now in the app launcher (<kbd>Alt</kbd>+<kbd>P</kbd>).

Some are ready-made. The menu's **INSTALL** group lists them, such as **Web app: Gmail**
and **Web app: YouTube**. Choose one to add it.

## Sign in

A web app uses your browser's profile. Sign in to the site in your browser first, and the
web app is signed in too.

The window opens in the first Chromium-based browser it finds, in this order: Chrome,
Chromium, Brave, Vivaldi, Edge. Without one, it uses LibreWolf, Firefox or Zen. These have
no app windows, so the web app opens as a normal browser window.

## Give it a key

Add `--hotkey` when you add it from a terminal:

```bash
bromigos webapp add gmail https://mail.google.com --hotkey "SUPER + SHIFT + G"
```

Or give an existing web app a key in **Settings › Shortcuts**. See
[Your own shortcuts](shortcuts.md).

## From a terminal

```bash
bromigos webapp catalog                     # the ready-made ones
bromigos webapp add --from-catalog youtube  # add a ready-made one
bromigos webapp list                        # yours
bromigos webapp remove gmail                # remove one, and its key
```

A web app uses the site's own icon. To choose another, add `--icon` and a file or an
address.

## Remove a web app

Open the menu and choose it under **REMOVE**, or run `bromigos webapp remove` and its name.
