# CyberTown Godot 4 client

This directory is a real Godot 4 project skeleton. Godot owns the 2D scene, grid, buildings, player/NPC drawing and keyboard input. The FastAPI service in `../backend` remains the source of truth for state, memory, affinity and dialogue.

## Run locally

1. Start the Python service from the repository root.
2. Open this folder in Godot 4.x.
3. Run `main.tscn`.

The default backend URL is `http://127.0.0.1:8000/`. For an AUP proxy deployment, change the exported `base_url` in the Godot project to the proxy URL that exposes the FastAPI service.

## Export for the browser

The repository includes a GitHub Actions workflow at `.github/workflows/godot-web.yml`. It exports a real Godot Web build with the official Godot CI image, so the AUP server does not spend quota downloading the large export template archive. After downloading the artifact, place its files in `godot_web/` beside `backend/`; the FastAPI service will serve them at `/godot/`.

Keep the Python backend on the server so API keys remain private. The Godot client uses HTTP requests; a WebSocket transport can be added later for token streaming and live world events.
