// session.hpp  –  Per‑player WebSocket session
// ─────────────────────────────────────────────────────────────
// Each connected player gets a Session.  It reads JSON messages
// from the client, dispatches them to the Room / Game, and
// provides a send() method for the Room to push state updates.
// ─────────────────────────────────────────────────────────────
#pragma once

#include "room.hpp"

#include <boost/asio.hpp>
#include <boost/beast.hpp>
#include <memory>
#include <string>
#include <deque>
#include <cstdint>

namespace beast = boost::beast;
namespace ws    = beast::websocket;
namespace net   = boost::asio;
using     tcp   = net::ip::tcp;

class Session : public std::enable_shared_from_this<Session> {
public:
    Session(tcp::socket socket, std::shared_ptr<Room> room);

    // Start the WebSocket handshake
    void run();

    // Push a text message to the client (thread‑safe)
    void send(const std::string& msg);

    uint32_t id() const { return id_; }
    void set_id(uint32_t id) { id_ = id; }

private:
    void on_accept(beast::error_code ec);
    void do_read();
    void on_read(beast::error_code ec, std::size_t bytes);
    void handle_message(const std::string& text);
    void do_write();
    void on_write(beast::error_code ec, std::size_t bytes);

    ws::stream<beast::tcp_stream> ws_;
    std::shared_ptr<Room>         room_;
    beast::flat_buffer             buf_;

    uint32_t                       id_ = 0;
    bool                           joined_ = false;

    // Write queue – keeps outgoing messages in order
    std::deque<std::string>        write_queue_;
};
