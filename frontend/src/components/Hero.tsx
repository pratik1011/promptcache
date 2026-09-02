import HeroIllustration from './HeroIllustration'

interface HeroProps {
  isAuthenticated: boolean
}

export default function Hero({ isAuthenticated }: HeroProps) {
  return (
    <section className="hero" id="hero">
      <div className="hero-content">
        <p className="eyebrow">
          <span className="eyebrow-dot" />
          AI COST CONTROL
        </p>
        <h1>
          Your AI bills are too high.
          <br />
          Fix it in <span className="gradient">one line of code.</span>
        </h1>
        <p className="subtitle">
          PromptCache sits between your app and AI providers like OpenAI and Anthropic. It automatically caches repeated questions, routes cheap requests to cheaper models, and shows you exactly how much you're saving — all with zero code changes.
        </p>
        <div className="hero-actions">
          {isAuthenticated ? (
            <a href="#dashboard" className="btn btn-primary">
              View your dashboard →
            </a>
          ) : (
            <>
              <a href="#onboard" className="btn btn-primary">
                Get started free
              </a>
              <a href="#features" className="btn btn-secondary">
                View dashboard
              </a>
            </>
          )}
        </div>

        <div className="hero-stats">
          <div>
            <strong>Up to 90%</strong>
            <span>Cost reduction on repeated queries</span>
          </div>
          <div>
            <strong>42ms</strong>
            <span>Avg cached response time</span>
          </div>
          <div>
            <strong>One line</strong>
            <span>To integrate with your app</span>
          </div>
        </div>
      </div>
      <HeroIllustration />
    </section>
  )
}