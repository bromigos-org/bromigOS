# Themed QR codes

bromigOS draws its QR codes in the world's own colours, with the world's emblem in the middle.
The installer (its graphical and text screens), Settings and Field Kit all use the same
component, `lib/bromigos_qr.py` (package `bromigos-core`). Every code is checked by decoding
it before it's shown. If a style can't be read here, the next safer one is used instead.

## The styles

| Style | For | What it looks like |
|---|---|---|
| `camera` | Codes any phone camera must read: store links, share links | The world's dark ink on its light paper, rounded modules, finder patterns drawn as the emblem's rings, the emblem in the centre |
| `brodec` | Codes only BRODEC's scanner reads: pairing codes | Inverted: the world's glowing light on its dark, with the same rings and emblem |
| `art` | BRODEC, when the screen has room for a picture | `brodec`'s colours with the world's picture blended in as a halftone |

When unsure, use `camera`. It's the one every phone reads.

On a terminal the code is drawn in coloured half blocks in the world's `camera` inks, with
both colours set in every cell so no font can leave gaps between rows. On kitty's terminal
(the kitty graphics protocol) the image itself is shown.

## From the command line

```bash
bromigos qr show https://bromigos.org                 # in this terminal
bromigos qr png https://bromigos.org code.png --style brodec --world mire
bromigos qr gallery /tmp/qr                           # every style in every world, decoded
```

`bromigos qr png` prints the style the code ended up as. That's the one asked for, unless a
decoder here couldn't read it.

## For power users

### In Python

```python
import bromigos_qr as Q
img, style = Q.render(text, style="art", world="wick")    # a PIL image, and the style used
Q.save(text, "code.png", style="camera")
print("\n".join(Q.terminal(text)))                        # half blocks, the world's inks
Q.kitty(png_bytes)                                        # kitty's graphics escape
```

A GUI shows the image in a DRIFTGLASS frame. Only the frame moves: a Pulse while it waits, and
a Spark when the code is scanned or the pairing is done. The code itself never animates.

### How each style stays readable

- **Error correction H**, so up to 30% of the code can be covered or damaged.
- **The emblem's plate** is 22% of the code's width, under 5% of its area.
- **Finder patterns** keep the 1:1:3:1:1 widths decoders look for: a ring one module
  thick, a light ring, then a 3×3 disc.
- **The inks** are the world's selection colour, darkened, and its text colour, lightened.
  Inverted styles use its background and its glowing primary. Both pairs are pushed apart
  until their contrast ratio (WCAG) is at least 7.
- **`brodec`'s glow** is a blur of the light ink under the modules. The modules are drawn
  sharp again over it, and each dark module keeps a dark centre.
- **`art`** keeps each data module's centre, half its width, at full contrast. The rest of
  the module carries the world's picture, toned 55% towards the module's own colour.
  Finders, timing and alignment patterns, and the format and version information, stay
  solid. The picture is the theme's background painting when it has one, else its emblem
  art. This is the halftone-QR technique.

### The decode test

`check` saves the image and reads it back. Then it reads two versions made to look like a
phone's camera: 300 and 200 pixels across, a 0.8 px blur, and a slight perspective tilt on a
grey table.

- `zbarimg` and ZXing (`ZXingReader`, package `zxing-cpp`) read `camera`, with ZXing's
  inverted search off.
- ZXing alone reads `brodec` and `art`, with its inverted search on. zbar has no inverted
  search.

`bromigos qr gallery` does this for every style in every world, and writes `report.json`.
`tests/qr` runs it in `bromigos-core`'s package check.

| Style | zbar | ZXing (inverted search off) | ZXing (inverted search on) |
|---|---|---|---|
| `camera` | reads, in every world | reads, in every world | reads |
| `brodec` | doesn't (inverted) | doesn't (inverted) | reads, in every world |
| `art` | doesn't (inverted) | doesn't (inverted) | reads, in every world |

### BRODEC's scanner

To read `brodec` and `art` codes, the app's scanner uses ZXing (zxing-cpp's `ReaderOptions`,
or the same settings in its bindings):

| Setting | Value | Why |
|---|---|---|
| `formats` | `QRCode` | Only QR, so it's faster and makes fewer false reads |
| `tryInvert` | `true` | `brodec` and `art` are light on dark |
| `tryHarder` | `true` | The art's halftone and the glow |
| `tryRotate` | `true` | A phone held at any angle |
| `tryDownscale` | `true` | Close-up frames from a phone's camera |
| `binarizer` | `LocalAverage` | Uneven light across a screen |
| `isPure` | `false` | A camera frame, not a clean image |
| `returnErrors` | `false` | Only codes whose checksum is right |

A scanner without an inverted search, such as ML Kit or AVFoundation, can invert each frame's
luminance and try again when the first pass finds nothing. If neither works, BRODEC should ask
the machine for `camera`.
