"""Print how many tests the suite collects (used in the README, checked in CI)."""
import re
import subprocess
import sys

_COUNT = re.compile(r"(\d+)(?:/\d+)? tests? collected")


def parse_count(text: str) -> int | None:
    m = _COUNT.search(text)
    return int(m.group(1)) if m else None


def collected() -> int:
    proc = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
                          capture_output=True, text=True)
    n = parse_count(proc.stdout)
    if n is None:
        sys.exit(f"could not count tests\n{proc.stdout}{proc.stderr}")
    return n


if __name__ == "__main__":
    print(f"{collected()} tests collected")
