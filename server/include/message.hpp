// message.hpp  –  JSON message protocol
// ─────────────────────────────────────────────────────────────
// Every message between client ↔ server is a JSON object with a
// mandatory "type" field.  This header defines helpers to build
// and parse those messages.
// ─────────────────────────────────────────────────────────────
#pragma once

#include <nlohmann/json.hpp>
#include <string>

using json = nlohmann::json;

// ── Client → Server message types ───────────────────────────
//   "join"   : { type, name }             – join a room
//   "input"  : { type, dx, dy }           – movement input
//   "attack" : { type }                   – attack action

// ── Server → Client message types ───────────────────────────
//   "welcome"    : { type, id }           – assigned player id
//   "state"      : { type, players }      – full game state
//   "player_left": { type, id }           – a player left
//   "game_over"  : { type, winner }       – game ended

namespace msg {

// ── Builders (server → client) ──────────────────────────────

inline json welcome(uint32_t id) {
    return {{"type", "welcome"}, {"id", id}};
}

inline json game_state(const json& players) {
    return {{"type", "state"}, {"players", players}};
}

inline json player_left(uint32_t id) {
    return {{"type", "player_left"}, {"id", id}};
}

inline json game_over(const std::string& winner) {
    return {{"type", "game_over"}, {"winner", winner}};
}

// ── Parser helpers (client → server) ────────────────────────

inline std::string get_type(const json& j) {
    if (j.contains("type") && j["type"].is_string()) {
        return j["type"].get<std::string>();
    }
    return "";
}

inline std::string get_name(const json& j) {
    if (j.contains("name") && j["name"].is_string()) {
        return j["name"].get<std::string>();
    }
    return "Player";
}

inline double get_dx(const json& j) {
    if (j.contains("dx") && j["dx"].is_number()) {
        return j["dx"].get<double>();
    }
    return 0.0;
}

inline double get_dy(const json& j) {
    if (j.contains("dy") && j["dy"].is_number()) {
        return j["dy"].get<double>();
    }
    return 0.0;
}

} // namespace msg
