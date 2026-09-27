"""Import the pure model modules without importing Home Assistant."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "adaptive_climate_control"))
