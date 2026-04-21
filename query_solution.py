#!/usr/bin/env python3
"""
Query tetromino solutions from database and display board, score, and placements.

Usage:
    python query_solution.py '{"I": 2, "O": 1, "S": 0, "Z": 0, "L": 1, "J": 1, "T": 2}'
    python query_solution.py --db best_solutions.sqlite3 '{"I": 1, "O": 2, "S": 1, "Z": 1, "L": 1, "J": 1, "T": 1}'
"""

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import solver


PIECE_ORDER = ["I", "O", "S", "Z", "L", "J", "T"]
DEFAULT_DB_PATH = Path("best_solutions.sqlite3")


def query_solution(
    counts: Dict[str, int],
    db_path: Path = DEFAULT_DB_PATH,
) -> Optional[Dict[str, Any]]:
    """
    Query the database for the best solution given piece counts.
    
    Args:
        counts: Dictionary with piece names as keys (I, O, S, Z, L, J, T) and counts as values
        db_path: Path to the SQLite database
    
    Returns:
        Dictionary with solution data (grid, placements, score, etc.) or None if not found
    """
    if not db_path.exists():
        print(f"Error: Database file not found: {db_path}")
        return None
    
    # Validate and normalize counts
    for piece_name in PIECE_ORDER:
        if piece_name not in counts:
            counts[piece_name] = 0
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        row = conn.execute(
            """
            SELECT 
                i_count, o_count, s_count, z_count, l_count, j_count, t_count,
                best_score, nodes, elapsed_seconds, filled_cells,
                grid_json, owner_grid_json, placements_json, created_at
            FROM best_solutions
            WHERE i_count = ? AND o_count = ? AND s_count = ? AND z_count = ?
                AND l_count = ? AND j_count = ? AND t_count = ?
            """,
            (
                counts["I"],
                counts["O"],
                counts["S"],
                counts["Z"],
                counts["L"],
                counts["J"],
                counts["T"],
            ),
        ).fetchone()
        
        if row is None:
            return None
        
        grid = json.loads(row["grid_json"]) if row["grid_json"] else None
        placements = json.loads(row["placements_json"]) if row["placements_json"] else []
        
        return {
            "counts": {
                "I": row["i_count"],
                "O": row["o_count"],
                "S": row["s_count"],
                "Z": row["z_count"],
                "L": row["l_count"],
                "J": row["j_count"],
                "T": row["t_count"],
            },
            "best_score": row["best_score"],
            "nodes": row["nodes"],
            "elapsed_seconds": row["elapsed_seconds"],
            "filled_cells": row["filled_cells"],
            "grid": grid,
            "placements": placements,
            "created_at": row["created_at"],
        }
    finally:
        conn.close()


def print_solution(solution: Dict[str, Any]) -> None:
    """
    Print the solution with board, score, and placement information.
    
    Args:
        solution: Solution dictionary from query_solution()
    """
    print("\n" + "=" * 60)
    print("TETROMINO SOLUTION")
    print("=" * 60)
    
    # Print piece counts
    print("\nPiece Counts:")
    for piece_name in PIECE_ORDER:
        count = solution["counts"][piece_name]
        if count > 0:
            print(f"  {piece_name}: {count}")
    
    # Print board
    print("\nBoard:")
    if solution["grid"]:
        solver.print_grid(solution["grid"])
    else:
        print("  (No grid data)")
    
    # Print score
    print("\nScore:")
    if solution["grid"]:
        solver.print_score(solution["grid"])
    else:
        print("  (No score data)")
    
    # Print placement information
    print("\nPlacements:")
    placements = solution["placements"]
    if placements:
        for i, placement in enumerate(placements, 1):
            piece = placement["piece"]
            rotation = placement["rotation"]
            anchor_r = placement["anchor_r"]
            anchor_c = placement["anchor_c"]
            print(
                f"  {i}. {piece} - Rotation: {rotation}, "
                f"Position (r,c): ({anchor_r}, {anchor_c})"
            )
    else:
        print("  (No placements)")
    
    # Print search statistics
    print("\nSearch Statistics:")
    print(f"  Best Score: {solution['best_score']}")
    print(f"  Nodes Explored: {solution['nodes']}")
    print(f"  Time: {solution['elapsed_seconds']:.2f}s")
    print(f"  Filled Cells: {solution['filled_cells']}")
    print(f"  Created: {solution['created_at']}")
    print("\n" + "=" * 60 + "\n")


def get_placements(solution: Dict[str, Any]) -> List[Tuple[str, int, int, int]]:
    """
    Extract placements from solution as a list of tuples.
    
    Args:
        solution: Solution dictionary from query_solution()
    
    Returns:
        List of tuples: (piece_name, rotation, anchor_r, anchor_c)
    """
    placements = []
    for placement in solution.get("placements", []):
        placements.append((
            placement["piece"],
            placement["rotation"],
            placement["anchor_r"],
            placement["anchor_c"],
        ))
    return placements


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query tetromino solutions from database"
    )
    parser.add_argument(
        "counts_json",
        help="JSON dict with piece counts, e.g. '{\"I\": 2, \"O\": 1, \"S\": 0, \"Z\": 0, \"L\": 1, \"J\": 1, \"T\": 2}'",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to database (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--json-output",
        action="store_true",
        help="Output results as JSON instead of formatted text",
    )
    
    args = parser.parse_args()
    
    # Parse counts from JSON
    try:
        counts = json.loads(args.counts_json)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        return
    
    # Validate counts
    if not isinstance(counts, dict):
        print("Error: counts must be a JSON dictionary")
        return
    
    # Query database
    solution = query_solution(counts, args.db)
    
    if solution is None:
        print(f"No solution found in database for counts: {counts}")
        return
    
    if args.json_output:
        print(json.dumps(solution, indent=2, default=str))
    else:
        print_solution(solution)
        placements = get_placements(solution)
        print("Placements (programmatic format):")
        print(f"  {placements}")


if __name__ == "__main__":
    main()
