# -*- coding: utf-8 -*-
import time
import random
import sys
import io

# Force UTF-8 output so Unicode chars render on all terminals
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# -----------------------------------------------
# O(n)  -- Linear time
# Loop through each element exactly once.
# Work grows proportionally with input size.
# -----------------------------------------------
def find_max_linear(arr):
    """O(n): single pass to find the maximum value."""
    current_max = arr[0]
    for item in arr:
        if item > current_max:
            current_max = item
    return current_max


# -----------------------------------------------
# O(n^2) -- Quadratic time
# Nested loops: for every element, loop again.
# Work grows as the SQUARE of input size.
# -----------------------------------------------
def bubble_sort_quadratic(arr):
    """O(n^2): classic bubble sort -- nested loops."""
    arr = arr.copy()          # don't mutate original
    n = len(arr)
    for i in range(n):
        for j in range(0, n - i - 1):
            if arr[j] > arr[j + 1]:
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
    return arr


def benchmark(sizes):
    print(f"{'Size':>8}  {'O(n) ms':>12}  {'O(n^2) ms':>12}  {'Ratio':>10}")
    print("-" * 50)

    for n in sizes:
        data = [random.randint(0, 1_000_000) for _ in range(n)]

        # --- O(n) timing ---
        t0 = time.perf_counter()
        find_max_linear(data)
        t_linear = (time.perf_counter() - t0) * 1000   # ms

        # --- O(n^2) timing ---
        t0 = time.perf_counter()
        bubble_sort_quadratic(data)
        t_quad = (time.perf_counter() - t0) * 1000     # ms

        ratio = f"{t_quad / t_linear:.1f}x" if t_linear > 0 else "N/A"
        print(f"{n:>8}  {t_linear:>12.4f}  {t_quad:>12.3f}  {ratio:>10}")


if __name__ == "__main__":
    print()
    print("=" * 50)
    print("  Big-O Timing Demo: O(n) vs O(n^2)")
    print("=" * 50)
    print()
    print("  O(n)   -> find_max_linear  : one loop, scans once")
    print("  O(n^2) -> bubble_sort      : nested loops")
    print()

    sizes = [500, 1_000, 2_000, 4_000, 8_000]
    benchmark(sizes)

    print()
    print("Key insight:")
    print("  Double n -> O(n) time ~doubles, O(n^2) time ~quadruples.")
    print("  That gap explodes as n grows -- that's why O(n^2) is")
    print("  avoided for large datasets.")
    print()
