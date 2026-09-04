# Free public-pilot deployment

This is a zero-cost MVP path, not a permanent high-availability production architecture. It is appropriate for early users and validating demand.

## Architecture

```text
Browser -> Cloudflare Pages (React dashboard)
                  |
                  v
          Render free web service (FastAPI)
                  |                 |
                  v                 v
           Neon Postgres       Upstash Redis
```

Cloudflare Pages serves the dashboard. Render runs the existing Docker API and migrations. Neon holds durable Postgres data; Upstash provides Redis.

## Create data stores

1. Create a Neon project near your users and copy its pooled Postgres connection URL.
2. Create one Upstash Redis database in the nearest region and copy its TLS Redis URL.
3. Keep both values private. They belong only in Render environment variables, never in VITE frontend values.

The free plans are adequate for a pilot: Neon includes 0.5 GB and 100 CU-hours per project each month, while Upstash includes 256 MB and 500K Redis commands per month. See [Neon pricing](https://neon.com/pricing) and [Upstash pricing](https://upstash.com/pricing/redis).

## Deploy the API on Render

1. Push this repository to GitHub.
2. In Render, create a Blueprint from the repository. It uses `render.yaml` and creates `promptcache-api` on the free plan.
3. Set these Render environment variables:

   - `DATABASE_URL`: Neon connection string.
   - `REDIS_URL`: Upstash TLS connection string.
   - `API_KEY_ENC_MASTER_KEY`: generate a Fernet key locally with the command in `.env.example`.
   - `CORS_ALLOW_ORIGINS`: your exact Pages address, for example `https://promptcache.pages.dev`.
   - `DASHBOARD_URL`: that same Pages address.

4. Deploy and wait for `GET /health/ready` to return a successful response.

Do not change `API_KEY_ENC_MASTER_KEY` after provider credentials have been stored: it encrypts them at rest.

## Deploy the dashboard on Cloudflare Pages

1. In Cloudflare Workers and Pages, create a Pages project from the same GitHub repository.
2. Set **Root directory** to `frontend`.
3. Set **Build command** to `npm run build` and **Build output directory** to `dist`.
4. Set production build variable `VITE_API_URL` to the public Render API URL, such as `https://promptcache-api.onrender.com`.
5. Deploy, then copy the resulting Pages URL into Render’s `CORS_ALLOW_ORIGINS` and `DASHBOARD_URL` values.
6. Redeploy the API once after setting those values.

`_redirects` keeps React routes working on direct visits. `_headers` adds browser hardening and immutable caching for versioned Vite assets.

## Before inviting users

1. Create a test account in a private browser window.
2. Verify login, workspace creation, invitations, and dashboard metrics.
3. Verify `https://YOUR_RENDER_API/health/ready` returns success.
4. Confirm the browser console has no CORS errors.
5. Create a Neon restore point or export before inviting real users.
