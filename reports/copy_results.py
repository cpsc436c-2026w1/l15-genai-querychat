"""Copy ../results into reports/results so the rendered pages can link the raw files."""
import shutil
from pathlib import Path

here = Path(__file__).resolve().parent
dst = here / "results"
shutil.rmtree(dst, ignore_errors=True)
shutil.copytree(here.parent / "results", dst)
