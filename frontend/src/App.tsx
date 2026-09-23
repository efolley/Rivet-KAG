import ChatWindow from "./components/ChatWindow";

export default function App() {
  return (
    <div className="app">
      <header>
        <h1>rivet-kag</h1>
        <span>Knowledge-Augmented Generation over Milvus + Neo4j</span>
      </header>
      <ChatWindow />
    </div>
  );
}
