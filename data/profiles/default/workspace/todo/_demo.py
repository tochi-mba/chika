"""Real-usage demo: add 3 tasks, list, mark one done, remove another, confirm state."""
import json
import subprocess
import sys
from pathlib import Path

TODO = [sys.executable, str(Path(__file__).parent / "main.py")]

# Wipe any existing tasks.json so we start clean
tasks_file = Path(__file__).parent / "tasks.json"
tasks_file.unlink(missing_ok=True)


def run(*args):
    r = subprocess.run(TODO + list(args), capture_output=True, text=True)
    out = r.stdout.strip()
    err = r.stderr.strip()
    if out:
        print(out)
    if err:
        print("STDERR:", err)
    return r


print("=== add 3 tasks ===")
run("add", "Buy groceries")
run("add", "Write unit tests")
run("add", "Deploy to production")

print()
print("=== list all ===")
run("list")

print()
print("=== mark #2 done ===")
run("done", "2")

print()
print("=== remove #3 ===")
run("remove", "3")

print()
print("=== final list ===")
run("list")

print()
print("=== raw tasks.json ===")
print(tasks_file.read_text())

print()
print("=== assertions ===")
data = json.loads(tasks_file.read_text())
assert len(data) == 2, f"Expected 2 tasks, got {len(data)}"
assert data[0]["id"] == 1 and data[0]["title"] == "Buy groceries" and data[0]["done"] is False
assert data[1]["id"] == 2 and data[1]["title"] == "Write unit tests" and data[1]["done"] is True
print("All assertions passed:")
print("  - 2 tasks remain (task #3 removed)")
print("  - #1 Buy groceries: not done")
print("  - #2 Write unit tests: done")
