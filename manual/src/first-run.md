# First run

At the end of the install, bromigOS asks a few questions in the terminal: your monitors,
the theme, where VECTOR's thinking runs, and so on. Most questions have a sensible answer
already chosen, so you can press <kbd>Enter</kbd>. The Homelab question starts on
**Skip**. If you have a settings file for your homelab, press <kbd>↑</kbd> to choose it,
then <kbd>Tab</kbd> to type its path. You can change any answer later.

If you installed from the bromigOS USB stick, these questions were answered for you: the
Wick theme, with VECTOR's brain, voice and creation tools off. Run `bromigos setup` to
answer them yourself.

## Answer the questions

Each question is a page with a list of choices.

| To | Press |
|---|---|
| choose an answer | <kbd>↑</kbd> and <kbd>↓</kbd> |
| fill in a choice's details, such as an address | <kbd>Tab</kbd>, then type |
| go to the next question | <kbd>Enter</kbd> |
| go back | <kbd>Esc</kbd> |
| skip a section, and keep its answer as it is | <kbd>S</kbd> |
| leave without changing anything | <kbd>Ctrl</kbd>+<kbd>C</kbd> |

At the end, a review page lists your answers. Press <kbd>Enter</kbd> to apply them.

## The questions

| Question | What you choose |
|---|---|
| Monitors | Which monitor is your main one, their order from left to right, and their scale and refresh rate. Monitors you plug in later work on their own. |
| The AUR | Whether to keep an AUR helper, paru, so you can install apps from the [AUR](apps.md#install-an-app-from-the-aur) and update them with everything else. |
| Hardware | Whether to set up what your hardware needs, such as the graphics driver. See [Hardware](hardware.md). |
| Motion | How much the desktop moves: full, reduced or still. See [Accessibility](accessibility.md). |
| Contrast | Normal or high contrast. |
| Theme | The look of the whole desktop. The Wick is the default. See [Themes and worlds](themes-and-worlds.md). |
| VECTOR's brain | The AI model [VECTOR](vector.md) thinks with: a local Ollama, another server, or none for now. |
| VECTOR's voice | Whether VECTOR speaks, and whether his voice runs on your graphics card or the processor. Setting up a voice downloads it, which takes a few minutes. |
| Homelab | A settings file that lists [your homelab's](homelab.md) services, or Skip. Later, `bromigos setup homelab` finds them for you. |
| Where AI runs | Whether AI work runs on your homelab, this machine, or the paid cloud, in which order. See [Creating with AI](where-ai-runs.md). |
| Creation | The tools that make images, cutouts, 3D models and video loops. |
| Peripherals | Only asked when a supported device is connected, such as a Razer keyboard. See [Keyboards and peripherals](peripherals.md). |

> **The cloud costs money.** The suggested order for AI work leaves the paid cloud out,
> unless this machine has nothing else that can do the work. Check the order on the review
> page before you press <kbd>Enter</kbd>.

## Change an answer later

To ask one question again, run `bromigos setup` with the section's name. Your other
answers stay as they are. For example, to change VECTOR's voice:

```bash
bromigos setup voice
```

The sections are `monitors`, `aur`, `hardware`, `accessibility`, `theme`, `vector`,
`voice`, `homelab`, `targets`, `create` and `peripherals`. Run `bromigos setup` on its own to answer
them all again.

You can also open the menu with <kbd>Super</kbd>+<kbd>Space</kbd> and choose **SETUP**.
Each question is an item there. Most answers are in [Settings](settings.md) too.

## Set up many machines the same way

To install without questions, write the answers in a file and pass it to setup:

```bash
bromigos setup --answers answers.toml
```

Or give answers as options, such as `bromigos setup --theme mire --voice off`. The file's
format is in the developer docs, `docs/install.md`, and `bromigos setup --help` lists every
option.

## Where your answers go

Most answers are saved as your own settings, in `~/.config/bromigos/` and in your
`~/.config/hypr/hyprland.lua`. The theme you pick is kept in
`~/.local/state/bromigos/theme/`. See [Files and folders](files.md).
