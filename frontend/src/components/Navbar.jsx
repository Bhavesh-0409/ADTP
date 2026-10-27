import React from "react";

export default function Navbar({ activeTab, setActiveTab, apiOnline }) {
  const tabs = [
    { id: "replay", label: "Replay" },
    { id: "sidebyside", label: "Side-by-Side" },
    { id: "results", label: "Results" },
    { id: "howitworks", label: "How it works" },
  ];

  return (
    <header className="app-header">
      <div className="header-inner">
        <div className="brand">
          <div className="brand-mark">A</div>
          <div><div className="brand-name">ADTP</div><div className="brand-tagline">Adaptive Data Transport Protocol</div></div>
        </div>
        <nav className="tabs">
          {tabs.map((tab) => {
            const isActive = activeTab === tab.id;
            return (
              <button className={`tab ${isActive ? "active" : ""}`} key={tab.id} onClick={() => setActiveTab(tab.id)}>{tab.label}</button>
            );
          })}
        </nav>
        <div className={`api-status ${apiOnline ? "online" : ""}`}><span />{apiOnline ? "API online" : "API offline"}</div>
      </div>
    </header>
  );
}
