import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@xyflow/react/dist/style.css";
import "./styles.css";
import App from "./App";
import { PasswordGate } from "./components/PasswordGate";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <PasswordGate>
      <App />
    </PasswordGate>
  </StrictMode>
);
