// ponytail: importing the top-level `monaco-editor` package registers all ~60 bundled
// languages, not the 4 this app runs, producing a large editor chunk. Upgrade path if that
// matters: import `monaco-editor/esm/vs/editor/editor.api` plus only the needed
// `basic-languages/{python,cpp,c,java}/*.contribution` entries instead.
import * as monaco from "monaco-editor";
import { loader } from "@monaco-editor/react";
import editorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import tsWorker from "monaco-editor/esm/vs/language/typescript/ts.worker?worker";

// Self-hosted, not the CDN @monaco-editor/react defaults to (cdn.jsdelivr.net) - this is
// a local-first tool (local SQLite, local Citron sandbox), so the editor has to work
// without internet access too.
self.MonacoEnvironment = {
  getWorker(_workerId: string, label: string) {
    if (label === "javascript" || label === "typescript") return new tsWorker();
    return new editorWorker();
  },
};

loader.config({ monaco });
