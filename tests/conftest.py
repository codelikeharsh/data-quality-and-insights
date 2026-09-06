import sys
from pathlib import Path

# Allow `import config`, `import quality`, etc. when pytest is run from the
# project root (adds the repo root to sys.path once, for the whole session).
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
