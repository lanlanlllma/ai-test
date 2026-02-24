# ⚔️ WebSocket Multiplayer 2D Battle Arena

A real-time multiplayer 2D battle game built with **C++20** and **Boost.Beast** (WebSocket) as a learning project for backend game-server architecture.

## Architecture

```
┌─────────────┐  WebSocket  ┌──────────────────────────────────┐
│  Browser     │◄──────────►│  Server (Authoritative)          │
│  HTML+Canvas │            │                                  │
│              │  "input"►  │  Session ──► Room ──► Game       │
│              │  ◄"state"  │    │                   │         │
│              │            │    │  join/leave        │ tick()  │
│              │            │    │                   ▼         │
│              │            │    └──── broadcast ◄── snapshot  │
└─────────────┘            └──────────────────────────────────┘
```

### Key Design Decisions

| Concept | Design |
|---|---|
| **Server model** | Authoritative – the server owns all game state; clients send inputs only |
| **Networking** | WebSocket via Boost.Beast (built on Boost.Asio) |
| **Game loop** | Fixed-rate tick at 30 Hz; each tick advances physics & broadcasts state |
| **Room** | Players share a Room; the Room owns the Game and the tick timer |
| **Session** | One per WebSocket connection; reads messages, relays inputs to Room |
| **Message format** | JSON (`nlohmann/json`) for clarity |

### Message Protocol

**Client → Server**

| Type | Fields | Description |
|------|--------|-------------|
| `join` | `name` | Join the room |
| `input` | `dx`, `dy` | Movement direction (-1 to 1) |
| `attack` | – | Melee attack |

**Server → Client**

| Type | Fields | Description |
|------|--------|-------------|
| `welcome` | `id` | Assigned player ID |
| `state` | `players[]` | Full snapshot each tick |
| `player_left` | `id` | A player disconnected |
| `game_over` | `winner` | Last player standing |

## Prerequisites

- Ubuntu (tested on 24.04)
- GCC 13+ (C++20)
- CMake 3.20+
- Boost 1.74+ (`libboost-all-dev`)
- nlohmann-json (`nlohmann-json3-dev`)

```bash
sudo apt-get install build-essential cmake libboost-all-dev nlohmann-json3-dev
```

## Build & Run

```bash
# Build
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)

# Run tests
cd build && ctest --output-on-failure && cd ..

# Start server (default port 9002)
./build/battle_server

# Or specify a port
./build/battle_server 8080
```

Then open `frontend/index.html` in your browser (multiple tabs for multiplayer).

## Project Structure

```
.
├── CMakeLists.txt              # Build configuration
├── frontend/
│   └── index.html              # HTML + Canvas game client
├── server/
│   ├── include/
│   │   ├── message.hpp         # JSON message protocol helpers
│   │   ├── player.hpp          # Player state struct
│   │   ├── game.hpp            # Authoritative game simulation
│   │   ├── room.hpp            # Room management + tick loop
│   │   ├── session.hpp         # Per-player WebSocket session
│   │   └── server.hpp          # TCP acceptor / WebSocket listener
│   └── src/
│       ├── main.cpp            # Entry point
│       ├── game.cpp            # Game logic implementation
│       ├── room.cpp            # Room implementation
│       ├── session.cpp         # Session implementation
│       ├── server.cpp          # Server implementation
│       ├── test_message.cpp    # Message unit tests
│       └── test_game.cpp       # Game logic unit tests
└── README.md
```

## How It Works (Step by Step)

### Phase 1 – Connection
1. The **Server** listens on a TCP port using `boost::asio::ip::tcp::acceptor`.
2. When a browser connects, the connection is upgraded to WebSocket via `boost::beast::websocket::stream`.
3. A **Session** object is created to manage the connection's lifecycle.

### Phase 2 – Joining a Room
4. The client sends `{"type":"join","name":"Alice"}`.
5. The Session asks the **Room** to add the player; the Room assigns an ID and creates a **Player** in the **Game**.
6. The server responds with `{"type":"welcome","id":1}`.

### Phase 3 – Game Loop (Tick)
7. The Room runs a 30 Hz tick timer via `boost::asio::steady_timer`.
8. Each tick calls `Game::tick(dt)`:
   - Applies movement from pending inputs
   - Processes attacks (range check, damage)
   - Updates cooldown timers
9. After `tick()`, the Room calls `Game::snapshot()` to get the full state as JSON.
10. The snapshot is **broadcast** to every Session in the Room.

### Phase 4 – Client Rendering
11. The browser receives the `state` message 30 times per second.
12. The Canvas draws each player as a colored circle with name and HP bar.
13. Player inputs (WASD / arrows / space) are sent back to the server every animation frame.

### Phase 5 – Win Condition
14. When a player's HP reaches 0 and only one player remains alive, the server broadcasts `game_over`.
