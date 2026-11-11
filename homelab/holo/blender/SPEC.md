# Script-built holograms: the written specs

Built by `build.py` in Blender (headless, its Python API), one object per
feature, every object named `<part id>:<feature>` so the part ids stay the
shipped ones. Units are metres. Blender's axes: x to the right, -y toward the
viewer (the front), z up; the glTF export turns that into y up and +z front,
which is what the hologram bake expects. Nothing is copied from an image: the
dimensions below are a real product class's, and the layout follows the
current holograms and their references only as far as what parts exist and
roughly where.

## Battery backup (UPS), parts `front` and `battery`

A tower UPS of the 1.5 to 3 kVA class (the size of an APC Smart-UPS tower):

| Feature | Part | Spec |
|---|---|---|
| Body | battery | 0.22 wide, 0.42 high, 0.36 deep, standing 0.012 off the floor; vertical edges rounded (radius 0.012, 3 steps), top edges with a 0.004 chamfer |
| Feet | battery | four, 0.03 x 0.03 x 0.012, inset 0.025 from the corners |
| Front bezel | front | a raised panel 0.11 wide from 0.19 to 0.405 high, 0.006 proud of the face, its edges chamfered |
| Display | front | 0.064 x 0.095, set into the bezel's upper half (its glass 0.002 below the bezel's face, framed) |
| Power button | front | round, 0.018 across, 0.004 proud, below the display; a status light beside it |
| Front grille | battery | 13 vertical slots, each 0.0045 wide and 0.13 high, from 0.035 to 0.165 high across the middle 0.12 of the face |
| Side vents | battery | on both sides, near the back: 9 horizontal slots 0.11 long, 0.005 high, every 0.012, from 0.05 to 0.15 high |
| Rear | battery | four outlets and an input socket on the back panel, a fan grille |
| Power cable | battery | a cable out of the lower left of the face to a loose coil of three turns on the floor beside the left side, ending in a plug |

## The rack, parts `switch`, `nodes`, `gpu`, `storage`, `ups`, `frame`

A 24U 19-inch server cabinet on casters (1U = 44.45 mm, faceplates 482.6 mm
wide), open front, the equipment of a small homelab:

| Feature | Part | Spec |
|---|---|---|
| Cabinet | frame | 0.60 wide, 0.60 deep (a homelab 600 x 600 cabinet), 1.25 high on casters: four corner posts 0.045 square, top and bottom panels 0.035 thick, a closed back panel, side panels each with two recessed vent fields of horizontal slots |
| Rails | frame | two front mounting rails 0.018 x 0.04, just inside the posts, the full inner height, with a row of square holes every 1U |
| Casters | frame | four, each a 0.07 wheel on a swivel fork under a mounting plate |
| Cable bundle | frame | a bundle of three cables down the left inside the rails, into the switch's ports |
| Patch panel and switch | switch | two 1U units at the top: 24 keystone ports on the patch panel, 24 ports and 4 uplink cages on the switch, status lights |
| Equipment depth | (each) | chassis 0.45 deep behind its faceplate |
| Cluster nodes | nodes | three 1U servers below a 1U gap, each with four drive trays, a vent grille and a power button |
| GPU server | gpu | one 4U server with three 0.12 fans behind round grilles (hub and seven blades each), a vent strip |
| Storage | storage | one 3U chassis with three rows of six drive trays, each tray with a handle and a light |
| UPS shelf | ups | one 2U rack UPS near the bottom: a small display, three buttons, a vent grille |

Left between the units: 1U blanking gaps, so each part is its own block when
it slides out.
