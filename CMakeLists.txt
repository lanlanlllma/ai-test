cmake_minimum_required(VERSION 3.20)
project(battle_server LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# ── Dependencies ──────────────────────────────────────────────
find_package(Boost 1.74 REQUIRED COMPONENTS system)
find_package(nlohmann_json 3.9 REQUIRED)
find_package(Threads REQUIRED)

# ── Game Server ───────────────────────────────────────────────
add_executable(battle_server
    server/src/main.cpp
    server/src/server.cpp
    server/src/session.cpp
    server/src/room.cpp
    server/src/game.cpp
)

target_include_directories(battle_server PRIVATE server/include)

target_link_libraries(battle_server PRIVATE
    Boost::system
    nlohmann_json::nlohmann_json
    Threads::Threads
)

# ── Tests ─────────────────────────────────────────────────────
enable_testing()

add_executable(test_message  server/src/test_message.cpp)
target_include_directories(test_message PRIVATE server/include)
target_link_libraries(test_message PRIVATE nlohmann_json::nlohmann_json)
add_test(NAME test_message COMMAND test_message)

add_executable(test_game server/src/test_game.cpp server/src/game.cpp)
target_include_directories(test_game PRIVATE server/include)
target_link_libraries(test_game PRIVATE
    nlohmann_json::nlohmann_json
    Boost::system
    Threads::Threads
)
add_test(NAME test_game COMMAND test_game)
