# PromptCache

A provider-neutral AI gateway that reduces inference spend through similarity caching, complexity-based model routing, and transparent savings telemetry.

## MVP status

- OpenAI-compatible client endpoint: `POST /v1/chat/completions`
- SSE streaming for `stream:true` (passthrough; cache bypassed; usage recorded)
- Adapters for OpenAI-compatible providers, Anthropic, and generic JSON APIs
- Exact and lexical-semantic similarity cache with tenant namespaces and TTL
- Complexity rules that route inexpensive prompts to inexpensive providers
- Per-request cost attribution and a live savings dashboard
- Zero-dependency local demo mode

## Run locally

Backend demo mode requires Python 3.12 or newer.

```bash
python run.py
```

Open `http://localhost:8787` for the built-in demo page. To run the React dashboard instead (requires Node.js 20 or newer):

```bash
cd frontend
npm install
npm run dev
```

Then generate demo traffic:

```bash
curl -X POST http://localhost:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Summarize our refund policy"}]}'
```

Send the same prompt again to see a cache hit. For production, copy `.env.example` into your deployment environment and configure `PROVIDERS_JSON`, `ROUTES_JSON`, and `ADMIN_API_KEY`.


## Deploy to Render

A Render Blueprint is included at `render.yaml`. It provisions the API, React/Nginx dashboard, Postgres, and a private Render Key Value instance. Follow the complete setup and smoke-test guide in [`docs/render-deployment.md`](docs/render-deployment.md).

## Universal provider contract

Clients always receive an OpenAI-style response, regardless of the upstream vendor. Configure providers with one of these adapter types:

- `openai-compatible`: OpenAI, Groq, Together, Fireworks, OpenRouter, vLLM, Ollama, and other compatible servers.
- `anthropic`: Native Anthropic Messages API translation.
- `generic`: Any JSON endpoint accepting the normalized request. Use `endpoint`, `headers`, and dot-separated `responsePath` to identify returned text.

Requests can allow automatic routing or set `provider` explicitly. Set `cache_namespace` per customer/project to prevent cross-tenant cache leakage, and `cache: false` for sensitive or non-deterministic prompts.

## Product implementation plan

### Phase 1 — Validate (weeks 1–2)

Target AI SaaS teams spending at least $2,000/month. Recruit 5 design partners, proxy one non-sensitive workload each, and measure cacheability, latency, answer acceptance, and gross savings. The success gate is 3 customers seeing at least 20% savings with no measurable quality regression.

### Phase 2 — Production MVP (weeks 3–6)

Replace the JSON store with Postgres and a vector extension, add API-key tenants, encrypted bring-your-own-provider credentials, streaming, rate limits, retries/circuit breakers, PII redaction, and configurable cache policies. Add real provider price catalogs and exportable invoices/usage reports.

### Phase 3 — Sell (weeks 7–10)

Offer a free local estimator, usage-based pricing (for example 10–20% of verified savings with a monthly cap), and a 14-day trial. Publish anonymized before/after cost graphs and integrations for popular AI SDKs. Sell the measurable outcome—lower inference cost—not “AI infrastructure.”

### Phase 4 — Defensibility

Learn routing policies from each tenant’s quality feedback, add response-quality evals, prompt-version-aware invalidation, regional data residency, audit logs, and enterprise SSO. The defensible asset is a trustworthy per-workload cost/quality routing policy, not the basic proxy.

## Important MVP limits

The local similarity matcher is deliberately dependency-free and lexical; production semantic matching should use embeddings plus a vector index. The file store is for local evaluation only, writes are not concurrency-safe, generic providers may need custom request transforms, tool calls are not yet normalized. Streaming is an SSE passthrough for OpenAI-compatible providers: `stream:true` bypasses the cache in both directions while usage is still recorded from the accumulated response text.

## Semantic matching upgrade

The current cache uses a dependency-free lexical similarity fallback. The next production adapter should implement an embedding interface and vector repository behind the existing cache module, with PostgreSQL/pgvector as the default backend. This keeps provider selection and gateway logic unchanged while enabling true intent matching.
