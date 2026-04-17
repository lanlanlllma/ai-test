"""
Tetromino Puzzle Solver
=======================
Uses Depth-First Search (DFS) + Backtracking to fill a rectangular grid
with tetromino pieces.

Algorithm
---------
1. **"First empty cell" ordering** – always try to cover the top-left-most
   empty cell.  For each rotation the piece cell that is in the topmost row
   and, within that row, the leftmost column is designated the *anchor cell*.
   That cell is aligned with the first empty cell.  Because every cell above
   and to the left of the first empty cell is already filled, no other cell of
   the piece could legally occupy that position, making this ordering
   exhaustive and duplicate-free.

2. **Flood-fill region pruning** – after each placement check every connected
   empty region.  If any region's size is not a multiple of 4 the branch is a
   dead end; backtrack immediately.

3. **Checkerboard parity pruning** – T-tetrominoes are the only shape that
   covers an unequal number of black and white checkerboard cells (3 of one
   colour, 1 of the other; a contribution of ±2 to the black-minus-white
   balance per placement).  If the remaining T-piece count can never restore
   balance to 0, backtrack.

Usage
-----
    python solver.py              # solve the default 4×10 demo puzzle
    python solver.py --full       # attempt the 14×10 / 5-of-each puzzle
                                  # (parity pruning shows "No solution" fast)
    python solver.py --all        # enumerate all solutions to the demo puzzle
    python solver.py --test       # run built-in unit tests
"""

from __future__ import annotations

import sys
import time
from collections import deque
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# 1. Piece definitions (19 distinct rotations across 7 tetromino types)
# ---------------------------------------------------------------------------

_RAW_PIECES: dict[str, List[List[Tuple[int, int]]]] = {
    # ████  I-shape
    "I": [
        [(0, 0), (0, 1), (0, 2), (0, 3)],
        [(0, 0), (1, 0), (2, 0), (3, 0)],
    ],
    # ██
    # ██   O-shape
    "O": [
        [(0, 0), (0, 1), (1, 0), (1, 1)],
    ],
    # ███
    #  █   T-shape  (only piece with 3+1 checkerboard parity)
    "T": [
        [(0, 0), (0, 1), (0, 2), (1, 1)],
        [(0, 0), (1, 0), (1, 1), (2, 0)],
        [(0, 1), (1, 0), (1, 1), (1, 2)],
        [(0, 1), (1, 0), (1, 1), (2, 1)],
    ],
    #  ██
    # ██   S-shape
    "S": [
        [(0, 1), (0, 2), (1, 0), (1, 1)],
        [(0, 0), (1, 0), (1, 1), (2, 1)],
    ],
    # ██
    #  ██  Z-shape
    "Z": [
        [(0, 0), (0, 1), (1, 1), (1, 2)],
        [(0, 1), (1, 0), (1, 1), (2, 0)],
    ],
    # █
    # ███  L-shape
    "L": [
        [(0, 0), (1, 0), (2, 0), (2, 1)],
        [(0, 0), (0, 1), (0, 2), (1, 0)],
        [(0, 0), (0, 1), (1, 1), (2, 1)],
        [(0, 2), (1, 0), (1, 1), (1, 2)],
    ],
    #   █
    # ███  J-shape
    "J": [
        [(0, 1), (1, 1), (2, 0), (2, 1)],
        [(0, 0), (0, 1), (0, 2), (1, 2)],
        [(0, 0), (0, 1), (1, 0), (2, 0)],
        [(0, 0), (1, 0), (1, 1), (1, 2)],
    ],
}

# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _normalise(cells: List[Tuple[int, int]]) -> Tuple[Tuple[int, int], ...]:
    """Translate so min_row = min_col = 0, then sort."""
    min_r = min(r for r, _ in cells)
    min_c = min(c for _, c in cells)
    return tuple(sorted((r - min_r, c - min_c) for r, c in cells))


def _all_rotations(cells: List[Tuple[int, int]]) -> List[Tuple[Tuple[int, int], ...]]:
    """All unique 90°-rotation forms of *cells* (normalised, deduplicated)."""
    seen: set[Tuple[Tuple[int, int], ...]] = set()
    result: List[Tuple[Tuple[int, int], ...]] = []
    current = list(cells)
    for _ in range(4):
        norm = _normalise(current)
        if norm not in seen:
            seen.add(norm)
            result.append(norm)
        # 90° clockwise: (r, c) → (c, -r)
        current = [(c, -r) for r, c in current]
    return result


# Final PIECES table: name → deduplicated rotation tuples.
PIECES: dict[str, List[Tuple[Tuple[int, int], ...]]] = {}
for _name, _rots in _RAW_PIECES.items():
    _seen: set[Tuple[Tuple[int, int], ...]] = set()
    _unique: List[Tuple[Tuple[int, int], ...]] = []
    for _rot in _rots:
        for _derived in _all_rotations(_rot):
            if _derived not in _seen:
                _seen.add(_derived)
                _unique.append(_derived)
    PIECES[_name] = _unique

# ---------------------------------------------------------------------------
# 2. Anchor offset per rotation
# ---------------------------------------------------------------------------
# The *anchor cell* of a shape is its topmost-then-leftmost cell.
# We align this cell with the first empty cell during search, guaranteeing
# that cell is always covered and there is no redundancy.

def _anchor_offset(shape: Tuple[Tuple[int, int], ...]) -> Tuple[int, int]:
    min_dr = min(dr for dr, _ in shape)
    min_dc = min(dc for dr, dc in shape if dr == min_dr)
    return (min_dr, min_dc)


PIECE_ANCHORS: dict[str, List[Tuple[int, int]]] = {
    name: [_anchor_offset(shape) for shape in rots]
    for name, rots in PIECES.items()
}

# ---------------------------------------------------------------------------
# 3. Default puzzle configurations
# ---------------------------------------------------------------------------

# The problem description specifies a 14×10 grid with 5 copies of each of
# the 7 standard tetrominoes (35 pieces × 4 cells = 140 cells).
#
# NOTE: this configuration has NO solution.  T-tetrominoes are the only
# shape that covers an unequal number of black/white checkerboard cells
# (3 of one colour + 1 of the other; a ±2 change to the balance per piece).
# With an ODD number of T-pieces (5) the balance can never be restored to 0
# after placing all pieces; a solution is therefore impossible.
# The parity pruning below catches this at the root (before any placement).
#
# A solvable alternative: use an EVEN number of T-pieces (or 0).
# DEFAULT_CONFIG below uses a 4×10 grid with no T-pieces so the solver can
# demonstrate finding a real solution quickly.  Pass --full to attempt the
# original 14×10 / 5-of-each spec.

FULL_ROWS = 14
FULL_COLS = 10
FULL_PIECE_COUNTS: dict[str, int] = {name: 5 for name in PIECES}

# 4×10 = 40 cells.  All pieces are 2+2 parity → balanced by design.
DEMO_ROWS = 4
DEMO_COLS = 10
DEMO_PIECE_COUNTS: dict[str, int] = {
    "I": 2, "O": 2, "S": 2, "Z": 2, "L": 1, "J": 1, "T": 0,
}
# 2+2+2+2+1+1+0 = 10 pieces × 4 = 40 cells ✓
# all non-T → all 2+2 → 10×4=40=20+20 balanced ✓

# Runtime-selectable config (modified by CLI flags).
ROWS: int = DEMO_ROWS
COLS: int = DEMO_COLS
PIECE_COUNTS: dict[str, int] = dict(DEMO_PIECE_COUNTS)

# ---------------------------------------------------------------------------
# 4. Grid helpers
# ---------------------------------------------------------------------------

Grid = List[List[int]]   # 0 = empty; positive int = piece-type label

_PIECE_LABELS: dict[str, int] = {
    name: idx + 1 for idx, name in enumerate(sorted(PIECES))
}


def empty_grid() -> Grid:
    return [[0] * COLS for _ in range(ROWS)]


def find_first_empty(grid: Grid) -> Optional[Tuple[int, int]]:
    for r in range(ROWS):
        for c in range(COLS):
            if grid[r][c] == 0:
                return (r, c)
    return None


def can_place(
    grid: Grid,
    shape: Tuple[Tuple[int, int], ...],
    anchor_r: int,
    anchor_c: int,
) -> bool:
    """True iff placing *shape* with its (0,0) offset at (anchor_r, anchor_c)
    keeps all cells in-bounds and empty."""
    for dr, dc in shape:
        nr, nc = anchor_r + dr, anchor_c + dc
        if nr < 0 or nr >= ROWS or nc < 0 or nc >= COLS:
            return False
        if grid[nr][nc] != 0:
            return False
    return True


def place(
    grid: Grid,
    shape: Tuple[Tuple[int, int], ...],
    anchor_r: int,
    anchor_c: int,
    label: int,
) -> None:
    for dr, dc in shape:
        grid[anchor_r + dr][anchor_c + dc] = label


def unplace(
    grid: Grid,
    shape: Tuple[Tuple[int, int], ...],
    anchor_r: int,
    anchor_c: int,
) -> None:
    for dr, dc in shape:
        grid[anchor_r + dr][anchor_c + dc] = 0


# ---------------------------------------------------------------------------
# 5. Pruning
# ---------------------------------------------------------------------------

def _flood_fill_sizes(grid: Grid) -> List[int]:
    """Size of each 4-connected empty region."""
    visited = [[False] * COLS for _ in range(ROWS)]
    sizes: List[int] = []
    for r in range(ROWS):
        for c in range(COLS):
            if grid[r][c] == 0 and not visited[r][c]:
                size = 0
                q: deque[Tuple[int, int]] = deque([(r, c)])
                visited[r][c] = True
                while q:
                    cr, cc = q.popleft()
                    size += 1
                    for dr2, dc2 in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        nr, nc = cr + dr2, cc + dc2
                        if (
                            0 <= nr < ROWS
                            and 0 <= nc < COLS
                            and not visited[nr][nc]
                            and grid[nr][nc] == 0
                        ):
                            visited[nr][nc] = True
                            q.append((nr, nc))
                sizes.append(size)
    return sizes


def prune_by_region(grid: Grid) -> bool:
    """True iff some empty region has size not divisible by 4."""
    for size in _flood_fill_sizes(grid):
        if size % 4 != 0:
            return True
    return False


def prune_by_parity(grid: Grid, counts: "Counts") -> bool:
    """True iff the T-piece checkerboard parity rules out a solution.

    T-pieces are the only tetrominoes that cover 3 cells of one checkerboard
    colour and 1 of the other (+2 or −2 change to the black-minus-white
    balance).  With *t* T-pieces remaining, the achievable total balance
    changes are {−2t, −2t+4, …, +2t−4, +2t}.  If the required change to
    bring the current imbalance to 0 is not in that set, prune.
    """
    t = counts.get("T", 0)
    if t == 0:
        return False  # No T-pieces; parity cannot go wrong.

    black = sum(
        1 for r in range(ROWS) for c in range(COLS)
        if grid[r][c] == 0 and (r + c) % 2 == 0
    )
    white = sum(
        1 for r in range(ROWS) for c in range(COLS)
        if grid[r][c] == 0 and (r + c) % 2 == 1
    )
    balance = black - white   # target: 0
    needed = -balance         # required net change from remaining T-pieces

    # Check range and residue.
    if abs(needed) > 2 * t:
        return True
    if (needed + 2 * t) % 4 != 0:
        return True
    return False


# ---------------------------------------------------------------------------
# 6. DFS solver
# ---------------------------------------------------------------------------

Counts = dict[str, int]
PlacedList = List[Tuple[str, int, int, int]]   # (name, rot_idx, adj_r, adj_c)


def solve(grid: Grid, counts: Counts, placed: PlacedList) -> bool:
    """DFS with backtracking.

    Returns True and populates *placed* when a complete solution is found.
    """
    # Parity check at every node (fast: O(ROWS*COLS)).
    if prune_by_parity(grid, counts):
        return False

    pos = find_first_empty(grid)
    if pos is None:
        return True  # all cells filled → solution!

    anchor_r, anchor_c = pos

    for name, rotations in PIECES.items():
        if counts[name] == 0:
            continue
        anchors = PIECE_ANCHORS[name]
        for rot_idx, shape in enumerate(rotations):
            off_r, off_c = anchors[rot_idx]
            # Align anchor cell of this rotation with the first empty cell.
            adj_r = anchor_r - off_r
            adj_c = anchor_c - off_c

            if can_place(grid, shape, adj_r, adj_c):
                label = _PIECE_LABELS[name]
                place(grid, shape, adj_r, adj_c, label)

                if not prune_by_region(grid):
                    counts[name] -= 1
                    placed.append((name, rot_idx, adj_r, adj_c))

                    if solve(grid, counts, placed):
                        return True

                    placed.pop()
                    counts[name] += 1

                unplace(grid, shape, adj_r, adj_c)

    return False


# ---------------------------------------------------------------------------
# 7. Validation and display
# ---------------------------------------------------------------------------

def validate_solution(grid: Grid, counts: Counts) -> bool:
    """True iff every cell is filled and all piece counts are zero."""
    for r in range(ROWS):
        for c in range(COLS):
            if grid[r][c] == 0:
                return False
    return all(v == 0 for v in counts.values())


_LABEL_TO_CHAR: dict[int, str] = {v: k for k, v in _PIECE_LABELS.items()}

# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
# Rules:
#   • Base score  : +10 points for every completely filled row.
#   • Bonus score : +10 extra points for each filled row that contains
#                   4 or more distinct tetromino piece types (colours).
#
# A "filled" row is one where every cell holds a non-zero label.
# In the solver a completely filled grid is the goal, but the scoring
# functions also work on partially filled intermediate grids (useful for
# evaluating heuristic moves or partial placements).

POINTS_PER_ROW = 10
BONUS_POINTS_PER_ROW = 10
BONUS_COLOUR_THRESHOLD = 4


def score_breakdown(grid: Grid) -> List[dict]:
    """Return per-row scoring details for every filled row in *grid*.

    Each entry is a dict with:
        row      – row index
        colours  – number of distinct piece types in that row
        base     – base points (always POINTS_PER_ROW for filled rows)
        bonus    – bonus points (BONUS_POINTS_PER_ROW if colours >= threshold)
        total    – base + bonus
    """
    result: List[dict] = []
    for r in range(ROWS):
        row = grid[r]
        # Skip incomplete rows.
        if any(cell == 0 for cell in row):
            continue
        colours = len(set(row))
        bonus = BONUS_POINTS_PER_ROW if colours >= BONUS_COLOUR_THRESHOLD else 0
        result.append({
            "row": r,
            "colours": colours,
            "base": POINTS_PER_ROW,
            "bonus": bonus,
            "total": POINTS_PER_ROW + bonus,
        })
    return result


def score_grid(grid: Grid) -> int:
    """Return the total score for *grid* according to the scoring rules."""
    return sum(entry["total"] for entry in score_breakdown(grid))


def print_score(grid: Grid) -> None:
    """Print a per-row scoring table and the grand total."""
    breakdown = score_breakdown(grid)
    if not breakdown:
        print("Score: 0  (no filled rows)")
        return

    header = f"{'Row':>4}  {'Colours':>7}  {'Base':>4}  {'Bonus':>5}  {'Total':>5}"
    sep = "-" * len(header)
    print(header)
    print(sep)
    for entry in breakdown:
        bonus_str = f"+{entry['bonus']}" if entry["bonus"] else "  —"
        print(
            f"{entry['row']:>4}  {entry['colours']:>7}  "
            f"{entry['base']:>4}  {bonus_str:>5}  {entry['total']:>5}"
        )
    print(sep)
    total = sum(e["total"] for e in breakdown)
    print(f"{'Total':>4}  {'':>7}  {'':>4}  {'':>5}  {total:>5}")


def print_grid(grid: Grid) -> None:
    border = "+" + "-" * (COLS * 2 - 1) + "+"
    print(border)
    for row in grid:
        print("|" + " ".join(
            _LABEL_TO_CHAR.get(c, ".") if c != 0 else "." for c in row
        ) + "|")
    print(border)


# ---------------------------------------------------------------------------
# 8. Built-in unit tests
# ---------------------------------------------------------------------------

def _run_tests() -> None:
    failures: List[str] = []

    def ok(desc: str, value: bool) -> None:
        if not value:
            failures.append(f"FAIL [{desc}]")
        else:
            print(f"  OK  [{desc}]")

    def eq(desc: str, actual, expected) -> None:
        ok(f"{desc}: got {actual!r}, want {expected!r}", actual == expected)

    print("=== Running unit tests ===\n")

    # 1 – normalise
    eq("normalise O", _normalise([(2, 3), (2, 4), (3, 3), (3, 4)]),
       ((0, 0), (0, 1), (1, 0), (1, 1)))

    # 2 – rotation counts
    eq("I rotations == 2", len(PIECES["I"]), 2)
    eq("O rotations == 1", len(PIECES["O"]), 1)
    eq("T rotations == 4", len(PIECES["T"]), 4)
    eq("PIECES has 7 types", len(PIECES), 7)
    eq("total rotations == 19", sum(len(v) for v in PIECES.values()), 19)

    # 3 – anchor invariants
    ok("every anchor cell is IN its shape", all(
        PIECE_ANCHORS[n][i] in shape
        for n, rots in PIECES.items()
        for i, shape in enumerate(rots)
    ))
    ok("anchor is topmost-then-leftmost", all(
        PIECE_ANCHORS[n][i] == (
            (lambda s: (
                min(dr for dr, _ in s),
                min(dc for dr, dc in s if dr == min(dr2 for dr2, _ in s))
            ))(shape)
        )
        for n, rots in PIECES.items()
        for i, shape in enumerate(rots)
    ))

    # 4 – S-piece horizontal anchor is (0,1)
    s_h = PIECES["S"][0]
    eq("S-horizontal shape[0]", s_h[0], (0, 1))
    eq("S-horizontal anchor", PIECE_ANCHORS["S"][0], (0, 1))

    # 5 – placing S-horizontal so anchor covers cell (2,3)
    # Temporarily use a 10×10 grid for this geometry test.
    global ROWS, COLS
    _save_rows, _save_cols = ROWS, COLS
    ROWS, COLS = 10, 10
    g7 = [[0] * 10 for _ in range(10)]
    off_r, off_c = PIECE_ANCHORS["S"][0]
    adj_r, adj_c = 2 - off_r, 3 - off_c
    place(g7, s_h, adj_r, adj_c, _PIECE_LABELS["S"])
    eq("S-horizontal covers anchor (2,3)", g7[2][3], _PIECE_LABELS["S"])
    ROWS, COLS = _save_rows, _save_cols

    # 6 – can_place / place / unplace
    g = empty_grid()
    shape_O = PIECES["O"][0]
    ok("can_place O at (0,0)", can_place(g, shape_O, 0, 0))
    ok("can_place O at top-right corner is False",
       not can_place(g, shape_O, 0, COLS - 1))
    g2 = empty_grid()
    place(g2, shape_O, 0, 0, 1)
    eq("place O sets (0,0)", g2[0][0], 1)
    eq("place O sets (0,1)", g2[0][1], 1)
    unplace(g2, shape_O, 0, 0)
    eq("unplace O clears (0,0)", g2[0][0], 0)

    # 7 – flood fill
    g3 = empty_grid()
    sizes = _flood_fill_sizes(g3)
    eq("empty grid: 1 region", len(sizes), 1)
    eq("empty grid: region size = ROWS*COLS", sizes[0], ROWS * COLS)

    # 8 – prune_by_region detects 2-cell isolated pocket
    g4 = empty_grid()
    for c in range(COLS):
        g4[0][c] = 1
    for c in range(COLS):
        g4[1][c] = 1
    g4[1][4] = 0
    g4[1][5] = 0
    for c in range(COLS):
        g4[2][c] = 1
    ok("prune detects isolated 2-cell region", prune_by_region(g4))

    # 9 – parity pruning: 5 T-pieces → unsolvable at balance 0
    counts9: Counts = {name: 0 for name in PIECES}
    counts9["T"] = 5
    g9 = [[0] * COLS for _ in range(ROWS)]
    ok("parity prune: 5 T at balance 0 → prune", prune_by_parity(g9, counts9))

    # 10 – parity pruning: 4 T-pieces → OK at balance 0
    counts10: Counts = {name: 0 for name in PIECES}
    counts10["T"] = 4
    ok("parity prune: 4 T at balance 0 → no prune",
       not prune_by_parity(g9, counts10))

    # 11 – validate_solution fails on empty grid
    counts11: Counts = {name: 5 for name in PIECES}
    ok("validate_solution fails on empty grid",
       not validate_solution(g, counts11))

    # 12 – solve actually finds a solution for the demo config
    ROWS, COLS = DEMO_ROWS, DEMO_COLS
    g_demo = [[0] * DEMO_COLS for _ in range(DEMO_ROWS)]
    counts_demo = dict(DEMO_PIECE_COUNTS)
    placed_demo: PlacedList = []
    found = solve(g_demo, counts_demo, placed_demo)
    ok("solve finds demo solution", found)
    if found:
        ok("demo solution is valid", validate_solution(g_demo, counts_demo))
    ROWS, COLS = _save_rows, _save_cols

    # 13 – score_grid: empty grid scores 0
    g_empty = [[0] * COLS for _ in range(ROWS)]
    eq("score empty grid == 0", score_grid(g_empty), 0)
    eq("score_breakdown empty grid == []", score_breakdown(g_empty), [])

    # 14 – score_grid: one fully filled row, 2 distinct types → 10 pts (no bonus)
    g_s1 = [[0] * COLS for _ in range(ROWS)]
    # Fill row 0: first 5 cells = label 1, next 5 = label 2 (2 colours < 4)
    for c in range(5):
        g_s1[0][c] = 1
    for c in range(5, COLS):
        g_s1[0][c] = 2
    bd1 = score_breakdown(g_s1)
    eq("1 filled row (2 colours): 1 entry", len(bd1), 1)
    eq("1 filled row (2 colours): no bonus", bd1[0]["bonus"], 0)
    eq("1 filled row (2 colours): total 10", bd1[0]["total"], 10)
    eq("score 1 filled row (2 colours) == 10", score_grid(g_s1), 10)

    # 15 – score_grid: one fully filled row, 4 distinct types → 20 pts (bonus)
    g_s2 = [[0] * COLS for _ in range(ROWS)]
    # Fill row 0 with 4 different labels (COLS=10: labels 1,1,1,2,2,3,3,4,4,4)
    for c, lbl in enumerate([1, 1, 1, 2, 2, 3, 3, 4, 4, 4][:COLS]):
        g_s2[0][c] = lbl
    bd2 = score_breakdown(g_s2)
    eq("1 filled row (4 colours): bonus == 10", bd2[0]["bonus"], 10)
    eq("1 filled row (4 colours): total 20", bd2[0]["total"], 20)
    eq("score 1 filled row (4 colours) == 20", score_grid(g_s2), 20)

    # 16 – score_grid: demo solution scores at least 10 pts per row
    if found:
        demo_score = score_grid(g_demo)
        ok(f"demo solution score >= {DEMO_ROWS * POINTS_PER_ROW}",
           demo_score >= DEMO_ROWS * POINTS_PER_ROW)

    print()
    if failures:
        for f in failures:
            print(f)
        sys.exit(1)
    else:
        print(f"All 30 tests passed.")


# ---------------------------------------------------------------------------
# 9. Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    global ROWS, COLS, PIECE_COUNTS

    args = sys.argv[1:]

    if "--test" in args:
        _run_tests()
        return

    use_full = "--full" in args
    find_all = "--all" in args

    if use_full:
        ROWS = FULL_ROWS
        COLS = FULL_COLS
        PIECE_COUNTS.update(FULL_PIECE_COUNTS)
        print(
            "NOTE: 14×10 with 5 of each tetromino type is PROVABLY UNSOLVABLE\n"
            "      (T-piece checkerboard parity: with an odd number of T-pieces\n"
            "       the equation 4k = 10 has no integer solution, so the\n"
            "       black/white balance can never be restored to 0).\n"
            "      Parity pruning will return 'No solution' immediately.\n"
        )
    else:
        ROWS = DEMO_ROWS
        COLS = DEMO_COLS
        PIECE_COUNTS.update(DEMO_PIECE_COUNTS)

    grid = empty_grid()
    counts: Counts = dict(PIECE_COUNTS)
    placed: PlacedList = []

    used = {k: v for k, v in sorted(counts.items()) if v > 0}
    print(f"Solving {ROWS}×{COLS} tetromino puzzle …")
    print(f"Pieces: {used}")
    print()

    t0 = time.perf_counter()

    if find_all:
        solution_count = 0
        best_score = -1
        best_grid: Optional[Grid] = None

        def _solve_all(grid: Grid, counts: Counts, placed: PlacedList) -> None:
            nonlocal solution_count, best_score, best_grid
            if prune_by_parity(grid, counts):
                return
            pos = find_first_empty(grid)
            if pos is None:
                solution_count += 1
                s = score_grid(grid)
                print(f"\n--- Solution #{solution_count}  (score: {s}) ---")
                print_grid(grid)
                print_score(grid)
                if s > best_score:
                    best_score = s
                    best_grid = [row[:] for row in grid]
                return
            anchor_r, anchor_c = pos
            for name, rotations in PIECES.items():
                if counts[name] == 0:
                    continue
                for rot_idx, shape in enumerate(rotations):
                    off_r, off_c = PIECE_ANCHORS[name][rot_idx]
                    adj_r = anchor_r - off_r
                    adj_c = anchor_c - off_c
                    if can_place(grid, shape, adj_r, adj_c):
                        label = _PIECE_LABELS[name]
                        place(grid, shape, adj_r, adj_c, label)
                        if not prune_by_region(grid):
                            counts[name] -= 1
                            placed.append((name, rot_idx, adj_r, adj_c))
                            _solve_all(grid, counts, placed)
                            placed.pop()
                            counts[name] += 1
                        unplace(grid, shape, adj_r, adj_c)

        _solve_all(grid, counts, placed)
        elapsed = time.perf_counter() - t0
        print(f"\nFound {solution_count} solution(s) in {elapsed:.3f}s")
        if best_grid is not None:
            print(f"\nBest score: {best_score}")
            print("Best scoring grid:")
            print_grid(best_grid)

    else:
        found = solve(grid, counts, placed)
        elapsed = time.perf_counter() - t0

        if found:
            print("Solution found!\n")
            print_grid(grid)
            print()
            print("Placement log:")
            for step, (name, rot_idx, r, c) in enumerate(placed, 1):
                shape = PIECES[name][rot_idx]
                cells = [(r + dr, c + dc) for dr, dc in shape]
                print(
                    f"  {step:2d}. piece={name}  rotation={rot_idx}"
                    f"  anchor=({r},{c})  cells={cells}"
                )
            print()
            assert validate_solution(grid, counts), "BUG: validation failed!"
            print(f"Validation: PASSED  (elapsed: {elapsed:.3f}s)")
            print()
            print("Scoring:")
            print_score(grid)
            print(f"\nFinal score: {score_grid(grid)}")
        else:
            print("No solution found.")
            print(f"Elapsed: {elapsed:.3f}s")


if __name__ == "__main__":
    main()
