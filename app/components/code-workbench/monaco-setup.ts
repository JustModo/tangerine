// Only the four languages the sandbox can run. Importing the top-level `monaco-editor`
// package registers all ~60 bundled languages and pulls in the TypeScript, CSS and HTML
// language services — ~8MB of workers for languages this editor never opens.
import * as monaco from "monaco-editor/esm/vs/editor/editor.api.js";
import "monaco-editor/esm/vs/editor/editor.all.js";
import "monaco-editor/esm/vs/basic-languages/python/python.contribution.js";
import "monaco-editor/esm/vs/basic-languages/cpp/cpp.contribution.js";
import "monaco-editor/esm/vs/basic-languages/java/java.contribution.js";
import { loader } from "@monaco-editor/react";
import editorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";

// Self-hosted, not the CDN @monaco-editor/react defaults to (cdn.jsdelivr.net) - this is
// a local-first tool (local SQLite, local Citron sandbox), so the editor has to work
// without internet access too.
//
// One worker for every language: python, c, cpp and java are syntax-highlighting-only
// contributions with no language service of their own.
self.MonacoEnvironment = {
  getWorker() {
    return new editorWorker();
  },
};

// Monaco binds Ctrl/Cmd+Enter to insertLineAfter and consumes the event, so the workbench's
// submit shortcut never reached the window listener. Unbinding lets the keydown bubble.
monaco.editor.addKeybindingRules([
  { keybinding: monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, command: null },
]);

loader.config({ monaco });
