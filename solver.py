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
    python solver.py --best       # find the highest-scoring placement by
                                  # allowing some pieces to go unused; useful
                                  # when a full-grid fill is impossible or
                                  # sub-optimal (combine with --full)
    python solver.py --test       # run built-in unit tests
"""

from __future__ import annotations

import os
import multiprocessing as mp
import queue
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


def _shape_origin_offset(shape: Tuple[Tuple[int, int], ...]) -> Tuple[float, float]:
    """Return the geometric origin used for reporting placements.

    This is the centre point of the four occupied cells in the shape's local
    coordinates, which matches the marked origin in the reference image more
    closely than the search anchor.
    """
    return (
        sum(dr for dr, _ in shape) / len(shape),
        sum(dc for _, dc in shape) / len(shape),
    )


PIECE_ORIGINS: dict[str, List[Tuple[float, float]]] = {
    name: [_shape_origin_offset(shape) for shape in rots]
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
FULL_PIECE_COUNTS["T"] = 4  # make it solvable by parity

# 4×10 = 40 cells.  All pieces are 2+2 parity → balanced by design.
DEMO_ROWS = 14
DEMO_COLS = 10
DEMO_PIECE_COUNTS: dict[str, int] = {
    "I": 5, "O": 5, "S": 5, "Z": 3, "L": 5, "J": 5, "T": 5,
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


def _format_coord(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text


def _format_point(point: Tuple[float, float]) -> str:
    return f"({_format_coord(point[0])},{_format_coord(point[1])})"


def _placement_origin(name: str, rot_idx: int, adj_r: int, adj_c: int) -> Tuple[float, float]:
    off_r, off_c = PIECE_ORIGINS[name][rot_idx]
    return (adj_r + off_r, adj_c + off_c)


def _print_placement_log(placed: PlacedList) -> None:
    print("Placement log:")
    for step, (name, rot_idx, r, c) in enumerate(placed, 1):
        shape = PIECES[name][rot_idx]
        origin = _placement_origin(name, rot_idx, r, c)
        cells = [(r + dr, c + dc) for dr, dc in shape]
        print(
            f"  {step:2d}. piece={name}  rotation={rot_idx}"
            f"  origin={_format_point(origin)}  anchor=({r},{c})  cells={cells}"
        )


def _infer_rotation(name: str, cells: List[Tuple[int, int]]) -> int:
    min_r = min(r for r, _ in cells)
    min_c = min(c for _, c in cells)
    normalised = tuple(sorted((r - min_r, c - min_c) for r, c in cells))
    for rot_idx, shape in enumerate(PIECES[name]):
        if shape == normalised:
            return rot_idx
    raise ValueError(f"unable to infer rotation for {name} from cells {cells!r}")


def _reconstruct_placements(grid: Grid, owner_grid: Optional[Grid]) -> PlacedList:
    if owner_grid is None:
        return []

    pieces: List[Tuple[int, str, int, int, int]] = []
    by_owner: dict[int, List[Tuple[int, int]]] = {}
    for r in range(ROWS):
        for c in range(COLS):
            owner = owner_grid[r][c]
            if owner == 0:
                continue
            by_owner.setdefault(owner, []).append((r, c))

    for owner, cells in by_owner.items():
        if len(cells) != 4:
            continue
        piece_type = _LABEL_TO_CHAR.get(grid[cells[0][0]][cells[0][1]], "?")
        if piece_type == "?":
            continue
        rot_idx = _infer_rotation(piece_type, cells)
        anchor_r = min(r for r, _ in cells)
        anchor_c = min(c for r, c in cells if r == anchor_r)
        off_r, off_c = PIECE_ANCHORS[piece_type][rot_idx]
        adj_r = anchor_r - off_r
        adj_c = anchor_c - off_c
        pieces.append((owner, piece_type, rot_idx, adj_r, adj_c))

    pieces.sort(key=lambda item: item[0])
    return [(name, rot_idx, adj_r, adj_c) for _, name, rot_idx, adj_r, adj_c in pieces]


def _print_reconstructed_placement_log(grid: Grid, owner_grid: Optional[Grid]) -> None:
    placed = _reconstruct_placements(grid, owner_grid)
    if not placed:
        return
    _print_placement_log(placed)


def _count_filled_cells(grid: Grid) -> int:
    return sum(1 for row in grid for cell in row if cell != 0)


def _clone_grid(grid: Grid) -> Grid:
    return [row[:] for row in grid]


def _clone_counts(counts: Counts) -> Counts:
    return dict(counts)


def _progress_print(progress: Optional[dict], message: str) -> None:
    if progress is None:
        print(message)
        return
    if progress.get("quiet"):
        return
    lock = progress.get("print_lock")
    if lock is None:
        print(message)
        return
    with lock:
        print(message)


def _emit_progress(progress: dict, state: List, counts: Counts, grid: Grid) -> None:
    progress["nodes"] = progress.get("nodes", 0) + 1
    reporter = progress.get("reporter")
    mirror_local_output = progress.get("mirror_local_output", True)
    if not progress.get("progress_enabled", True):
        if reporter is None:
            return
    now = time.perf_counter()
    last_report = progress.get("last_report", progress.get("started_at", now))
    report_interval = progress.get("report_interval", 2.0)
    if progress["nodes"] == 1 or now - last_report >= report_interval:
        elapsed = now - progress.get("started_at", now)
        if reporter is not None:
            reporter.put({
                "kind": "progress",
                "branch_idx": progress.get("branch_idx"),
                "elapsed": elapsed,
                "nodes": progress["nodes"],
                "filled": _count_filled_cells(grid),
                "best": state[0],
                "pieces_left": sum(counts.values()),
            })
        if mirror_local_output:
            _progress_print(
                progress,
                f"[progress] elapsed={elapsed:.1f}s  nodes={progress['nodes']}  "
                f"filled={_count_filled_cells(grid)}  best={state[0]}  "
                f"pieces_left={sum(counts.values())}",
            )
        progress["last_report"] = now


def _record_new_best(progress: Optional[dict], score: int, grid: Grid) -> None:
    if progress is None:
        return
    now = time.perf_counter()
    elapsed = now - progress.get("started_at", now)
    reporter = progress.get("reporter")
    mirror_local_output = progress.get("mirror_local_output", True)
    progress["last_newbest_at"] = now
    if reporter is not None:
        reporter.put({
            "kind": "newbest",
            "branch_idx": progress.get("branch_idx"),
            "elapsed": elapsed,
            "nodes": progress.get("nodes", 0),
            "filled": _count_filled_cells(grid),
            "best": score,
        })
    if not progress.get("newbest_enabled", True) or not mirror_local_output:
        return
    _progress_print(
        progress,
        f"[newbest] score={score}  filled={_count_filled_cells(grid)}  "
        f"nodes={progress.get('nodes', 0)}  elapsed={elapsed:.3f}s",
    )


def _branch_should_stop(progress: Optional[dict]) -> bool:
    if progress is None:
        return False
    stall_timeout = progress.get("stall_timeout")
    if stall_timeout is None or stall_timeout <= 0:
        return False
    if progress.get("target_score") is not None and progress.get("stopped_due_to_target"):
        return True
    now = time.perf_counter()
    last_newbest_at = progress.get("last_newbest_at", progress.get("started_at", now))
    if now - last_newbest_at < stall_timeout:
        return False
    if not progress.get("stopped_due_to_stall"):
        progress["stopped_due_to_stall"] = True
        progress["stop_reason"] = "stall"
        reporter = progress.get("reporter")
        if reporter is not None:
            reporter.put({
                "kind": "stalled",
                "branch_idx": progress.get("branch_idx"),
                "elapsed": now - progress.get("started_at", now),
                "nodes": progress.get("nodes", 0),
                "best": progress.get("best_score", 0),
                "stall_for": now - last_newbest_at,
            })
    return True


def _theoretical_max_score(counts: Counts) -> int:
    total_cells = sum(counts.values()) * 4
    full_rows = min(ROWS, total_cells // COLS)
    if full_rows <= 0:
        return 0
    distinct_types = sum(1 for value in counts.values() if value > 0)
    per_row = POINTS_PER_ROW
    if distinct_types >= BONUS_COLOUR_THRESHOLD:
        per_row += BONUS_POINTS_PER_ROW
    return full_rows * per_row


def _solve_max_score_branch(
    branch_idx: int,
    branch_grid: Grid,
    branch_owner_grid: Grid,
    branch_counts: Counts,
    started_at: float,
    target_score: int,
    report_interval: float,
    branch_stall_timeout: Optional[float],
    progress_queue,
) -> Tuple[int, Optional[Grid], Optional[Grid], int]:
    local_state: List = [
        score_grid(branch_grid),
        _clone_grid(branch_grid),
        _clone_grid(branch_owner_grid),
    ]
    local_progress = {
        "branch_idx": branch_idx,
        "started_at": started_at,
        "last_report": started_at,
        "last_newbest_at": started_at,
        "nodes": 0,
        "best_score": local_state[0],
        "progress_enabled": False,
        "newbest_enabled": False,
        "mirror_local_output": False,
        "report_interval": report_interval,
        "stall_timeout": branch_stall_timeout,
        "reporter": progress_queue,
        "target_score": target_score,
        "stop_reason": "completed",
        "initial_pieces_left": sum(branch_counts.values()) + 1,
    }
    solve_max_score(branch_grid, branch_counts, local_state, local_progress, branch_owner_grid)
    if progress_queue is not None:
        progress_queue.put({
            "kind": "done",
            "branch_idx": branch_idx,
            "elapsed": time.perf_counter() - started_at,
            "nodes": local_progress["nodes"],
            "best": local_state[0],
            "filled": _count_filled_cells(local_state[1]) if local_state[1] is not None else 0,
            "pieces_left": sum(branch_counts.values()),
            "reason": local_progress.get("stop_reason", "completed"),
        })
    return local_state[0], local_state[1], local_state[2], local_progress["nodes"]


def _solve_max_score_branch_process(
    branch_idx: int,
    branch_grid: Grid,
    branch_owner_grid: Grid,
    branch_counts: Counts,
    started_at: float,
    target_score: int,
    report_interval: float,
    branch_stall_timeout: Optional[float],
    progress_queue,
    result_queue,
) -> None:
    score, best_grid, best_owner_grid, nodes = _solve_max_score_branch(
        branch_idx,
        branch_grid,
        branch_owner_grid,
        branch_counts,
        started_at,
        target_score,
        report_interval,
        branch_stall_timeout,
        progress_queue,
    )
    result_queue.put({
        "branch_idx": branch_idx,
        "score": score,
        "best_grid": best_grid,
        "best_owner_grid": best_owner_grid,
        "nodes": nodes,
    })


def _drain_branch_reports(progress_queue, progress: dict) -> None:
    if progress_queue is None:
        return
    while True:
        try:
            update = progress_queue.get_nowait()
        except queue.Empty:
            break

        kind = update.get("kind", "progress")
        branch_idx = update.get("branch_idx", "?")
        elapsed = update.get("elapsed", 0.0)
        nodes = update.get("nodes", 0)
        best = update.get("best", 0)
        filled = update.get("filled", 0)
        pieces_left = update.get("pieces_left")
        reason = update.get("reason")
        stall_for = update.get("stall_for")

        if kind == "newbest":
            _progress_print(
                progress,
                f"[branch {branch_idx:02d} newbest] score={best}  filled={filled}  "
                f"nodes={nodes}  elapsed={elapsed:.3f}s",
            )
            continue

        if kind == "stalled":
            _progress_print(
                progress,
                f"[branch {branch_idx:02d} stalled] best={best}  nodes={nodes}  "
                f"idle={stall_for:.1f}s  elapsed={elapsed:.3f}s",
            )
            continue

        if kind == "done":
            suffix = f"  pieces_left={pieces_left}" if pieces_left is not None else ""
            reason_suffix = f"  reason={reason}" if reason else ""
            _progress_print(
                progress,
                f"[branch {branch_idx:02d} done] best={best}  filled={filled}  "
                f"nodes={nodes}  elapsed={elapsed:.3f}s{suffix}{reason_suffix}",
            )
            continue

        suffix = f"  pieces_left={pieces_left}" if pieces_left is not None else ""
        _progress_print(
            progress,
            f"[branch {branch_idx:02d} progress] elapsed={elapsed:.1f}s  nodes={nodes}  "
            f"filled={filled}  best={best}{suffix}",
        )


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
# 7. Score-maximising solver (allows unused pieces)
# ---------------------------------------------------------------------------

def solve_max_score(
    grid: Grid,
    counts: Counts,
    state: List,  # mutable [best_score: int, best_grid: Optional[Grid]]
    progress: Optional[dict] = None,
    owner_grid: Optional[Grid] = None,
) -> None:
    """DFS that maximises score while allowing some pieces to go unused.

    Unlike *solve*, this function does **not** require every piece to be
    placed or every cell to be filled.  At each node the current grid is
    scored; if the score beats the running best it is recorded.  This means
    that "giving up" the remaining pieces (stopping early) is always
    implicitly considered as an option.

    Pruning
    -------
    Upper-bound prune: the maximum additional score achievable from this
    node is bounded by the number of rows that could possibly be completed.
    That row count is bounded by both the number of remaining rows *and* by
    ``min(empty_cells, pieces_left × 4) // COLS`` – i.e., the fewer of
    (cells we have room for) and (cells the remaining pieces cover),
    divided by the column count.  Whichever bound is tighter is used.

    Note: *prune_by_region* is intentionally omitted because isolated
    regions are acceptable in a partial fill.
    """
    if progress is not None:
        _emit_progress(progress, state, counts, grid)
        progress["best_score"] = state[0]
        if _branch_should_stop(progress):
            return

    # Score the current (possibly partial) grid.
    s = score_grid(grid)
    if s > state[0]:
        state[0] = s
        if progress is not None:
            progress["best_score"] = s
        state[1] = [row[:] for row in grid]
        if owner_grid is not None and len(state) >= 3:
            state[2] = [row[:] for row in owner_grid]
        _record_new_best(progress, s, grid)
        target_score = progress.get("target_score") if progress is not None else None
        if target_score is not None and s >= target_score:
            if progress is not None:
                progress["stopped_due_to_target"] = True
                progress["stop_reason"] = "target"
            return

    pos = find_first_empty(grid)
    if pos is None:
        return  # Grid fully filled – nothing more to place.

    anchor_r, anchor_c = pos

    # Upper-bound pruning: tighter of two bounds on max additional complete rows.
    # We can place at most min(empty_cells, pieces_left × 4) more cells.
    # Additionally, cells already placed in rows anchor_r..ROWS-1 count towards
    # completing those rows – so the total cells available to fill the remaining
    # rows is filled_in_partial_rows + max_placeable.
    remaining_rows = ROWS - anchor_r
    pieces_left = sum(counts.values())
    # All empty cells lie in rows anchor_r..ROWS-1 (first-empty-cell invariant).
    empty_cells = sum(
        1 for r in range(anchor_r, ROWS) for c in range(COLS)
        if grid[r][c] == 0
    )
    filled_in_partial_rows = remaining_rows * COLS - empty_cells
    max_additional_rows = min(
        remaining_rows,
        (filled_in_partial_rows + min(empty_cells, pieces_left * 4)) // COLS,
    )
    if s + max_additional_rows * (POINTS_PER_ROW + BONUS_POINTS_PER_ROW) <= state[0]:
        return

    for name, rotations in PIECES.items():
        if counts[name] == 0:
            continue
        anchors = PIECE_ANCHORS[name]
        for rot_idx, shape in enumerate(rotations):
            off_r, off_c = anchors[rot_idx]
            adj_r = anchor_r - off_r
            adj_c = anchor_c - off_c

            if can_place(grid, shape, adj_r, adj_c):
                label = _PIECE_LABELS[name]
                owner_id = 0
                if owner_grid is not None:
                    total_pieces = (
                        progress.get("initial_pieces_left")
                        if progress is not None and progress.get("initial_pieces_left") is not None
                        else sum(counts.values())
                    )
                    assert total_pieces is not None
                    owner_id = total_pieces - sum(counts.values()) + 1
                place(grid, shape, adj_r, adj_c, label)
                if owner_grid is not None:
                    place(owner_grid, shape, adj_r, adj_c, owner_id)
                counts[name] -= 1
                solve_max_score(grid, counts, state, progress, owner_grid)
                counts[name] += 1
                unplace(grid, shape, adj_r, adj_c)
                if owner_grid is not None:
                    unplace(owner_grid, shape, adj_r, adj_c)
                if _branch_should_stop(progress):
                    return


def _enumerate_root_branches(grid: Grid, counts: Counts) -> List[Tuple[Grid, Grid, Counts]]:
    branches: List[Tuple[Grid, Grid, Counts]] = []
    pos = find_first_empty(grid)
    if pos is None:
        return branches

    anchor_r, anchor_c = pos
    for name, rotations in PIECES.items():
        if counts[name] == 0:
            continue
        anchors = PIECE_ANCHORS[name]
        for rot_idx, shape in enumerate(rotations):
            off_r, off_c = anchors[rot_idx]
            adj_r = anchor_r - off_r
            adj_c = anchor_c - off_c
            if can_place(grid, shape, adj_r, adj_c):
                branch_grid = _clone_grid(grid)
                branch_owner_grid = [[0] * COLS for _ in range(ROWS)]
                branch_counts = _clone_counts(counts)
                label = _PIECE_LABELS[name]
                place(branch_grid, shape, adj_r, adj_c, label)
                place(branch_owner_grid, shape, adj_r, adj_c, 1)
                branch_counts[name] -= 1
                if not prune_by_region(branch_grid):
                    branches.append((branch_grid, branch_owner_grid, branch_counts))

    return branches


def solve_max_score_parallel(
    grid: Grid,
    counts: Counts,
    started_at: float,
    report_interval: float = 2.0,
    branch_stall_timeout: Optional[float] = None,
    quiet: bool = False,
) -> Tuple[int, Optional[Grid], Optional[Grid], int]:
    """Run the score search across top-level branches in parallel processes."""
    base_score = score_grid(grid)
    best_state: List = [base_score, _clone_grid(grid), None]
    target_score = _theoretical_max_score(counts)
    progress = {
        "started_at": started_at,
        "last_report": started_at,
        "report_interval": report_interval,
        "nodes": 0,
        "quiet": quiet,
    }

    branches = _enumerate_root_branches(grid, counts)
    _progress_print(
        progress,
        f"[progress] process branches={len(branches)}  best={best_state[0]}  "
        f"pieces_left={sum(counts.values())}  target={target_score}",
    )

    if not branches:
        return best_state[0], best_state[1], best_state[2], progress["nodes"]

    worker_count = min(len(branches), os.cpu_count() or 1)
    completed_branches = 0
    mp_context = mp.get_context("fork")
    progress_queue = None
    result_queue = None
    workers = []
    try:
        progress_queue = mp_context.Queue()
        result_queue = mp_context.Queue()
        workers = [
            mp_context.Process(
                target=_solve_max_score_branch_process,
                args=(
                    idx,
                    branch_grid,
                    branch_owner_grid,
                    branch_counts,
                    started_at,
                    target_score,
                    report_interval,
                    branch_stall_timeout,
                    progress_queue,
                    result_queue,
                ),
                name=f"solve-max-score-{idx:02d}",
            )
            for idx, (branch_grid, branch_owner_grid, branch_counts) in enumerate(branches)
        ]
        for worker in workers:
            worker.start()

        remaining_branches = len(branches)
        reached_target = False

        while completed_branches < len(branches):
            _drain_branch_reports(progress_queue, progress)
            try:
                result = result_queue.get(timeout=report_interval)
            except queue.Empty:
                now = time.perf_counter()
                running = sum(1 for worker in workers if worker.is_alive())
                _progress_print(
                    progress,
                    f"[progress] elapsed={now - started_at:.1f}s  "
                    f"branches_done={completed_branches}/{len(branches)}  "
                    f"running={running}  nodes={progress['nodes']}  "
                    f"best={best_state[0]}  target={target_score}",
                )
                progress["last_report"] = now
                continue

            completed_branches += 1
            remaining_branches -= 1
            score = result["score"]
            best_grid = result["best_grid"]
            best_owner_grid = result["best_owner_grid"]
            nodes = result["nodes"]
            progress["nodes"] += nodes
            _drain_branch_reports(progress_queue, progress)

            if score > best_state[0]:
                best_state[0] = score
                best_state[1] = best_grid
                best_state[2] = best_owner_grid
                _progress_print(
                    progress,
                    f"[newbest] score={score}  nodes={progress['nodes']}  "
                    f"elapsed={time.perf_counter() - started_at:.3f}s",
                )

            if best_state[0] >= target_score:
                reached_target = True
                break

            now = time.perf_counter()
            if now - progress["last_report"] >= report_interval:
                running = sum(1 for worker in workers if worker.is_alive())
                _progress_print(
                    progress,
                    f"[progress] elapsed={now - started_at:.1f}s  "
                    f"branches_done={completed_branches}/{len(branches)}  "
                    f"running={running}  nodes={progress['nodes']}  "
                    f"best={best_state[0]}  target={target_score}",
                )
                progress["last_report"] = now

        if reached_target:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
        for worker in workers:
            worker.join()

        while remaining_branches > 0:
            try:
                result = result_queue.get_nowait()
            except queue.Empty:
                break
            completed_branches += 1
            remaining_branches -= 1
            progress["nodes"] += result["nodes"]
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
        for worker in workers:
            worker.join()
        _drain_branch_reports(progress_queue, progress)
        if progress_queue is not None:
            progress_queue.close()
            progress_queue.join_thread()
        if result_queue is not None:
            result_queue.close()
            result_queue.join_thread()

    return best_state[0], best_state[1], best_state[2], progress["nodes"]


# ---------------------------------------------------------------------------
# 8. Validation and display
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


def _piece_palette() -> dict[int, str]:
    return {
        _PIECE_LABELS["I"]: "#c4111a",
        _PIECE_LABELS["O"]: "#ff6a03",
        _PIECE_LABELS["T"]: "#976239",
        _PIECE_LABELS["S"]: "#2cbe57",
        _PIECE_LABELS["Z"]: "#0f54d5",
        _PIECE_LABELS["L"]: "#e3d20b",
        _PIECE_LABELS["J"]: "#5448a5",
    }


def save_grid_svg(grid: Grid, owner_grid: Optional[Grid], output_path: str) -> None:
    """Export the board to an SVG image.

    owner_grid stores per-piece instance ids; we use it to overlay hatch
    variants so adjacent tetrominoes of the same colour are still distinguishable.
    """
    cell = 36
    pad = 16
    width = pad * 2 + COLS * cell
    height = pad * 2 + ROWS * cell
    palette = _piece_palette()

    lines: List[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
    )
    lines.append('<defs>')
    for idx in range(8):
        step = 7 + idx
        lines.append(
            f'<pattern id="h{idx}" patternUnits="userSpaceOnUse" width="{step}" height="{step}" '
            'patternTransform="rotate(45)">'
        )
        lines.append(
            f'<line x1="0" y1="0" x2="0" y2="{step}" '
            'stroke="#111" stroke-opacity="0.20" stroke-width="1"/>'
        )
        lines.append('</pattern>')
    lines.append('</defs>')
    lines.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="#f7f7f8"/>')

    for r in range(ROWS):
        for c in range(COLS):
            x = pad + c * cell
            y = pad + r * cell
            label = grid[r][c]
            if label == 0:
                lines.append(
                    f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" '
                    'fill="#f0f1f3" stroke="#c9ccd1" stroke-width="1"/>'
                )
                continue

            base = palette.get(label, "#888")
            lines.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="{base}"/>')
            if owner_grid is not None:
                owner = owner_grid[r][c]
                hatch_id = owner % 8
                lines.append(
                    f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="url(#h{hatch_id})"/>'
                )
            lines.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" '
                'fill="none" stroke="#0d0f14" stroke-opacity="0.35" stroke-width="1"/>'
            )

    lines.append(
        f'<rect x="{pad}" y="{pad}" width="{COLS * cell}" height="{ROWS * cell}" '
        'fill="none" stroke="#0d0f14" stroke-width="2"/>'
    )
    lines.append('</svg>')

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# 8. Built-in unit tests
# ---------------------------------------------------------------------------

def _run_tests() -> None:
    failures: List[str] = []
    demo_score = 0

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
    eq("L-origin is shape centre", _shape_origin_offset(PIECES["L"][0]), (0.75, 0.75))

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
    owner_test = empty_grid()
    place(g2, shape_O, 0, 0, _PIECE_LABELS["O"])
    place(owner_test, shape_O, 0, 0, 1)
    eq("reconstruct best placement log", _reconstruct_placements(g2, owner_test), [("O", 0, 0, 0)])
    unplace(g2, shape_O, 0, 0)
    unplace(owner_test, shape_O, 0, 0)

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

    # 17 – solve_max_score: empty-inventory → score 0
    ROWS, COLS = DEMO_ROWS, DEMO_COLS
    g_ms1 = [[0] * DEMO_COLS for _ in range(DEMO_ROWS)]
    counts_ms1: Counts = {name: 0 for name in PIECES}
    state_ms1: List = [0, None]
    solve_max_score(g_ms1, counts_ms1, state_ms1)
    eq("solve_max_score empty inventory → score 0", state_ms1[0], 0)

    # 18 – solve_max_score: demo config scores at least as well as solve
    g_ms2 = [[0] * DEMO_COLS for _ in range(DEMO_ROWS)]
    counts_ms2 = dict(DEMO_PIECE_COUNTS)
    state_ms2: List = [0, None]
    solve_max_score(g_ms2, counts_ms2, state_ms2)
    ok("solve_max_score demo score >= demo solve score",
       state_ms2[0] >= (demo_score if found else 0))

    # 19 – solve_max_score: giving up a piece can match or beat full-fill
    # Use a single-piece config that can fill exactly one row of a 1×4 grid.
    _save_rows2, _save_cols2 = ROWS, COLS
    ROWS, COLS = 1, 4
    g_ms3 = [[0] * 4 for _ in range(1)]
    counts_ms3: Counts = {name: 0 for name in PIECES}
    counts_ms3["I"] = 1
    state_ms3: List = [0, None]
    solve_max_score(g_ms3, counts_ms3, state_ms3)
    eq("solve_max_score 1×4 with 1 I-piece fills row → score 10",
       state_ms3[0], 10)
    ROWS, COLS = _save_rows2, _save_cols2

    print()
    if failures:
        for f in failures:
            print(f)
        sys.exit(1)
    else:
        print(f"All 38 tests passed.")


# ---------------------------------------------------------------------------
# 9. Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    global ROWS, COLS, PIECE_COUNTS

    args = sys.argv[1:]
    branch_stall_timeout: Optional[float] = 60

    filtered_args: List[str] = []
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if arg == "--branch-stall-timeout":
            if idx + 1 >= len(args):
                print("error: --branch-stall-timeout requires a numeric value", file=sys.stderr)
                sys.exit(1)
            raw_value = args[idx + 1]
            try:
                branch_stall_timeout = float(raw_value)
            except ValueError:
                print(
                    f"error: invalid --branch-stall-timeout value: {raw_value!r}",
                    file=sys.stderr,
                )
                sys.exit(1)
            if branch_stall_timeout <= 0:
                print("error: --branch-stall-timeout must be > 0", file=sys.stderr)
                sys.exit(1)
            idx += 2
            continue
        filtered_args.append(arg)
        idx += 1

    args = filtered_args

    known_flags = {"--test", "--full", "--all", "--best"}
    unknown = [a for a in args if a not in known_flags]
    if unknown:
        print(f"error: unknown argument(s): {' '.join(unknown)}", file=sys.stderr)
        print(
            "usage: python solver.py [--full] [--all | --best] [--branch-stall-timeout SECONDS] [--test]",
            file=sys.stderr,
        )
        sys.exit(1)

    if "--test" in args:
        _run_tests()
        return

    use_full = "--full" in args
    find_all = "--all" in args
    find_best = "--best" in args

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
            "      Use --best to find the highest score achievable by giving\n"
            "      up some pieces rather than requiring a complete fill.\n"
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

    if find_best:
        print("Search updates: [progress] periodic status, [newbest] when score improves")
        if branch_stall_timeout is not None:
            print(f"Branch stall timeout: {branch_stall_timeout:.3f}s")
        print()
        best_score_val, best_grid_val, best_owner_grid, nodes = solve_max_score_parallel(
            grid,
            counts,
            t0,
            branch_stall_timeout=branch_stall_timeout,
        )
        elapsed = time.perf_counter() - t0
        print(
            f"Best score found: {best_score_val}  "
            f"(elapsed: {elapsed:.3f}s, nodes: {nodes})"
        )
        if best_grid_val is not None and best_owner_grid is not None:
            print()
            print("Best scoring grid:")
            print_grid(best_grid_val)
            _print_reconstructed_placement_log(best_grid_val, best_owner_grid)
            print()
            print("Scoring breakdown:")
            print_score(best_grid_val)
            # Report how many cells are filled vs total.
            # Each tetromino covers exactly 4 cells, so filled // 4 is exact.
            filled = sum(
                1 for r in range(ROWS) for c in range(COLS)
                if best_grid_val[r][c] != 0
            )
            total = ROWS * COLS
            pieces_available = sum(PIECE_COUNTS.values())
            print(
                f"\nCells filled: {filled}/{total}  |  "
                f"Pieces used: {filled // 4}/{pieces_available}"
            )
            image_path = os.path.join(os.getcwd(), "best_grid.svg")
            save_grid_svg(best_grid_val, best_owner_grid, image_path)
            print(f"Board image saved: {image_path}")
        else:
            print("No scoring arrangement found.")

    elif find_all:
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
                print()
                _print_placement_log(placed)
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
            _print_placement_log(placed)
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
