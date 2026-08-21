import Editor from "@monaco-editor/react";
import "./monaco-setup";

const MONACO_LANGUAGE: Record<string, string> = {
  python: "python",
  cpp: "cpp",
  c: "c",
  java: "java",
};

export function MonacoEditor({
  language,
  value,
  onChange,
}: {
  language: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <Editor
      language={MONACO_LANGUAGE[language] || "plaintext"}
      theme="vs-dark"
      value={value}
      onChange={(next) => onChange(next ?? "")}
      loading={null}
      options={{
        minimap: { enabled: false },
        fontSize: 14,
        tabSize: 2,
        scrollBeyondLastLine: false,
        padding: { top: 12, bottom: 12 },
      }}
    />
  );
}
