import { useState } from "react";
import ChatWindow from "./components/ChatWindow";
import DataManagement from "./components/DataManagement";

type View = "chat" | "data";

const NAV: { id: View; label: string }[] = [
  { id: "chat", label: "Chat" },
  { id: "data", label: "Data Management" },
];

export default function App() {
  const [view, setView] = useState<View>(location.hash === "#data" ? "data" : "chat");
  const select = (v: View) => {
    setView(v);
    location.hash = v === "data" ? "data" : "";
  };
  return (
    <div className="app">
      <aside className="sidebar">
        <h1>Rivet KAG</h1>
        <nav>
          {NAV.map((n) => (
            <button key={n.id} className={view === n.id ? "on" : ""} onClick={() => select(n.id)}>
              {n.label}
            </button>
          ))}
        </nav>
      </aside>
      <div className="content">
        <div hidden={view !== "chat"} className="pane">
          <ChatWindow />
        </div>
        {view === "data" && (
          <div className="pane">
            <DataManagement />
          </div>
        )}
      </div>
    </div>
  );
}
