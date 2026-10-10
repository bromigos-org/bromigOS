#!/usr/bin/env python3
"""Write the current theme's colours to mehshell. Optional args: palette.json config."""
import sys
from pathlib import Path
sys.path.insert(0, "/usr/lib/bromigos/lib")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from bromigos_prompt import update
if __name__ == "__main__":
    update(*sys.argv[1:])
