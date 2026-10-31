"""Compatibility entry: the former research viewer now opens basic charts only."""
from pathlib import Path
import runpy,sys
if __name__=="__main__":
    target=Path(__file__).resolve().parents[2]/"hushen_kline_viewer"/"launch.py"
    sys.argv=[str(target)]+(["--no-browser"] if "--no-browser" in sys.argv else [])
    runpy.run_path(str(target),run_name="__main__")
