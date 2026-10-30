# CyberTown Godot 4 client

This directory is a real Godot 4 project skeleton. Godot owns the 2D scene, grid, buildings, player/NPC drawing and keyboard input. The FastAPI service in `../backend` remains the source of truth for state, memory, affinity and dialogue.

## Run locally

1. Start the Python service from the repository root.
2. Open this folder in Godot 4.x.
3. Run `main.tscn`.

The default backend URL is `http://127.0.0.1:8000/`. For an AUP proxy deployment, change the exported `base_url` in the Godot project to the proxy URL that exposes the FastAPI service.

## Export for the browser

Use Godot's Web export preset to generate the HTML5/WebAssembly files, then serve the generated directory from the same AUP server or a static host. Keep the Python backend on the server so API keys remain private. The current script uses HTTP requests; a WebSocket transport can be added later for token streaming and live world events.
