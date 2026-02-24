// test_message.cpp  –  Unit tests for message helpers
// ─────────────────────────────────────────────────────────────
// Minimal assert‑based tests (no framework dependency).
// ─────────────────────────────────────────────────────────────
#include "message.hpp"
#include <cassert>
#include <iostream>

void test_welcome() {
    auto j = msg::welcome(42);
    assert(j["type"] == "welcome");
    assert(j["id"]   == 42);
}

void test_game_state() {
    json players = json::array();
    players.push_back({{"id", 1}, {"x", 10.0}});
    auto j = msg::game_state(players);
    assert(j["type"] == "state");
    assert(j["players"].size() == 1);
    assert(j["players"][0]["id"] == 1);
}

void test_player_left() {
    auto j = msg::player_left(7);
    assert(j["type"] == "player_left");
    assert(j["id"]   == 7);
}

void test_game_over() {
    auto j = msg::game_over("Alice");
    assert(j["type"]   == "game_over");
    assert(j["winner"] == "Alice");
}

void test_get_type() {
    json j = {{"type", "input"}, {"dx", 1.0}};
    assert(msg::get_type(j) == "input");

    json bad = {{"foo", "bar"}};
    assert(msg::get_type(bad).empty());
}

void test_get_name() {
    json j = {{"name", "Bob"}};
    assert(msg::get_name(j) == "Bob");

    json missing = {{"type", "join"}};
    assert(msg::get_name(missing) == "Player");
}

void test_get_dx_dy() {
    json j = {{"dx", 0.5}, {"dy", -1.0}};
    assert(msg::get_dx(j) == 0.5);
    assert(msg::get_dy(j) == -1.0);

    json missing = {};
    assert(msg::get_dx(missing) == 0.0);
    assert(msg::get_dy(missing) == 0.0);
}

int main() {
    test_welcome();
    test_game_state();
    test_player_left();
    test_game_over();
    test_get_type();
    test_get_name();
    test_get_dx_dy();

    std::cout << "All message tests passed.\n";
    return 0;
}
