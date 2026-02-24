// session.cpp  –  Per‑player WebSocket session
#include "session.hpp"
#include "message.hpp"

#include <iostream>

// ─────────────────────────────────────────────────────────────

Session::Session(tcp::socket socket, std::shared_ptr<Room> room)
    : ws_(std::move(socket))
    , room_(std::move(room))
{}

void Session::run() {
    // Set WebSocket options
    ws_.set_option(ws::stream_base::timeout::suggested(
        beast::role_type::server));

    ws_.set_option(ws::stream_base::decorator(
        [](ws::response_type& res) {
            res.set(beast::http::field::server, "BattleServer");
        }));

    // Limit max incoming message size to prevent memory abuse
    ws_.read_message_max(4096);

    // Accept the WebSocket handshake
    ws_.async_accept(
        [self = shared_from_this()](beast::error_code ec) {
            self->on_accept(ec);
        });
}

void Session::on_accept(beast::error_code ec) {
    if (ec) {
        std::cerr << "[Session] accept error: " << ec.message() << "\n";
        return;
    }
    do_read();
}

// ── Reading ──────────────────────────────────────────────────

void Session::do_read() {
    ws_.async_read(buf_,
        [self = shared_from_this()](beast::error_code ec,
                                    std::size_t bytes) {
            self->on_read(ec, bytes);
        });
}

void Session::on_read(beast::error_code ec, std::size_t /*bytes*/) {
    if (ec) {
        if (ec != ws::error::closed) {
            std::cerr << "[Session] read error: " << ec.message() << "\n";
        }
        if (joined_) {
            room_->leave(id_);
        }
        return;
    }

    std::string text = beast::buffers_to_string(buf_.data());
    buf_.consume(buf_.size());

    handle_message(text);
    do_read(); // continue reading
}

void Session::handle_message(const std::string& text) {
    json j;
    try {
        j = json::parse(text);
    } catch (const json::exception&) {
        return; // ignore malformed messages
    }

    std::string type = msg::get_type(j);

    if (type == "join") {
        if (!joined_) {
            std::string name = msg::get_name(j);
            // Limit name length to prevent abuse
            if (name.size() > 20) name = name.substr(0, 20);
            room_->join(shared_from_this(), name);
            joined_ = true;
        }
    } else if (type == "input") {
        if (joined_) {
            room_->on_input(id_, msg::get_dx(j), msg::get_dy(j));
        }
    } else if (type == "attack") {
        if (joined_) {
            room_->on_attack(id_);
        }
    }
}

// ── Writing (thread‑safe queue) ─────────────────────────────

void Session::send(const std::string& msg) {
    // Post into the strand so writes are serialized
    net::post(ws_.get_executor(),
        [self = shared_from_this(), msg]() {
            // Drop messages if the client is too slow
            if (self->write_queue_.size() >= 64) return;
            bool idle = self->write_queue_.empty();
            self->write_queue_.push_back(msg);
            if (idle) self->do_write();
        });
}

void Session::do_write() {
    if (write_queue_.empty()) return;

    ws_.text(true);
    ws_.async_write(net::buffer(write_queue_.front()),
        [self = shared_from_this()](beast::error_code ec,
                                    std::size_t bytes) {
            self->on_write(ec, bytes);
        });
}

void Session::on_write(beast::error_code ec, std::size_t /*bytes*/) {
    if (ec) {
        std::cerr << "[Session] write error: " << ec.message() << "\n";
        return;
    }

    write_queue_.pop_front();
    do_write(); // drain the queue
}
