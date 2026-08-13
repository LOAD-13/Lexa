"""Arranque sin consola para desarrollo (se abre con pythonw.exe)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import main

if __name__ == "__main__":
    sys.exit(main())
