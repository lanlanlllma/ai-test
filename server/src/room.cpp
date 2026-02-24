// room.cpp  –  Room management + tick loop
#include "room.hpp"
#include "session.hpp"
#include "message.hpp"

#include <iostream>

using namespace std::chrono_literals;

// ─────────────────────────────────────────────────────────────

Room::Room(net::io_context& ioc)
    : ioc_(ioc)
    , timer_(ioc)
{}

// ── Session lifecycle ────────────────────────────────────────

void Room::join(std::shared_ptr<Session> s, const std::string& name) {
    uint32_t id;
    {
        std::lock_guard lock(mtx_);
        id = next_id_++;
        s->set_id(id);
        sessions_[id] = s;
    }

    game_.add_player(id, name);

    // Send the player their id
    s->send(msg::welcome(id).dump());

    std::cout << "[Room] Player " << id
              << " (" << name << ") joined.\n";

    // Start tick loop if this is the first player
    if (game_.player_count() == 1) {
        start_tick();
    }
}

void Room::leave(uint32_t id) {
    {
        std::lock_guard lock(mtx_);
        sessions_.erase(id);
    }

    game_.remove_player(id);
    broadcast(msg::player_left(id).dump());

    std::cout << "[Room] Player " << id << " left.\n";

    // Stop ticking if empty
    if (game_.player_count() == 0) {
        timer_.cancel();
    }
}

// ── Relay inputs ─────────────────────────────────────────────

void Room::on_input(uint32_t id, double dx, double dy) {
    game_.set_input(id, dx, dy);
}

void Room::on_attack(uint32_t id) {
    game_.set_attack(id);
}

// ── Tick loop ────────────────────────────────────────────────

void Room::start_tick() {
    timer_.expires_after(
        std::chrono::milliseconds(1000 / TICK_RATE));
    timer_.async_wait(
        [self = shared_from_this()](boost::system::error_code ec) {
            self->on_tick(ec);
        });
}

void Room::on_tick(boost::system::error_code ec) {
    if (ec) return; // timer cancelled or error

    double dt = 1.0 / TICK_RATE;

    game_.tick(dt);

    // Build & broadcast the state snapshot
    auto state = msg::game_state(game_.snapshot());
    broadcast(state.dump());

    // Check for a winner
    std::string winner = game_.check_winner();
    if (!winner.empty()) {
        broadcast(msg::game_over(winner).dump());
    }

    // Schedule next tick (only if players remain)
    if (game_.player_count() > 0) {
        start_tick();
    }
}

// ── Broadcast ────────────────────────────────────────────────

void Room::broadcast(const std::string& msg) {
    std::lock_guard lock(mtx_);
    for (auto& [id, s] : sessions_) {
        s->send(msg);
    }
}
