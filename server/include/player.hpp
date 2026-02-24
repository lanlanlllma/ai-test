// player.hpp  –  Player state
// ─────────────────────────────────────────────────────────────
// A simple value type that the authoritative server owns.
// Clients never modify this directly; they send *inputs* and
// the server applies them during each tick.
// ─────────────────────────────────────────────────────────────
#pragma once

#include <nlohmann/json.hpp>
#include <string>
#include <cstdint>

struct Player {
    uint32_t    id   = 0;
    std::string name = "Player";
    double      x    = 0.0;     // position
    double      y    = 0.0;
    double      dx   = 0.0;     // pending input direction
    double      dy   = 0.0;
    int         hp   = 100;     // hit‑points
    double      speed = 200.0;  // pixels per second
    bool        attacking = false;
    double      attack_cooldown = 0.0;

    // Serialize for network broadcast
    nlohmann::json to_json() const {
        return {
            {"id",   id},
            {"name", name},
            {"x",    x},
            {"y",    y},
            {"hp",   hp},
            {"attacking", attacking}
        };
    }
};
