import sys
from pathlib import Path

# Allow `import config`, `import quality`, etc. when pytest is run from the
# project root (adds the repo root to sys.path once, for the whole session).
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def report_font(size: int = 28):
    """A TrueType font for rendering synthetic OCR test images — PIL's
    default bitmap font is tiny and OCRs poorly (tesseract misreads
    "Assam" as "sam"), so a real font at a reasonable size is what makes
    these tests representative of an actual scanned/printed report.

    Tries macOS system fonts first, then the common Linux path (CI installs
    `fonts-dejavu-core`, see .github/workflows/ci.yml) — this ran green
    locally on macOS but failed on GitHub's Ubuntu runners with
    "OSError: cannot open resource" until this list included a Linux path,
    which is exactly the kind of environment-specific assumption CI exists
    to catch.
    """
    from PIL import ImageFont

    for candidate in (
        "/System/Library/Fonts/Supplemental/Courier New.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()
