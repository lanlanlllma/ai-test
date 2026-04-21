import argparse
import json
import multiprocessing as mp
import sqlite3
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from itertools import product
from pathlib import Path
from typing import Iterator, Optional

import solver


PIECE_ORDER = ["I", "O", "S", "Z", "L", "J", "T"]
DEFAULT_DB_PATH = Path("best_solutions.sqlite3")
TOTAL_COMBINATIONS = 6 ** len(PIECE_ORDER)
PROGRESS_BAR_WIDTH = 28


def _positive_int(raw_value: str, option_name: str) -> int:
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid {option_name} value: {raw_value!r}") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError(f"{option_name} must be > 0")
    return value


def _positive_float(raw_value: str, option_name: str) -> float:
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid {option_name} value: {raw_value!r}") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError(f"{option_name} must be > 0")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python emulate.py",
        description="Enumerate tetromino count combinations and store best scores.",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite database path")
    parser.add_argument(
        "--branch-stall-timeout",
        type=lambda raw: _positive_float(raw, "--branch-stall-timeout"),
        default=None,
        help="Stop a branch after this many seconds without improvement",
    )
    parser.add_argument(
        "--limit",
        type=lambda raw: _positive_int(raw, "--limit"),
        default=None,
        help="Only evaluate the first N combinations",
    )
    parser.add_argument(
        "--report-every",
        type=lambda raw: _positive_int(raw, "--report-every"),
        default=25,
        help="Commit and print a snapshot every N completed combinations",
    )
    parser.add_argument(
        "--outer-workers",
        type=lambda raw: _positive_int(raw, "--outer-workers"),
        default=1,
        help="Number of concurrent enumeration jobs",
    )
    parser.add_argument(
        "--solver-workers",
        type=lambda raw: _positive_int(raw, "--solver-workers"),
        default=None,
        help="Maximum worker processes used by each solver job",
    )
    return parser


def _parse_args(argv: list[str]) -> argparse.Namespace:
    return _build_parser().parse_args(argv)


def _iter_count_combinations() -> Iterator[dict[str, int]]:
    for values in product(range(5, -1, -1), repeat=len(PIECE_ORDER)):
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


def _counts_key(counts: dict[str, int]) -> tuple[int, ...]:
    return tuple(counts[name] for name in PIECE_ORDER)


def _load_existing_keys(conn: sqlite3.Connection) -> set[tuple[int, ...]]:
    rows = conn.execute(
        """
        SELECT i_count, o_count, s_count, z_count, l_count, j_count, t_count
        FROM best_solutions
        """
    ).fetchall()
    return {tuple(row) for row in rows}


def _serialize_grid(grid: Optional[solver.Grid]) -> str:
    return json.dumps(grid if grid is not None else [])


def _serialize_placements(grid: Optional[solver.Grid], owner_grid: Optional[solver.Grid]) -> str:
    if grid is None or owner_grid is None:
        return json.dumps([])
    placements = solver.reconstruct_placements(grid, owner_grid)
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


def _snapshot_line(
    idx: int,
    target_total: int,
    counts: dict[str, int],
    best_score: int,
    filled_cells: int,
    nodes: int,
    elapsed_seconds: float,
) -> str:
    return (
        f"[{idx}/{target_total}] counts={{I:{counts['I']}, O:{counts['O']}, S:{counts['S']}, "
        f"Z:{counts['Z']}, L:{counts['L']}, J:{counts['J']}, T:{counts['T']}}}  "
        f"score={best_score}  filled={filled_cells}  nodes={nodes}  elapsed={elapsed_seconds:.3f}s"
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


def _run_one(
    counts: dict[str, int],
    branch_stall_timeout: Optional[float],
    solver_workers: Optional[int],
    use_parallel_solver: bool,
) -> tuple[dict[str, int], int, Optional[solver.Grid], Optional[solver.Grid], int, float]:
    grid = solver.empty_grid()
    started_at = time.perf_counter()
    if use_parallel_solver:
        best_score, best_grid, best_owner_grid, nodes = solver.solve_max_score_parallel(
            grid,
            counts,
            started_at,
            branch_stall_timeout=branch_stall_timeout,
            quiet=True,
            max_workers=solver_workers,
        )
    else:
        owner_grid = [[0] * solver.COLS for _ in range(solver.ROWS)]
        state: list[int | solver.Grid | None] = [solver.score_grid(grid), solver.empty_grid(), owner_grid]
        progress = {
            "started_at": started_at,
            "last_report": started_at,
            "last_newbest_at": started_at,
            "nodes": 0,
            "best_score": state[0],
            "progress_enabled": False,
            "newbest_enabled": False,
            "mirror_local_output": False,
            "report_interval": 2.0,
            "stall_timeout": branch_stall_timeout,
            "initial_pieces_left": sum(counts.values()),
            "initial_filled_cells": solver._count_filled_cells(grid),
        }
        solver.solve_max_score(grid, counts, state, progress, owner_grid)
        best_score = state[0] if isinstance(state[0], int) else 0
        best_grid = state[1] if isinstance(state[1], list) else None
        best_owner_grid = state[2] if isinstance(state[2], list) else None
        nodes = int(progress["nodes"])
    elapsed_seconds = time.perf_counter() - started_at
    return counts, best_score, best_grid, best_owner_grid, nodes, elapsed_seconds


def main() -> None:
    options = _parse_args(sys.argv[1:])
    db_path = options.db
    branch_stall_timeout = options.branch_stall_timeout
    limit = options.limit
    report_every = options.report_every
    outer_workers = options.outer_workers
    solver_workers = options.solver_workers

    solver.ROWS = solver.FULL_ROWS
    solver.COLS = solver.FULL_COLS

    target_total = TOTAL_COMBINATIONS if limit is None else min(limit, TOTAL_COMBINATIONS)

    print(
        f"Enumerating all {len(PIECE_ORDER)} tetromino count combinations "
        f"(0..5 each, total={TOTAL_COMBINATIONS}) into {db_path}"
    )
    if branch_stall_timeout is not None:
        print(f"Branch stall timeout: {branch_stall_timeout:.3f}s")
    print(f"Outer workers: {outer_workers}")
    if solver_workers is not None:
        print(f"Solver workers per job: {solver_workers}")
    if limit is not None:
        print(f"Limit: {limit} combinations")
    print()

    conn = sqlite3.connect(db_path)
    try:
        _ensure_schema(conn)
        existing_keys = _load_existing_keys(conn)
        existing_total = len(existing_keys)

        pending_counts = []
        for idx, counts in enumerate(_iter_count_combinations(), start=1):
            if limit is not None and idx > limit:
                break
            if _counts_key(counts) in existing_keys:
                continue
            pending_counts.append(counts)

        target_total = len(pending_counts)

        total_started = time.perf_counter()
        global_best_score = 0
        use_parallel_solver = False

        print(f"Existing rows skipped: {existing_total}")
        print(f"Pending combinations to run: {target_total}")
        print("Using process-based outer workers with sequential inner solver.")
        if target_total == 0:
            rows_written = conn.execute("SELECT COUNT(*) FROM best_solutions").fetchone()[0]
            print("Nothing to do - all selected combinations already exist in the database.")
            print(f"Finished. Rows in database: {rows_written}. Total elapsed: 0.000s")
            return

        counts_iter = iter(pending_counts)
        submitted = 0
        completed = 0
        future_to_index = {}
        mp_context = mp.get_context("spawn")

        with ProcessPoolExecutor(max_workers=outer_workers, mp_context=mp_context) as executor:
            while submitted < min(target_total, outer_workers):
                counts = next(counts_iter)
                submitted += 1
                future = executor.submit(
                    _run_one,
                    counts,
                    branch_stall_timeout,
                    solver_workers,
                    use_parallel_solver,
                )
                future_to_index[future] = submitted

            while future_to_index:
                done, _ = wait(set(future_to_index.keys()), return_when=FIRST_COMPLETED)
                for future in done:
                    future_to_index.pop(future)
                    counts, best_score, best_grid, best_owner_grid, nodes, elapsed_seconds = future.result()
                    completed += 1

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

                    progress_line = _render_progress(completed, target_total, total_started, global_best_score)
                    print(progress_line, end="", flush=True)

                    if completed % report_every == 0:
                        conn.commit()
                        print()
                        print(
                            _snapshot_line(
                                completed,
                                target_total,
                                counts,
                                best_score,
                                _filled_cells(best_grid),
                                nodes,
                                elapsed_seconds,
                            )
                        )

                    if submitted < target_total:
                        counts = next(counts_iter)
                        submitted += 1
                        next_future = executor.submit(
                            _run_one,
                            counts,
                            branch_stall_timeout,
                            solver_workers,
                            use_parallel_solver,
                        )
                        future_to_index[next_future] = submitted

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
