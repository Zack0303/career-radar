"""Module entrypoint for `python3 -m career_radar`."""

from __future__ import annotations

import sys

from career_radar.cli import main

if __name__ == "__main__":
    sys.exit(main())
