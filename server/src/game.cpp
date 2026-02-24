// game.cpp  –  Authoritative game simulation
#include "game.hpp"
#include <algorithm>
#include <cmath>

// ── Player management ───────────────────────────────────────

void Game::add_player(uint32_t id, const std::string& name) {
    std::lock_guard lock(mtx_);

    Player p;
    p.id   = id;
    p.name = name;

    // Spread players across the arena so they don't overlap
    double offset = static_cast<double>(id % 4);
    p.x = 100.0 + offset * 200.0;
    p.y = 100.0 + offset * 100.0;

    // Clamp within arena
    p.x = std::clamp(p.x, 0.0, ARENA_W);
    p.y = std::clamp(p.y, 0.0, ARENA_H);

    players_[id] = p;
}

void Game::remove_player(uint32_t id) {
    std::lock_guard lock(mtx_);
    players_.erase(id);
}

// ── Input ───────────────────────────────────────────────────

void Game::set_input(uint32_t id, double dx, double dy) {
    std::lock_guard lock(mtx_);
    if (auto it = players_.find(id); it != players_.end()) {
        // Normalize so diagonal movement isn't faster
        double len = std::sqrt(dx * dx + dy * dy);
        if (len > 1.0) { dx /= len; dy /= len; }
        it->second.dx = dx;
        it->second.dy = dy;
    }
}

void Game::set_attack(uint32_t id) {
    std::lock_guard lock(mtx_);
    if (auto it = players_.find(id); it != players_.end()) {
        if (it->second.attack_cooldown <= 0.0) {
            it->second.attacking = true;
        }
    }
}

// ── Tick ─────────────────────────────────────────────────────

void Game::tick(double dt) {
    std::lock_guard lock(mtx_);

    // 1) Move every player
    for (auto& [id, p] : players_) {
        p.x += p.dx * p.speed * dt;
        p.y += p.dy * p.speed * dt;

        // Keep inside the arena
        p.x = std::clamp(p.x, 0.0, ARENA_W);
        p.y = std::clamp(p.y, 0.0, ARENA_H);
    }

    // 2) Process attacks
    for (auto& [aid, attacker] : players_) {
        if (!attacker.attacking) continue;

        for (auto& [did, defender] : players_) {
            if (aid == did) continue;

            double dx = attacker.x - defender.x;
            double dy = attacker.y - defender.y;
            double dist = std::sqrt(dx * dx + dy * dy);

            if (dist < ATTACK_RANGE) {
                defender.hp -= ATTACK_DAMAGE;
                if (defender.hp < 0) defender.hp = 0;
            }
        }

        attacker.attacking = false;
        attacker.attack_cooldown = ATTACK_COOLDOWN_SEC;
    }

    // 3) Cool‑down timers
    for (auto& [id, p] : players_) {
        if (p.attack_cooldown > 0.0) {
            p.attack_cooldown -= dt;
        }
    }
}

// ── Snapshot ─────────────────────────────────────────────────

nlohmann::json Game::snapshot() const {
    std::lock_guard lock(mtx_);
    nlohmann::json arr = nlohmann::json::array();
    for (const auto& [id, p] : players_) {
        arr.push_back(p.to_json());
    }
    return arr;
}

// ── Winner check ─────────────────────────────────────────────

std::string Game::check_winner() const {
    std::lock_guard lock(mtx_);
    if (players_.size() < 2) return "";

    std::vector<const Player*> alive;
    for (const auto& [id, p] : players_) {
        if (p.hp > 0) alive.push_back(&p);
    }

    if (alive.size() == 1) return alive[0]->name;
    return "";
}

std::size_t Game::player_count() const {
    std::lock_guard lock(mtx_);
    return players_.size();
}
