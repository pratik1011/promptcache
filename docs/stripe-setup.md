# Stripe launch setup

PromptCache is ready for Stripe subscriptions. Configure it in test mode first.

1. In Stripe, create recurring monthly Prices for Startup ($39), Growth ($99), and Scale ($299).
2. Add a webhook endpoint at `https://YOUR_APP_DOMAIN/v1/billing/webhook`.
3. Subscribe it to `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, and `customer.subscription.deleted`.
4. Add the following values to the production environment, never to frontend code:

```env
STRIPE_SECRET_KEY=sk_test_or_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_STARTUP=price_...
STRIPE_PRICE_GROWTH=price_...
STRIPE_PRICE_SCALE=price_...
DASHBOARD_URL=https://YOUR_APP_DOMAIN
```

5. Create a test account, complete checkout, and confirm the account plan changes after Stripe delivers the webhook.
6. Use the Billing Portal in Stripe to enable customer self-service for payment methods, invoices, cancellations, and plan changes.

Use Stripe test keys until checkout, cancellation, and webhook updates have all been tested. Switch to live keys only after the domain and HTTPS deployment are ready.
