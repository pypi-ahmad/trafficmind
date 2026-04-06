# Notebooks — Colab MCP (Default) & Local Fallback

TrafficMind uses **Google Colab via [colab-mcp](https://github.com/googlecolab/colab-mcp)** as the default notebook runtime so that heavy GPU/CPU workloads run in the cloud instead of consuming local resources.

## Prerequisites

| Requirement | Install |
|---|---|
| Python ≥ 3.12 | Already required by TrafficMind |
| git | `winget install Git.Git` / `brew install git` |
| uv | `pip install uv` |
| VS Code + GitHub Copilot Chat | Extensions marketplace |

## How Colab MCP Works

1. VS Code reads `.vscode/mcp.json` and starts the `colab-mcp` server automatically.
2. When an AI agent needs to execute code, it calls the `open_colab_browser_connection` tool.
3. A Google Colab scratch notebook opens in your browser.
4. A WebSocket bridge connects VS Code ↔ Colab so the agent can create cells, execute code, and read outputs — all running on Colab's free GPU/TPU runtime.

No API keys or tokens are needed; the connection is established through your browser session.

## Using Colab MCP (Default)

The workspace is pre-configured — no manual setup required.

1. Open the project in VS Code.
2. Ensure GitHub Copilot Chat is active.
3. Ask the agent to run notebook code (e.g. "Run the detection pipeline on a test image").
4. The agent will call `open_colab_browser_connection`. A Colab tab opens in your browser.
5. Click **Connect** in the Colab UI when prompted.
6. The agent creates cells, executes code, and retrieves results — all on Colab.

### Colab MCP Tips

- The first connection takes a few seconds while the WebSocket handshake completes.
- If the Colab session disconnects (idle timeout), the agent will re-prompt you to reconnect.
- Colab free tier has usage limits; for sustained workloads consider Colab Pro.
- Uploaded files or pip-installed packages persist only for the Colab session lifetime.

## Local Fallback

If you prefer to execute notebooks locally (e.g. for offline work or to use your own GPU):

### Option A: Disable Colab MCP per-session

1. Open the Command Palette (`Ctrl+Shift+P`).
2. Run **MCP: List Servers**.
3. Toggle off `colab-mcp`.

The agent will fall back to any locally configured Jupyter kernel.

### Option B: Use local Jupyter directly

```bash
# install Jupyter in the project venv
pip install jupyter ipykernel

# register the venv as a Jupyter kernel
python -m ipykernel install --user --name trafficmind --display-name "TrafficMind (local)"

# launch Jupyter (optional — VS Code can use the kernel directly)
jupyter lab
```

Then open or create `.ipynb` files in VS Code and select the **TrafficMind (local)** kernel.

### Option C: Remove Colab MCP from workspace config

Delete or comment out the `colab-mcp` entry in `.vscode/mcp.json`:

```jsonc
{
  "servers": {
    // "colab-mcp": { ... }
  }
}
```

## Supported MCP Clients

Colab MCP works with any client that supports `notifications/tools/list_changed`:

- **VS Code** (GitHub Copilot Chat) — configured via `.vscode/mcp.json` ✅
- **Claude Code** — configure in `~/.claude/claude_code_config.json`
- **Gemini CLI** — configure in `~/.gemini/settings.json`
- **Windsurf** — configure in `~/.codeium/windsurf/mcp_config.json`

## Troubleshooting

| Symptom | Fix |
|---|---|
| `uvx: command not found` | Install uv: `pip install uv` |
| Colab tab opens but never connects | Check browser pop-up blocker; ensure you're signed into Google |
| "Timeout while waiting for user to connect" | The 60-second connection window expired — retry the tool call |
| Agent ignores colab-mcp and uses local kernel | Ensure `.vscode/mcp.json` is present and the server is enabled |
| Slow cell execution on Colab free tier | Switch to Colab Pro or use the local fallback |
