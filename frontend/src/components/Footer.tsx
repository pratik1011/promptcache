export default function Footer() {
  return (
    <footer>
      <div className="footer-inner">
        <span className="footer-brand">⚡ PromptCache</span>
        <p>© {new Date().getFullYear()} PromptCache — AI cost control gateway</p>
      </div>
    </footer>
  )
}