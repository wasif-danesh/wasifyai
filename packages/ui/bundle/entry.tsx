// What the bundle check builds (scripts/chat/check-bundle.mjs): the first screen of the new chat on its own, the way a person who
// turned it on loads it. Not part of the app.
import { createRoot } from "react-dom/client";
import { ChatScreen } from "../src/chat/ChatScreen";

const nothing = {} as never;
const root = document.getElementById("root");
if (root)
  createRoot(root).render(<ChatScreen runs={nothing} assistant={nothing} images={nothing} />);
