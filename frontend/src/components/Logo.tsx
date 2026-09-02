export default function Logo({ size = 40 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="PromptCache logo"
    >
      <defs>
        <linearGradient id="logo-grad" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
          <stop stopColor="#35ad76" />
          <stop offset="0.5" stopColor="#4ade80" />
          <stop offset="1" stopColor="#22d3ee" />
        </linearGradient>
      </defs>
      <rect
        width="48"
        height="48"
        rx="12"
        fill="#0c1b17"
        stroke="url(#logo-grad)"
        strokeWidth="2"
      />
      <path
        d="M14 20l4-4v16l-4-4M34 28l-4 4V16l4 4M22 18l4 12M18 24h12"
        stroke="url(#logo-grad)"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="34" cy="14" r="3" fill="#22d3ee" />
    </svg>
  )
}