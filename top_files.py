import os
import sys
from tabulate import tabulate

# Ensure stdout handles any character set
sys.stdout.reconfigure(encoding="utf-8")

ROOT = "chika/"

def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"

files = [
    (os.path.join(root, fname), os.path.getsize(os.path.join(root, fname)))
    for root, _, fnames in os.walk(ROOT)
    for fname in fnames
]

files.sort(key=lambda x: x[1], reverse=True)
top5 = files[:5]

rows = [
    [i + 1, path, human_size(size)]
    for i, (path, size) in enumerate(top5)
]

print(tabulate(
    rows,
    headers=["#", "File", "Size"],
    tablefmt="rounded_outline",
    colalign=("center", "left", "right"),
))
