from __future__ import annotations

import solver


def run_tests() -> None:
    failures: list[str] = []
    demo_score = 0

    def ok(desc: str, value: bool) -> None:
        if not value:
            failures.append(f"FAIL [{desc}]")
        else:
            print(f"  OK  [{desc}]")

    def eq(desc: str, actual, expected) -> None:
        ok(f"{desc}: got {actual!r}, want {expected!r}", actual == expected)

    print("=== Running unit tests ===\n")

    eq(
        "normalise O",
        solver._normalise([(2, 3), (2, 4), (3, 3), (3, 4)]),
        ((0, 0), (0, 1), (1, 0), (1, 1)),
    )

    eq("I rotations == 2", len(solver.PIECES["I"]), 2)
    eq("O rotations == 1", len(solver.PIECES["O"]), 1)
    eq("T rotations == 4", len(solver.PIECES["T"]), 4)
    eq("PIECES has 7 types", len(solver.PIECES), 7)
    eq("total rotations == 19", sum(len(v) for v in solver.PIECES.values()), 19)

    ok(
        "every anchor cell is IN its shape",
        all(
            solver.PIECE_ANCHORS[name][idx] in shape
            for name, rots in solver.PIECES.items()
            for idx, shape in enumerate(rots)
        ),
    )
    ok(
        "anchor is topmost-then-leftmost",
        all(
            solver.PIECE_ANCHORS[name][idx]
            == (
                (lambda s: (
                    min(dr for dr, _ in s),
                    min(dc for dr, dc in s if dr == min(dr2 for dr2, _ in s)),
                ))(shape)
            )
            for name, rots in solver.PIECES.items()
            for idx, shape in enumerate(rots)
        ),
    )
    eq("L-origin is shape centre", solver._shape_origin_offset(solver.PIECES["L"][0]), (1.25, 0.25))

    s_h = solver.PIECES["S"][0]
    eq("S-horizontal shape[0]", s_h[0], (0, 1))
    eq("S-horizontal anchor", solver.PIECE_ANCHORS["S"][0], (0, 1))

    saved_rows, saved_cols = solver.ROWS, solver.COLS
    solver.ROWS, solver.COLS = 10, 10
    g7 = [[0] * 10 for _ in range(10)]
    off_r, off_c = solver.PIECE_ANCHORS["S"][0]
    adj_r, adj_c = 2 - off_r, 3 - off_c
    solver.place(g7, s_h, adj_r, adj_c, solver._PIECE_LABELS["S"])
    eq("S-horizontal covers anchor (2,3)", g7[2][3], solver._PIECE_LABELS["S"])
    solver.ROWS, solver.COLS = saved_rows, saved_cols

    g = solver.empty_grid()
    shape_O = solver.PIECES["O"][0]
    ok("can_place O at (0,0)", solver.can_place(g, shape_O, 0, 0))
    ok("can_place O at top-right corner is False", not solver.can_place(g, shape_O, 0, solver.COLS - 1))
    g2 = solver.empty_grid()
    solver.place(g2, shape_O, 0, 0, 1)
    eq("place O sets (0,0)", g2[0][0], 1)
    eq("place O sets (0,1)", g2[0][1], 1)
    solver.unplace(g2, shape_O, 0, 0)
    eq("unplace O clears (0,0)", g2[0][0], 0)
    owner_test = solver.empty_grid()
    solver.place(g2, shape_O, 0, 0, solver._PIECE_LABELS["O"])
    solver.place(owner_test, shape_O, 0, 0, 1)
    eq(
        "reconstruct best placement log",
        solver.reconstruct_placements(g2, owner_test),
        [("O", 0, 0, 0)],
    )
    solver.unplace(g2, shape_O, 0, 0)
    solver.unplace(owner_test, shape_O, 0, 0)

    g3 = solver.empty_grid()
    sizes = solver._flood_fill_sizes(g3)
    eq("empty grid: 1 region", len(sizes), 1)
    eq("empty grid: region size = ROWS*COLS", sizes[0], solver.ROWS * solver.COLS)

    g4 = solver.empty_grid()
    for c in range(solver.COLS):
        g4[0][c] = 1
    for c in range(solver.COLS):
        g4[1][c] = 1
    g4[1][4] = 0
    g4[1][5] = 0
    for c in range(solver.COLS):
        g4[2][c] = 1
    ok("prune detects isolated 2-cell region", solver.prune_by_region(g4))

    counts9: solver.Counts = {name: 0 for name in solver.PIECES}
    counts9["T"] = 5
    g9 = [[0] * solver.COLS for _ in range(solver.ROWS)]
    ok("parity prune: 5 T at balance 0 → prune", solver.prune_by_parity(g9, counts9))

    counts10: solver.Counts = {name: 0 for name in solver.PIECES}
    counts10["T"] = 4
    ok("parity prune: 4 T at balance 0 → no prune", not solver.prune_by_parity(g9, counts10))

    counts11: solver.Counts = {name: 5 for name in solver.PIECES}
    ok("validate_solution fails on empty grid", not solver.validate_solution(g, counts11))

    solver.ROWS, solver.COLS = 4, 10
    g_demo = [[0] * solver.COLS for _ in range(solver.ROWS)]
    counts_demo: solver.Counts = {name: 0 for name in solver.PIECES}
    counts_demo.update({"I": 2, "O": 2, "S": 2, "Z": 2, "L": 1, "J": 1, "T": 0})
    placed_demo: solver.PlacedList = []
    found = solver.solve(g_demo, counts_demo, placed_demo)
    ok("solve finds demo solution", found)
    if found:
        ok("demo solution is valid", solver.validate_solution(g_demo, counts_demo))

    g_empty = [[0] * solver.COLS for _ in range(solver.ROWS)]
    eq("score empty grid == 0", solver.score_grid(g_empty), 0)
    eq("score_breakdown empty grid == []", solver.score_breakdown(g_empty), [])

    g_s1 = [[0] * solver.COLS for _ in range(solver.ROWS)]
    for c in range(5):
        g_s1[0][c] = 1
    for c in range(5, solver.COLS):
        g_s1[0][c] = 2
    bd1 = solver.score_breakdown(g_s1)
    eq("1 filled row (2 colours): 1 entry", len(bd1), 1)
    eq("1 filled row (2 colours): no bonus", bd1[0]["bonus"], 0)
    eq("1 filled row (2 colours): total 10", bd1[0]["total"], 10)
    eq("score 1 filled row (2 colours) == 10", solver.score_grid(g_s1), 10)

    g_s2 = [[0] * solver.COLS for _ in range(solver.ROWS)]
    for c, lbl in enumerate([1, 1, 1, 2, 2, 3, 3, 4, 4, 4][:solver.COLS]):
        g_s2[0][c] = lbl
    bd2 = solver.score_breakdown(g_s2)
    eq("1 filled row (4 colours): bonus == 10", bd2[0]["bonus"], 10)
    eq("1 filled row (4 colours): total 20", bd2[0]["total"], 20)
    eq("score 1 filled row (4 colours) == 20", solver.score_grid(g_s2), 20)

    if found:
        demo_score = solver.score_grid(g_demo)
        ok(
            f"demo solution score >= {solver.ROWS * solver.POINTS_PER_ROW}",
            demo_score >= solver.ROWS * solver.POINTS_PER_ROW,
        )
    solver.ROWS, solver.COLS = saved_rows, saved_cols

    solver.ROWS, solver.COLS = solver.DEMO_ROWS, solver.DEMO_COLS
    g_ms1 = [[0] * solver.DEMO_COLS for _ in range(solver.DEMO_ROWS)]
    counts_ms1: solver.Counts = {name: 0 for name in solver.PIECES}
    state_ms1: list[int | solver.Grid | None] = [0, None]
    solver.solve_max_score(g_ms1, counts_ms1, state_ms1)
    eq("solve_max_score empty inventory → score 0", state_ms1[0], 0)

    g_ms2 = [[0] * solver.DEMO_COLS for _ in range(solver.DEMO_ROWS)]
    counts_ms2 = dict(solver.DEMO_PIECE_COUNTS)
    state_ms2: list[int | solver.Grid | None] = [0, None]
    solver.solve_max_score(g_ms2, counts_ms2, state_ms2)
    ok(
        "solve_max_score demo score >= demo solve score",
        bool(isinstance(state_ms2[0], int) and state_ms2[0] >= (demo_score if found else 0)),
    )

    saved_rows2, saved_cols2 = solver.ROWS, solver.COLS
    solver.ROWS, solver.COLS = 1, 4
    g_ms3 = [[0] * 4 for _ in range(1)]
    counts_ms3: solver.Counts = {name: 0 for name in solver.PIECES}
    counts_ms3["I"] = 1
    state_ms3: list[int | solver.Grid | None] = [0, None]
    solver.solve_max_score(g_ms3, counts_ms3, state_ms3)
    eq("solve_max_score 1×4 with 1 I-piece fills row → score 10", state_ms3[0], 10)
    solver.ROWS, solver.COLS = saved_rows2, saved_cols2

    print()
    if failures:
        for failure in failures:
            print(failure)
        raise SystemExit(1)
    print("All 38 tests passed.")


if __name__ == "__main__":
    run_tests()
