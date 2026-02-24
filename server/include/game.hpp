// game.hpp  –  Authoritative game simulation
// ─────────────────────────────────────────────────────────────
// Owns all Player state for one room.  The tick() method is
// called at a fixed rate (e.g. 30 Hz) to advance the
// simulation and produce the snapshot that gets broadcast.
// ─────────────────────────────────────────────────────────────
#pragma once

#include "player.hpp"
#include <nlohmann/json.hpp>
#include <unordered_map>
#include <cstdint>
#include <mutex>

class Game {
public:
    static constexpr double ARENA_W = 800.0;
    static constexpr double ARENA_H = 600.0;
    static constexpr double ATTACK_RANGE = 50.0;
    static constexpr int    ATTACK_DAMAGE = 10;
    static constexpr double ATTACK_COOLDOWN_SEC = 0.5;

    // Add / remove players
    void add_player(uint32_t id, const std::string& name);
    void remove_player(uint32_t id);

    // Apply client input (called from session thread)
    void set_input(uint32_t id, double dx, double dy);
    void set_attack(uint32_t id);

    // Advance simulation by dt seconds (called from tick timer)
    void tick(double dt);

    // Build the JSON snapshot to broadcast
    nlohmann::json snapshot() const;

    // Check for a winner (last player standing)
    // Returns empty string if game is still going
    std::string check_winner() const;

    // Number of active players
    std::size_t player_count() const;

private:
    mutable std::mutex mtx_;
    std::unordered_map<uint32_t, Player> players_;
};
