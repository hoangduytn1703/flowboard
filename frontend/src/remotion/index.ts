// Entry point of the Remotion bundle (server render). Not imported by the app.
import { registerRoot } from "remotion";
import { RemotionRoot } from "./Root";

registerRoot(RemotionRoot);
