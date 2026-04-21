#!/usr/bin/env python3
"""
Example: How to use query_solution module programmatically
"""

from query_solution import query_solution, get_placements
from pathlib import Path


def main():
    # Example 1: Simple query with dict input
    print("=" * 60)
    print("Example 1: Query with piece counts")
    print("=" * 60)
    
    counts = {
        "I": 5,
        "O": 5,
        "S": 5,
        "Z": 5,
        "L": 5,
        "J": 5,
        "T": 1,
    }
    
    solution = query_solution(counts, Path("best_solutions.sqlite3"))
    
    if solution:
        print(f"\nFound solution with score: {solution['best_score']}")
        print(f"Filled cells: {solution['filled_cells']}")
        print(f"Time taken: {solution['elapsed_seconds']:.2f}s")
        
        # Get placements
        placements = get_placements(solution)
        print(f"\nTotal placements: {len(placements)}")
        print("\nFirst 5 placements:")
        for piece, rotation, anchor_r, anchor_c in placements[:5]:
            print(f"  Piece: {piece}, Rotation: {rotation}, Position: ({anchor_r}, {anchor_c})")
    else:
        print("No solution found")
    
    # Example 2: Query another combination
    print("\n" + "=" * 60)
    print("Example 2: Another query")
    print("=" * 60)
    
    counts2 = {
        "I": 5,
        "O": 5,
        "S": 5,
        "Z": 5,
        "L": 5,
        "J": 5,
        "T": 4,
    }
    
    solution2 = query_solution(counts2)
    
    if solution2:
        print(f"\nSolution found!")
        print(f"  Piece counts: {solution2['counts']}")
        print(f"  Best score: {solution2['best_score']}")
        print(f"  Grid size: {len(solution2['grid'])}x{len(solution2['grid'][0]) if solution2['grid'] else 0}")
        
        # Get placements for programmatic use
        placements = get_placements(solution2)
        print(f"  Placements: {placements}")
    else:
        print("No solution found")


if __name__ == "__main__":
    main()
