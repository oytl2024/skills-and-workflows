"""PyInstaller entry; modes are parsed by the product, never by a shell."""
import multiprocessing
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wqb.desktop_application import main


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
