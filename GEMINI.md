# finauto — Gemini CLI notes

> The finauto app guidance lives in **`CLAUDE.md`** (this folder) — Gemini loads it because the
> workspace `.gemini/settings.json` sets `context.fileName = ["GEMINI.md", "CLAUDE.md"]`. The
> shared workspace rules are in `../CLAUDE.md`, and deep detail is in `README.md` / `plan.md`.
> Read `CLAUDE.md` here as the primary app guide; this file only adds Gemini-specific pointers so
> the two never drift.

## Gemini-specific notes for finauto
- Default extraction provider is **Gemini** (`google-genai`, native PDF input, structured output);
  Claude is the pluggable alternative. This is an app-runtime choice (`--provider` / `.env`),
  independent of which CLI you develop with.
- Workspace commands apply here too — `/valuation-review` and `/llm-extraction` are the most
  relevant for finauto work. Run `/memory show` to confirm both this file and `CLAUDE.md` loaded.

## Non-negotiables (full detail in CLAUDE.md / plan.md)
- Keep the 3 stages decoupled; the `engine/` never imports an LLM SDK or hits the network.
- Hardcoded numbers only on sheets 01/02/03; sheets 04/05 are formula-only; guard every division.
- Validate LLM output against the Pydantic schema (one repair retry); report gaps; never invent values.
- API keys belong in `.env` only — never in tracked files.
