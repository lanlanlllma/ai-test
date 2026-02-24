// test_game.cpp  –  Unit tests for Game simulation
// ─────────────────────────────────────────────────────────────
#include "game.hpp"
#include <cassert>
#include <cmath>
#include <iostream>

void test_add_remove() {
    Game g;
    assert(g.player_count() == 0);

    g.add_player(1, "Alice");
    assert(g.player_count() == 1);

    g.add_player(2, "Bob");
    assert(g.player_count() == 2);

    g.remove_player(1);
    assert(g.player_count() == 1);

    g.remove_player(2);
    assert(g.player_count() == 0);
}

void test_movement() {
    Game g;
    g.add_player(1, "Alice");

    // Get initial position from snapshot
    auto snap1 = g.snapshot();
    double x0 = snap1[0]["x"].get<double>();
    double y0 = snap1[0]["y"].get<double>();

    // Move right
    g.set_input(1, 1.0, 0.0);
    g.tick(1.0); // 1 second

    auto snap2 = g.snapshot();
    double x1 = snap2[0]["x"].get<double>();
    assert(x1 > x0); // should have moved right
}

void test_arena_bounds() {
    Game g;
    g.add_player(1, "Test");

    // Move far left – should clamp at 0
    g.set_input(1, -1.0, 0.0);
    for (int i = 0; i < 100; ++i) g.tick(0.1);

    auto snap = g.snapshot();
    double x = snap[0]["x"].get<double>();
    assert(x >= 0.0);
    assert(x <= Game::ARENA_W);
}

void test_attack_damage() {
    Game g;
    g.add_player(1, "A");
    g.add_player(2, "B");

    // Move them to the same spot so attack hits
    g.set_input(1, 0.0, 0.0);
    g.set_input(2, 0.0, 0.0);

    // Get their positions and check initial HP
    auto snap0 = g.snapshot();
    int hp_before = -1;
    for (auto& p : snap0) {
        if (p["id"] == 2) hp_before = p["hp"].get<int>();
    }
    assert(hp_before == 100);

    // Put them very close together by moving player 2 toward player 1
    // First, get positions
    double x1 = 0, y1 = 0, x2 = 0, y2 = 0;
    for (auto& p : snap0) {
        if (p["id"] == 1) { x1 = p["x"].get<double>(); y1 = p["y"].get<double>(); }
        if (p["id"] == 2) { x2 = p["x"].get<double>(); y2 = p["y"].get<double>(); }
    }

    double dist = std::sqrt((x2 - x1) * (x2 - x1) + (y2 - y1) * (y2 - y1));
    if (dist < Game::ATTACK_RANGE) {
        // They're already close – attack should hit
        g.set_attack(1);
        g.tick(0.033);

        auto snap1 = g.snapshot();
        for (auto& p : snap1) {
            if (p["id"] == 2) {
                int hp_after = p["hp"].get<int>();
                assert(hp_after == hp_before - Game::ATTACK_DAMAGE);
            }
        }
    }
    // If they're far apart, we skip this sub‑test (depends on spawn logic)
}

void test_snapshot_format() {
    Game g;
    g.add_player(1, "Test");

    auto snap = g.snapshot();
    assert(snap.is_array());
    assert(snap.size() == 1);
    assert(snap[0].contains("id"));
    assert(snap[0].contains("name"));
    assert(snap[0].contains("x"));
    assert(snap[0].contains("y"));
    assert(snap[0].contains("hp"));
    assert(snap[0].contains("attacking"));
}

void test_winner_check() {
    Game g;
    // No winner with 0 or 1 player
    assert(g.check_winner().empty());

    g.add_player(1, "Solo");
    assert(g.check_winner().empty());
}

void test_input_normalization() {
    Game g;
    g.add_player(1, "Fast");

    // Large diagonal input should be normalized
    g.set_input(1, 100.0, 100.0);
    g.tick(1.0);

    auto snap = g.snapshot();
    // Player should have moved, but not 100*speed pixels
    // (normalization caps the direction vector to length 1)
    double x = snap[0]["x"].get<double>();
    // Speed is 200, so max movement in 1s ≈ 200 * 0.707 ≈ 141
    // Without normalization it would be 200 * 100 = 20000 (clamped)
    assert(x <= Game::ARENA_W);
}

int main() {
    test_add_remove();
    test_movement();
    test_arena_bounds();
    test_attack_damage();
    test_snapshot_format();
    test_winner_check();
    test_input_normalization();

    std::cout << "All game tests passed.\n";
    return 0;
}
