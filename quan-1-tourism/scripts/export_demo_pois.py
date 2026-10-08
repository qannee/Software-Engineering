"""Export the backend's curated demo POIs for the frontend offline fallback."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.repositories.poi_repository import POIRepository  # noqa: E402

output = ROOT / "frontend" / "src" / "data" / "demoPois.json"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(
    json.dumps(POIRepository.demo_data(), ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(f"Wrote {len(POIRepository.demo_data())} demo POIs to {output}")
