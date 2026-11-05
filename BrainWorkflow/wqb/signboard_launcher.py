"""Disabled legacy board entry, pending audited removal."""

import sys


def main() -> int:
    """Input: none. Output: int exit status; reject the retired board without side effects."""
    print("The project board is retired. Use BrainWorkflow.vbs for research; "
          "read root milestone.md and todo.md for architecture and maintenance.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
