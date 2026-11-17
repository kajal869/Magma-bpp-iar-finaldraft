export default function Header() {
  return (
    <header className="topbar">
      <div className="brand">
        <img src="/magma-logo.png" alt="Magma General Insurance" />
        <span className="brand-sep" />
        <span className="brand-title">Policy Draft Studio</span>
      </div>
      <span className="pill pill-demo">Internal demo</span>
    </header>
  );
}
