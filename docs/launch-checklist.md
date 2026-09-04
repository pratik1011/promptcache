# Production launch checklist

## Before deployment

- Set `APP_ENV=production` and strong values for `JWT_SECRET`, `ADMIN_API_KEY`, and `API_KEY_ENC_MASTER_KEY`.
- Set `CORS_ALLOW_ORIGINS` to the final HTTPS dashboard origin.
- Set `DASHBOARD_URL` to the same final HTTPS dashboard origin.
- Confirm `/health/ready` returns `{ok: true}` after deployment.
- Keep Postgres and Redis private; do not expose their ports publicly.

## Revenue and email

- Complete [Stripe setup](stripe-setup.md) with test-mode credentials first.
- Add a Resend API key and verified sending domain before enabling automatic invitations.
- Test checkout, webhook plan updates, invitation creation, and invitation acceptance with a separate test account.

## Go live

- Buy a domain, enable HTTPS, and update the origin settings.
- Create a backup policy for Postgres and verify a restore procedure.
- Add uptime monitoring for `/health/ready` and alert on failures.
- Invite a small beta group before announcing publicly.
