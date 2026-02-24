// server.cpp  –  WebSocket listener / acceptor
#include "server.hpp"
#include "session.hpp"

#include <iostream>

// ─────────────────────────────────────────────────────────────

Server::Server(net::io_context& ioc, tcp::endpoint endpoint,
               std::shared_ptr<Room> room)
    : ioc_(ioc)
    , acceptor_(ioc)
    , room_(std::move(room))
{
    boost::beast::error_code ec;

    acceptor_.open(endpoint.protocol(), ec);
    if (ec) { std::cerr << "open: " << ec.message() << "\n"; return; }

    acceptor_.set_option(net::socket_base::reuse_address(true), ec);
    if (ec) { std::cerr << "reuse_address: " << ec.message() << "\n"; return; }

    acceptor_.bind(endpoint, ec);
    if (ec) { std::cerr << "bind: " << ec.message() << "\n"; return; }

    acceptor_.listen(net::socket_base::max_listen_connections, ec);
    if (ec) { std::cerr << "listen: " << ec.message() << "\n"; return; }
}

void Server::start() {
    do_accept();
}

void Server::do_accept() {
    acceptor_.async_accept(
        [self = shared_from_this()](boost::beast::error_code ec,
                                    tcp::socket socket) {
            self->on_accept(ec, std::move(socket));
        });
}

void Server::on_accept(boost::beast::error_code ec, tcp::socket socket) {
    if (ec) {
        std::cerr << "[Server] accept error: " << ec.message() << "\n";
    } else {
        std::cout << "[Server] New connection from "
                  << socket.remote_endpoint() << "\n";

        auto session = std::make_shared<Session>(
            std::move(socket), room_);
        session->run();
    }

    do_accept(); // keep accepting
}
