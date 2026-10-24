"""Streamlit entry point; clean clone needs only requirements.txt, no editable install."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from fleetcare.ui import main

main()
