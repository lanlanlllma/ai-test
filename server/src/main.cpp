// main.cpp  –  Entry point
// ─────────────────────────────────────────────────────────────
// Usage:  ./battle_server [port]        (default port 9002)
// ─────────────────────────────────────────────────────────────
#include "server.hpp"
#include "room.hpp"

#include <boost/asio.hpp>
#include <iostream>
#include <cstdlib>
#include <thread>
#include <vector>

int main(int argc, char* argv[]) {
    uint16_t port = 9002;
    if (argc >= 2) {
        port = static_cast<uint16_t>(std::atoi(argv[1]));
    }

    // Use one thread per CPU core
    auto const threads = std::max<int>(1,
        static_cast<int>(std::thread::hardware_concurrency()));

    net::io_context ioc{threads};

    // Create the shared room (single room for simplicity)
    auto room = std::make_shared<Room>(ioc);

    // Create and start the listener
    auto server = std::make_shared<Server>(
        ioc,
        tcp::endpoint(net::ip::make_address("0.0.0.0"), port),
        room);
    server->start();

    std::cout << "=== Battle Server listening on port "
              << port << " ===\n"
              << "Open frontend/index.html in your browser.\n";

    // Run the io_context on multiple threads
    std::vector<std::thread> workers;
    workers.reserve(threads - 1);
    for (int i = 0; i < threads - 1; ++i) {
        workers.emplace_back([&ioc] { ioc.run(); });
    }
    ioc.run(); // main thread also participates

    for (auto& t : workers) t.join();

    return 0;
}
