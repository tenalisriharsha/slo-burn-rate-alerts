"""Every local image referenced in README.md must exist on disk - a prior
session added the architecture diagram and 3 latency screenshots
(docs/screenshots/07-09) alongside the latency SLO feature, and
PROGRESS.md phase 4 added 3 more (docs/screenshots/10-12) alongside the
saturation SLO, so a typo'd path or a forgotten `git add` would otherwise
only surface as a broken image on GitHub.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"

IMAGE_REF = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _local_image_paths():
    paths = []
    for match in IMAGE_REF.finditer(README.read_text()):
        target = match.group(1)
        if not target.startswith("http://") and not target.startswith("https://"):
            paths.append(target)
    return paths


def test_readme_references_at_least_the_documented_images():
    paths = _local_image_paths()
    assert "docs/architecture.png" in paths
    assert any("latency" in p for p in paths)
    assert any("saturation" in p for p in paths)


def test_every_local_image_referenced_in_the_readme_exists():
    for relative_path in _local_image_paths():
        assert (REPO_ROOT / relative_path).is_file(), f"missing {relative_path}"
