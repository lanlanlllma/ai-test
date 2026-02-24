// server.hpp  –  WebSocket listener / acceptor
// ─────────────────────────────────────────────────────────────
// Listens on a TCP port, upgrades each connection to WebSocket,
// and spawns a Session for the new player.
// ─────────────────────────────────────────────────────────────
#pragma once

#include "room.hpp"

#include <boost/asio.hpp>
#include <boost/beast.hpp>
#include <memory>
#include <cstdint>

namespace net   = boost::asio;
using     tcp   = net::ip::tcp;

class Server : public std::enable_shared_from_this<Server> {
public:
    Server(net::io_context& ioc, tcp::endpoint endpoint,
           std::shared_ptr<Room> room);

    void start();

private:
    void do_accept();
    void on_accept(boost::beast::error_code ec, tcp::socket socket);

    net::io_context&      ioc_;
    tcp::acceptor         acceptor_;
    std::shared_ptr<Room> room_;
};
