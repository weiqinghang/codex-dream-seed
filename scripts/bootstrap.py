from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from codex_dream.bootstrap import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
