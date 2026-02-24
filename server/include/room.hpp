// room.hpp  –  Room management
// ─────────────────────────────────────────────────────────────
// A Room groups sessions together and runs the game‑loop tick
// timer.  For simplicity we keep a single global room for now;
// expanding to multiple rooms is straightforward.
// ─────────────────────────────────────────────────────────────
#pragma once

#include "game.hpp"

#include <boost/asio.hpp>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <cstdint>

namespace net = boost::asio;

// Forward declaration – sessions register themselves with the
// room so the room can broadcast state updates.
class Session;

class Room : public std::enable_shared_from_this<Room> {
public:
    static constexpr int TICK_RATE = 30; // Hz

    explicit Room(net::io_context& ioc);

    // Session lifecycle
    void join(std::shared_ptr<Session> s, const std::string& name);
    void leave(uint32_t id);

    // Relay client inputs to the game
    void on_input(uint32_t id, double dx, double dy);
    void on_attack(uint32_t id);

    // Access the game (for tests)
    Game& game() { return game_; }

private:
    void start_tick();
    void on_tick(boost::system::error_code ec);
    void broadcast(const std::string& msg);

    net::io_context&       ioc_;
    net::steady_timer      timer_;
    Game                   game_;

    std::mutex             mtx_;
    uint32_t               next_id_ = 1;
    std::unordered_map<uint32_t, std::shared_ptr<Session>> sessions_;
};
