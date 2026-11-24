"""Source-mode entry for the same packaged read-only research query commands."""
from pathlib import Path
import sys


def main() -> int:
    """Input: local command-line tokens. Output: query JSON and exit code; never authenticate or start research."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from wqb.retrieval_research_planning import main as query_main
    return query_main()


if __name__ == '__main__':
    raise SystemExit(main())
