export default function HeroIllustration() {
  return (
    <div className="hero-art" aria-hidden="true">
      <svg width="480" height="400" viewBox="0 0 480 400" fill="none" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id="art-grad" x1="0" y1="0" x2="480" y2="400" gradientUnits="userSpaceOnUse">
            <stop stopColor="#35ad76" />
            <stop offset="0.5" stopColor="#4ade80" />
            <stop offset="1" stopColor="#22d3ee" />
          </linearGradient>
          <linearGradient id="art-grad-2" x1="0" y1="0" x2="480" y2="400" gradientUnits="userSpaceOnUse">
            <stop stopColor="#22d3ee" stopOpacity="0.15" />
            <stop offset="1" stopColor="#35ad76" stopOpacity="0.05" />
          </linearGradient>
          <filter id="glow">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <circle cx="240" cy="200" r="160" fill="url(#art-grad-2)" />

        <circle cx="240" cy="200" r="56" stroke="url(#art-grad)" strokeWidth="2" fill="#0c1b17" />
        <circle cx="240" cy="200" r="40" stroke="url(#art-grad)" strokeWidth="1.5" fill="#0f1f1a" />
        <circle cx="240" cy="200" r="24" stroke="url(#art-grad)" strokeWidth="2" fill="none" filter="url(#glow)" />

        <path d="M233 176l-5 30h12l-3 24 19-35h-12l3-19z" fill="url(#art-grad)" />

        {/* Orbiting nodes */}
        <g>
          <circle cx="360" cy="200" r="18" fill="#0f1f1a" stroke="#4ade80" strokeWidth="1.5" />
          <circle cx="360" cy="200" r="5" fill="#4ade80" filter="url(#glow)" />
          <text x="360" y="230" textAnchor="middle" fill="#91b4a4" fontSize="10" fontWeight="600" letterSpacing="1">Save</text>
        </g>
        <g>
          <circle cx="240" cy="80" r="18" fill="#0f1f1a" stroke="#22d3ee" strokeWidth="1.5" />
          <circle cx="240" cy="80" r="5" fill="#22d3ee" filter="url(#glow)" />
          <text x="240" y="110" textAnchor="middle" fill="#91b4a4" fontSize="10" fontWeight="600" letterSpacing="1">Speed</text>
        </g>
        <g>
          <circle cx="120" cy="200" r="18" fill="#0f1f1a" stroke="#c084fc" strokeWidth="1.5" />
          <circle cx="120" cy="200" r="5" fill="#c084fc" filter="url(#glow)" />
          <text x="120" y="230" textAnchor="middle" fill="#91b4a4" fontSize="10" fontWeight="600" letterSpacing="1">Cache</text>
        </g>
        <g>
          <circle cx="240" cy="320" r="18" fill="#0f1f1a" stroke="#fb923c" strokeWidth="1.5" />
          <circle cx="240" cy="320" r="5" fill="#fb923c" filter="url(#glow)" />
          <text x="240" y="350" textAnchor="middle" fill="#91b4a4" fontSize="10" fontWeight="600" letterSpacing="1">Route</text>
        </g>

        {/* Connection lines */}
        <line x1="240" y1="200" x2="360" y2="200" stroke="url(#art-grad)" strokeWidth="1" strokeDasharray="4 4" opacity="0.3" />
        <line x1="240" y1="200" x2="240" y2="80" stroke="url(#art-grad)" strokeWidth="1" strokeDasharray="4 4" opacity="0.3" />
        <line x1="240" y1="200" x2="120" y2="200" stroke="url(#art-grad)" strokeWidth="1" strokeDasharray="4 4" opacity="0.3" />
        <line x1="240" y1="200" x2="240" y2="320" stroke="url(#art-grad)" strokeWidth="1" strokeDasharray="4 4" opacity="0.3" />

        {/* Floating metric chips */}
        <g transform="translate(50, 70)">
          <rect width="88" height="32" rx="8" fill="#0c1b17" stroke="#315e4c" />
          <circle cx="16" cy="16" r="5" fill="#4ade80" />
          <text x="28" y="21" fill="#edfff5" fontSize="11" fontWeight="600">$0.0021</text>
        </g>
        <g transform="translate(360, 280)">
          <rect width="100" height="32" rx="8" fill="#0c1b17" stroke="#315e4c" />
          <circle cx="16" cy="16" r="5" fill="#22d3ee" />
          <text x="28" y="21" fill="#edfff5" fontSize="11" fontWeight="600">98.4% hit</text>
        </g>

        {/* Animated pulse rings */}
        <circle cx="240" cy="200" r="70" stroke="url(#art-grad)" strokeWidth="1" opacity="0.3" className="pulse-ring" />
        <circle cx="240" cy="200" r="100" stroke="url(#art-grad)" strokeWidth="1" opacity="0.2" className="pulse-ring" style={{ animationDelay: '0.6s' }} />
      </svg>
    </div>
  )
}