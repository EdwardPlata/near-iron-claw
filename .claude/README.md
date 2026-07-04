# Claude Code toolkit for near-iron-claw

Curated agents/skills for building on **NEAR AI's IronClaw** (open-source Rust "Agent OS")
against the hosted **NEAR AI Cloud** endpoint. See [`../CONNECTING.md`](../CONNECTING.md) for
the connection/`.env` setup.

## Project-scoped agents (`.claude/agents/`)

Copied from the global library so the toolkit is version-controlled with the repo.

| Agent | Why it fits |
|-------|-------------|
| `ai-engineer`       | Build the LLM/agent-powered client — RAG, orchestration, tool loops |
| `llm-architect`     | Endpoint/model-routing architecture, inference config, prompt systems |
| `mcp-developer`     | IronClaw tools are MCP/WASM — build & integrate MCP servers |
| `backend-developer` | Service/API layer that calls the hosted NEAR AI Cloud endpoint |
| `api-designer`      | Design the client/integration surface |
| `security-auditor`  | IronClaw is security-first — audit secret handling, `.env`, prompt-injection |
| `prompt-engineer`   | Agent/system-prompt design |

**Optional add-ons** (copy from `~/.claude/agents/` if the direction firms up):
- `blockchain-developer` — NEAR ecosystem work
- `rust-engineer` + `postgres-pro` — only if IronClaw is later built from source (Rust + pgvector)

## Recommended skills (global — invoke with `/`)

- `mcp-builder` — scaffold MCP servers/tools for IronClaw
- `skill-creator` — author project-specific skills
- `deep-research` — research NEAR AI / IronClaw specifics
- `openai-automation` — OpenAI-compatible calls (matches the NEAR AI Cloud API shape)
- Dev-loop built-ins: `code-review`, `security-review`, `verify`, `run`
