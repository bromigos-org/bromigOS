# Power menu

Open the keyboard menu from a terminal or a Linux text console:

```sh
bromigos power menu
```

Choose **Suspend**, **Restart** or **Shut down** with the arrow keys, then press
Enter. Each action opens a confirmation with **Cancel** selected. Move to the
action and press Enter to proceed. Escape goes back or closes the menu.
The keys j/k move through choices; h/l select the confirmation buttons. Tab also
moves between choices.

Try the menu without changing the machine's power state:

```sh
bromigos power menu --preview
```

The menu uses symbols supported by text-console fonts. If the terminal becomes too
small, action keys stop working until it is large enough again. Escape still closes it.
Normal system permissions and applications' shutdown inhibitors apply. A refused
action reports an error after restoring your terminal.

On the desktop, <kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>E</kbd> opens the existing graphical
power menu. Both menus request the normal system shutdown or restart. The
[Plymouth splash](boot-menu.md#the-startup-and-shutdown-splash) provides the closing visuals
when graphical splash support is enabled.
