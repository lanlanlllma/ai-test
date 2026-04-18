import json
import sqlite3
import sys
import time
from itertools import product
from pathlib import Path
from typing import Iterable, Optional

import solver


PIECE_ORDER = ["I", "O", "S", "Z", "L", "J", "T"]
DEFAULT_DB_PATH = Path("best_solutions.sqlite3")
TOTAL_COMBINATIONS = 6 ** len(PIECE_ORDER)
PROGRESS_BAR_WIDTH = 28


def _parse_args(argv: list[str]) -> dict:
    db_path = DEFAULT_DB_PATH
    branch_stall_timeout: Optional[float] = None
    limit: Optional[int] = None
    report_every = 25

    idx = 0
    while idx < len(argv):
        arg = argv[idx]
        if arg == "--db":
            if idx + 1 >= len(argv):
                raise SystemExit("error: --db requires a path")
            db_path = Path(argv[idx + 1])
            idx += 2
            continue
        if arg == "--branch-stall-timeout":
            if idx + 1 >= len(argv):
                raise SystemExit("error: --branch-stall-timeout requires a numeric value")
            try:
                branch_stall_timeout = float(argv[idx + 1])
            except ValueError as exc:
                raise SystemExit(
                    f"error: invalid --branch-stall-timeout value: {argv[idx + 1]!r}"
                ) from exc
            if branch_stall_timeout <= 0:
                raise SystemExit("error: --branch-stall-timeout must be > 0")
            idx += 2
            continue
        if arg == "--limit":
            if idx + 1 >= len(argv):
                raise SystemExit("error: --limit requires an integer value")
            try:
                limit = int(argv[idx + 1])
            except ValueError as exc:
                raise SystemExit(f"error: invalid --limit value: {argv[idx + 1]!r}") from exc
            if limit <= 0:
                raise SystemExit("error: --limit must be > 0")
            idx += 2
            continue
        if arg == "--report-every":
            if idx + 1 >= len(argv):
                raise SystemExit("error: --report-every requires an integer value")
            try:
                report_every = int(argv[idx + 1])
            except ValueError as exc:
                raise SystemExit(
                    f"error: invalid --report-every value: {argv[idx + 1]!r}"
                ) from exc
            if report_every <= 0:
                raise SystemExit("error: --report-every must be > 0")
            idx += 2
            continue
        raise SystemExit(
            "usage: python emulate.py [--db PATH] [--branch-stall-timeout SECONDS] "
            "[--limit N] [--report-every N]"
        )

    return {
        "db_path": db_path,
        "branch_stall_timeout": branch_stall_timeout,
        "limit": limit,
        "report_every": report_every,
    }


def _iter_count_combinations() -> Iterable[dict[str, int]]:
    for values in product(range(6), repeat=len(PIECE_ORDER)):
        yield dict(zip(PIECE_ORDER, values, strict=True))


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS best_solutions (
            i_count INTEGER NOT NULL,
            o_count INTEGER NOT NULL,
            s_count INTEGER NOT NULL,
            z_count INTEGER NOT NULL,
            l_count INTEGER NOT NULL,
            j_count INTEGER NOT NULL,
            t_count INTEGER NOT NULL,
            best_score INTEGER NOT NULL,
            nodes INTEGER NOT NULL,
            elapsed_seconds REAL NOT NULL,
            filled_cells INTEGER NOT NULL,
            grid_json TEXT NOT NULL,
            owner_grid_json TEXT,
            placements_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (i_count, o_count, s_count, z_count, l_count, j_count, t_count)
        );

        CREATE INDEX IF NOT EXISTS idx_best_solutions_score
        ON best_solutions(best_score DESC);
        """
    )
    conn.commit()


def _serialize_grid(grid: Optional[solver.Grid]) -> str:
    return json.dumps(grid if grid is not None else [])


def _serialize_placements(grid: Optional[solver.Grid], owner_grid: Optional[solver.Grid]) -> str:
    if grid is None or owner_grid is None:
        return json.dumps([])
    placements = solver._reconstruct_placements(grid, owner_grid)
    serializable = [
        {
            "piece": name,
            "rotation": rot_idx,
            "anchor_r": adj_r,
            "anchor_c": adj_c,
        }
        for name, rot_idx, adj_r, adj_c in placements
    ]
    return json.dumps(serializable)


def _filled_cells(grid: Optional[solver.Grid]) -> int:
    if grid is None:
        return 0
    return sum(1 for row in grid for cell in row if cell != 0)


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _render_progress(current: int, total: int, started_at: float, best_score: int) -> str:
    ratio = 0.0 if total <= 0 else min(1.0, current / total)
    filled = int(PROGRESS_BAR_WIDTH * ratio)
    bar = "#" * filled + "-" * (PROGRESS_BAR_WIDTH - filled)
    elapsed = time.perf_counter() - started_at
    eta = 0.0
    if current > 0 and total >= current:
        eta = (elapsed / current) * (total - current)
    return (
        f"\r[{bar}] {current}/{total} "
        f"({ratio * 100:5.1f}%)  elapsed={_format_duration(elapsed)}  "
        f"eta={_format_duration(eta)}  best={best_score}"
    )


def _store_result(
    conn: sqlite3.Connection,
    counts: dict[str, int],
    best_score: int,
    best_grid: Optional[solver.Grid],
    best_owner_grid: Optional[solver.Grid],
    nodes: int,
    elapsed_seconds: float,
) -> None:
    conn.execute(
        """
        INSERT INTO best_solutions (
            i_count, o_count, s_count, z_count, l_count, j_count, t_count,
            best_score, nodes, elapsed_seconds, filled_cells,
            grid_json, owner_grid_json, placements_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(i_count, o_count, s_count, z_count, l_count, j_count, t_count)
        DO UPDATE SET
            best_score = excluded.best_score,
            nodes = excluded.nodes,
            elapsed_seconds = excluded.elapsed_seconds,
            filled_cells = excluded.filled_cells,
            grid_json = excluded.grid_json,
            owner_grid_json = excluded.owner_grid_json,
            placements_json = excluded.placements_json,
            created_at = CURRENT_TIMESTAMP
        """,
        (
            counts["I"],
            counts["O"],
            counts["S"],
            counts["Z"],
            counts["L"],
            counts["J"],
            counts["T"],
            best_score,
            nodes,
            elapsed_seconds,
            _filled_cells(best_grid),
            _serialize_grid(best_grid),
            _serialize_grid(best_owner_grid),
            _serialize_placements(best_grid, best_owner_grid),
        ),
    )


def _run_one(counts: dict[str, int], branch_stall_timeout: Optional[float]) -> tuple[int, Optional[solver.Grid], Optional[solver.Grid], int, float]:
    grid = solver.empty_grid()
    started_at = time.perf_counter()
    best_score, best_grid, best_owner_grid, nodes = solver.solve_max_score_parallel(
        grid,
        counts,
        started_at,
        branch_stall_timeout=branch_stall_timeout,
        quiet=True,
    )
    elapsed_seconds = time.perf_counter() - started_at
    return best_score, best_grid, best_owner_grid, nodes, elapsed_seconds


def main() -> None:
    options = _parse_args(sys.argv[1:])
    db_path: Path = options["db_path"]
    branch_stall_timeout: Optional[float] = options["branch_stall_timeout"]
    limit: Optional[int] = options["limit"]
    report_every: int = options["report_every"]

    solver.ROWS = solver.FULL_ROWS
    solver.COLS = solver.FULL_COLS

    target_total = TOTAL_COMBINATIONS if limit is None else min(limit, TOTAL_COMBINATIONS)

    print(
        f"Enumerating all {len(PIECE_ORDER)} tetromino count combinations "
        f"(0..5 each, total={TOTAL_COMBINATIONS}) into {db_path}"
    )
    if branch_stall_timeout is not None:
        print(f"Branch stall timeout: {branch_stall_timeout:.3f}s")
    if limit is not None:
        print(f"Limit: {limit} combinations")
    print()

    conn = sqlite3.connect(db_path)
    try:
        _ensure_schema(conn)
        total_started = time.perf_counter()
        global_best_score = 0

        for idx, counts in enumerate(_iter_count_combinations(), start=1):
            if limit is not None and idx > limit:
                break

            best_score, best_grid, best_owner_grid, nodes, elapsed_seconds = _run_one(
                counts,
                branch_stall_timeout,
            )
            _store_result(
                conn,
                counts,
                best_score,
                best_grid,
                best_owner_grid,
                nodes,
                elapsed_seconds,
            )
            global_best_score = max(global_best_score, best_score)

            progress_line = _render_progress(idx, target_total, total_started, global_best_score)
            print(progress_line, end="", flush=True)

            if idx % report_every == 0:
                conn.commit()

        conn.commit()
        total_elapsed = time.perf_counter() - total_started
        rows_written = conn.execute("SELECT COUNT(*) FROM best_solutions").fetchone()[0]
        if target_total > 0:
            print()
        print(f"Finished. Rows in database: {rows_written}. Total elapsed: {total_elapsed:.3f}s")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
