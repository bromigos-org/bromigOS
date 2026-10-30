<!-- Draft for bromigos.org's "Installing bromigOS" page. A separate website job publishes it;
     the screenshots are the installer's own, from a test computer with made-up names
     (shots/final/NN-name.png in the installer's test output); the image links below are where
     the website job puts them (https://bromigos.org/images/installing/NN-name.png). The manual's
     "The installer" page has the full detail. -->

# Installing bromigOS

Installing bromigOS takes about ten minutes. You don't need to know Linux, and you don't
type any commands. The installer asks a few questions in plain words, shows you a summary,
and changes nothing on your computer until you press **Install**.

You can keep Windows. bromigOS can go beside it, and each time the computer starts you
choose which one to use.

## Before you start

- **Back up anything important.** The installer is careful, but changing a disk always
  carries a small risk.
- **Plug in the charger** if it's a laptop.
- **Keeping Windows?** Do two things in Windows first:
  - **Turn off Fast Startup.** Open Control Panel › Power Options › Choose what the power
    buttons do. Click "Change settings that are currently unavailable" and untick
    **Turn on fast startup**. Then hold **Shift** while you click **Shut down**.
  - **If Windows uses BitLocker (Device encryption), save its recovery key.** Open
    Settings › Privacy & security › Device encryption › Back up your recovery key, or sign
    in at aka.ms/myrecoverykey on another device. Write down the 48 digits and keep them
    somewhere that isn't this computer. Windows may ask for the key once after bromigOS is
    installed.
- **A USB stick** of 8 GB or more. Everything on it is replaced.

## Make the stick

Download the bromigOS image and write it to the stick with a tool like balenaEtcher (on
Windows or macOS) or `dd` (on Linux).

## Start from the stick

Plug the stick in and restart. Open the computer's boot menu, often with **F12**, **F11**,
**F8** or **Esc** right after switching on, and choose the USB stick.

![The stick's menu: try bromigOS, install it, or install it in text mode](https://bromigos.org/images/installing/01-boot-menu.png)

- **Install bromigOS** opens the installer.
- **Start bromigOS (try it live)** lets you look around first. Nothing is installed and
  nothing on the computer changes. A welcome card offers **Try bromigOS** or **Install
  bromigOS** whenever you're ready.

![The welcome card on the live desktop](https://bromigos.org/images/installing/02-welcome-card.png)

## The steps

### Welcome

Choose the language for your new system and your time zone. You don't need the internet:
everything bromigOS needs is on the stick.

![Welcome: language, time zone, network](https://bromigos.org/images/installing/03-welcome.png)

### Before you start

Shown only when there's something worth knowing, such as running on battery or a disk that
reports it's failing. Each line says what to do.

![Before you start: things about this computer worth knowing](https://bromigos.org/images/installing/04-checks.png)

### What kind of computer is this?

**bromigOS (desktop)** is the usual choice: the full desktop for a computer you sit at.
**bromigOS Server** has no desktop, for servers and lab machines.

![What kind of computer is this?](https://bromigos.org/images/installing/05-kind.png)

### Your keyboard

Pick the layout that matches your keys, and try it in the box.

![Your keyboard, with a box to try it](https://bromigos.org/images/installing/06-keyboard.png)

### Where to install

You see every disk with its size, its model and what's on it. Pick one, then choose how:

- **Install alongside Windows.** Windows and its files stay. If there isn't enough free
  space, the installer makes Windows' part smaller. Drag the slider to choose how much each
  gets: Windows keeps what it uses now plus room to grow, and bromigOS gets at least 20 GB.

  ![Install alongside Windows, with the slider](https://bromigos.org/images/installing/07-where-to-install-alongside-windows.png)

- **Erase the whole disk.** Everything on the disk is deleted, and the screen tells you
  what that is.

  ![Erase the whole disk](https://bromigos.org/images/installing/08-where-to-install-erase.png)

If something stops the installer from going beside Windows, it tells you why and what to
do. For example, if Fast Startup is on, it shows how to turn it off.

### Windows' recovery key

Only if Windows uses BitLocker. Save the recovery key (see "Before you start"), then tick
**I've saved the BitLocker recovery key**. bromigOS never changes a BitLocker drive.

![Save Windows' recovery key](https://bromigos.org/images/installing/09-bitlocker.png)

### About you

Your name, a user name for signing in, a password, and a name for the computer.

![About you](https://bromigos.org/images/installing/10-about-you.png)

### Encryption

On by default, and recommended. If the computer is lost or stolen, your files stay
private. You type the passphrase each time the computer starts; by default it's your
password. Remember it: nobody can recover a forgotten passphrase.

![Lock the disk](https://bromigos.org/images/installing/11-encryption.png)

### Remote access (bromigOS Server)

For a server: whether you can sign in from another computer (SSH, with keys only by
default), the firewall, and automatic updates. Each is explained in one line.

![Remote access and protection](https://bromigos.org/images/installing/12-remote-access.png)

### Summary

Every choice in plain words. Check it, then press **Install** (or **Erase disk and
install**).

![Ready to install](https://bromigos.org/images/installing/13-summary.png)

### Installing and done

A progress bar shows how far it has got. When it's done, press **Restart now** and take out
the stick when the screen goes dark. Type your passphrase when asked, then sign in.

![Installing](https://bromigos.org/images/installing/14-installing.png)

![bromigOS is installed](https://bromigos.org/images/installing/15-done.png)

## Reinstalling and keeping your files

If bromigOS is already on the disk, the installer offers **Reinstall bromigOS and keep my
files**. You get a fresh system, and your home folder (your documents, pictures and
settings) stays as it is. The old system is kept as a snapshot, so nothing is lost.

## No picture? Text mode

If the screen stays black or the desktop doesn't start, choose **Install bromigOS (text
mode)** in the stick's menu. It's the same installer, with the same questions, on a plain
text screen. It also works with a screen reader: choose **Start with the screen reader
(speech)**, and the installer asks its questions one at a time, read aloud.

![The text installer](https://bromigos.org/images/installing/16-text-mode.png)

## Installing many computers

An answer file on a USB drive installs bromigOS with no questions: it counts down ten
seconds (you can cancel), then installs by itself. Put a file named `install.toml` in a
folder named `bromigos` on any USB drive:

```toml
[install]
disk = "/dev/nvme0n1"
mode = "erase"
user = "alex"
password = "correct horse battery staple"
timezone = "Europe/London"
keyboard = "gb"
```

Every setting is in the manual's [answer files](https://github.com/bromigos-org/bromigOS/blob/main/manual/src/installer.md#answer-files)
section.

## After installing

The first time you sign in, a short **welcome tour** helps you connect to Wi-Fi, pick a
world for your desktop, set up VECTOR, connect your homelab, and pair your phone with the
BRODEC app. Every step can be skipped, and the tour opens again from Settings › About.

## Getting help

If the install stops, the installer says what happened and what to do. Press **Save a
problem report** to put the details (never your password) on a USB drive, and attach that
file when you ask for help.
