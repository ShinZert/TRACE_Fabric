import { createContext } from "react";

// Shared between Editor and FabricNode for inline-edit coordination.
// editingId: id of the node currently being edited, or null.
// finishEdit(id, newLabel, cancelled): commit or cancel the edit.
export const EditorContext = createContext(null);
