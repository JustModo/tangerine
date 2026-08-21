import { useState, useEffect } from "react";
import { toast } from "sonner";
import {
  Play,
  FolderOpen,
  RefreshCcw,
  Hash,
  FileCode,
  Folder,
  ChevronLeft,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Separator } from "@/components/ui/separator";
import { cn } from "~/lib/utils";

interface TestCaseSpec {
  id?: string;
  input: string;
  output: string; // stored as a sha256 hash, never plaintext
}

interface QuestionExport {
  title: string;
  description: string;
  languages: string[];
  testCases: TestCaseSpec[];
}

interface TestResult {
  id: string;
  status: "PENDING" | "PASSED" | "FAILED" | "ERROR" | "TIMEOUT";
  input: string;
  actual_output?: string;
  error?: string;
  execution_time_ms?: string;
  pending?: boolean;
}

export default function Runner() {
  const [question, setQuestion] = useState<QuestionExport | null>(null);
  const [codePath, setCodePath] = useState("");
  const [selectedLanguage, setSelectedLanguage] = useState<string>("");
  const [results, setResults] = useState<Record<string, TestResult>>({});
  const [isRunning, setIsRunning] = useState(false);

  // File Picker State
  const [showPicker, setShowPicker] = useState(false);
  const [explorerPath, setExplorerPath] = useState("");
  const [explorerFiles, setExplorerFiles] = useState<any[]>([]);

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const json = JSON.parse(event.target?.result as string);
        if (!json.title || !json.testCases) throw new Error("INVALID");
        setQuestion(json);
        if (json.languages?.length > 0) setSelectedLanguage(json.languages[0]);
        toast.success("QUESTION LOADED");
      } catch (err) {
        toast.error("PARSE FAILED");
      }
    };
    reader.readAsText(file);
  };

  useEffect(() => {
    if (!codePath) return;
    const eventSource = new EventSource(
      `/api/workspace/watch?path=${encodeURIComponent(codePath)}`,
    );
    eventSource.addEventListener("change", () => {
      // File changed - maybe trigger auto run? For now just log
    });
    return () => eventSource.close();
  }, [codePath]);

  const runTests = async () => {
    if (!question || !codePath || !selectedLanguage) return;
    setIsRunning(true);
    const initialResults: Record<string, TestResult> = {};
    question.testCases.forEach((tc) => {
      initialResults[tc.id || tc.input] = {
        id: tc.id || tc.input,
        input: tc.input,
        status: "PENDING",
        pending: true,
      };
    });
    setResults(initialResults);

    try {
      const response = await fetch("/api/execution/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          language: selectedLanguage,
          code_path: codePath,
          test_cases: question.testCases.map((tc) => ({
            id: tc.id || tc.input,
            input: tc.input,
            output_hash: tc.output,
          })),
        }),
      });

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value);
          const lines = chunk.split("\n\n");
          for (const line of lines) {
            if (line.startsWith("data: ")) {
              const dataStr = line.replace("data: ", "");
              if (dataStr === "{}" || dataStr.trim() === "") continue;
              try {
                const result = JSON.parse(dataStr) as TestResult;
                setResults((prev) => ({
                  ...prev,
                  [result.id]: { ...result, pending: false },
                }));
              } catch (e) {}
            }
          }
        }
      }
    } catch (e) {
      toast.error("RUN ERROR");
    } finally {
      setIsRunning(false);
    }
  };

  const getStatusText = (status: string) => {
    switch (status) {
      case "PASSED":
        return <span className="text-green-500 font-black">PASS</span>;
      case "FAILED":
        return <span className="text-red-500 font-black">FAIL</span>;
      case "ERROR":
        return <span className="text-orange-500 font-black">ERR</span>;
      case "TIMEOUT":
        return <span className="text-yellow-500 font-black">TMO</span>;
      default:
        return (
          <span className="text-zinc-500 font-black animate-pulse">RUN</span>
        );
    }
  };

  const totalCases = question?.testCases.length || 0;
  const finishedCount = Object.values(results).filter((r) => !r.pending).length;
  const passedCases = Object.values(results).filter(
    (r) => r.status === "PASSED",
  ).length;

  const openPicker = async (path?: string) => {
    try {
      const resp = await fetch(
        `/api/workspace/list${path ? `?path=${encodeURIComponent(path)}` : ""}`,
      );
      const data = await resp.json();
      setExplorerPath(data.current_path);
      setExplorerFiles(data.files);
      setShowPicker(true);
    } catch (e) {
      toast.error("PICKER ERROR");
    }
  };

  const handleFileSelect = (path: string) => {
    setCodePath(path);
    setShowPicker(false);
  };

  return (
    <div className="h-full flex flex-col overflow-hidden bg-black text-white px-10 pt-10">
      <div className="flex-none">
        <div className="flex items-center justify-between mb-8">
          <div className="space-y-1">
            <h1 className="text-4xl font-black tracking-tighter uppercase">
              {question?.title || "RUNNER"}
            </h1>
            <p className="text-zinc-500 text-xs font-bold uppercase tracking-[0.2em]">
              Executing locally
            </p>
          </div>
          <div className="flex gap-4 items-center">
            <div className="relative group">
              <input
                type="file"
                accept=".json"
                className="absolute inset-0 opacity-0 cursor-pointer"
                onChange={handleFileUpload}
              />
              <Button variant="outline" size="sm" className="h-10 text-[10px]">
                <FolderOpen className="mr-2 h-4 w-4" /> OPEN JSON
              </Button>
            </div>
          </div>
        </div>

        <div className="flex gap-4 mb-8">
          <div className="flex-1 flex gap-2">
            <Input
              placeholder="FULL PATH TO SOURCE FILE"
              className="flex-1 bg-zinc-950 border-white/10 font-bold uppercase tracking-widest text-[10px]"
              value={codePath}
              onChange={(e) => setCodePath(e.target.value)}
            />
            <Button
              variant="outline"
              className="border-dashed border-white/20 hover:border-white text-[10px]"
              onClick={() => openPicker()}
            >
              PICK SOURCE
            </Button>
          </div>
          {question && (
            <select
              className="h-10 bg-zinc-950 border border-white/10 px-6 text-[10px] font-black uppercase tracking-widest focus:outline-none focus:ring-1 focus:ring-white"
              value={selectedLanguage}
              onChange={(e) => setSelectedLanguage(e.target.value)}
            >
              {question.languages.map((l) => (
                <option key={l} value={l} className="bg-black">
                  {l === "cpp" ? "c++" : l}
                </option>
              ))}
            </select>
          )}
          <Button onClick={runTests} disabled={!question || !codePath || isRunning}>
            {isRunning ? (
              <RefreshCcw className="mr-3 h-4 w-4 animate-spin" />
            ) : (
              <Play className="mr-3 h-4 w-4" />
            )}
            EXECUTE
          </Button>
        </div>

        <Separator className="bg-white/10 mb-8" />
      </div>

      <ResizablePanelGroup
        direction="horizontal"
        className="flex-1 min-h-0 overflow-hidden"
      >
        <ResizablePanel defaultSize={35}>
          <ScrollArea className="h-full p-8 prose dark:prose-invert max-w-none bg-zinc-950 border-r border-white/10">
            {question ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {question.description}
              </ReactMarkdown>
            ) : (
              <div className="flex flex-col items-center justify-center h-full gap-4 opacity-20">
                <Hash className="w-12 h-12" />
                <span className="text-[10px] font-black uppercase tracking-[0.5em]">
                  System Idle
                </span>
              </div>
            )}
          </ScrollArea>
        </ResizablePanel>

        <ResizableHandle className="w-1 bg-white/5" />

        {/* Added h-full and overflow-hidden here */}
        <ResizablePanel defaultSize={65} className="h-full overflow-hidden">
          <div className="h-full flex flex-col bg-black overflow-hidden">
            {question && totalCases > 0 && (
              <div className="px-8 py-6 space-y-4 flex-shrink-0">
                {" "}
                {/* flex-shrink-0 keeps header sized correctly */}
                <div className="flex justify-between items-end">
                  <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">
                    Execution Status
                  </h3>
                  <span className="text-[10px] font-black">
                    {finishedCount} / {totalCases} CASES
                  </span>
                </div>
                <div className="h-1 bg-zinc-900 w-full overflow-hidden">
                  <div
                    className="h-full bg-white transition-all duration-500 ease-out"
                    style={{ width: `${(finishedCount / totalCases) * 100}%` }}
                  />
                </div>
                <div className="flex gap-8 text-[10px] font-black uppercase tracking-widest">
                  <span className="text-green-500">{passedCases} PASSED</span>
                  <span className="text-red-500">
                    {finishedCount - passedCases} FAILED
                  </span>
                </div>
              </div>
            )}

            {/* Added flex-1 and min-h-0 to allow the scroll area to capture the remaining height */}
            <ScrollArea className="flex-1 min-h-0 px-8 w-full">
              <Table className="border-collapse">
                <TableHeader className="[&_tr]:border-b-0 sticky top-0 bg-black z-10">
                  {" "}
                  {/* Added sticky header */}
                  <TableRow className="border-b border-white/5 hover:bg-transparent">
                    <TableHead className="w-12 text-[9px] font-black uppercase tracking-widest p-2">
                      #
                    </TableHead>
                    <TableHead className="w-24 text-[9px] font-black uppercase tracking-widest p-2">
                      STAT
                    </TableHead>
                    <TableHead className="w-24 text-[9px] font-black uppercase tracking-widest p-2">
                      TIME
                    </TableHead>
                    <TableHead className="text-[9px] font-black uppercase tracking-widest p-2">
                      OUTPUT LOGS
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {question?.testCases.map((tc, idx) => {
                    const res = results[tc.id || tc.input];
                    return (
                      <TableRow
                        key={tc.id || idx}
                        className="border-b border-white/5 hover:bg-zinc-950 transition-colors group"
                      >
                        <TableCell className="p-4 text-[10px] font-bold text-zinc-600 font-mono">
                          {indexPadding(idx + 1)}
                        </TableCell>
                        <TableCell className="p-4">
                          {getStatusText(res?.status || "PENDING")}
                        </TableCell>
                        <TableCell className="p-4 text-[10px] font-bold font-mono">
                          {res?.execution_time_ms || "-"}
                        </TableCell>
                        <TableCell className="p-4">
                          <div className="space-y-2 opacity-60 group-hover:opacity-100 transition-opacity">
                            <div className="text-[9px] font-mono">
                              <span className="text-zinc-600">IN:</span>{" "}
                              {tc.input.substring(0, 100)}
                            </div>
                            {res?.actual_output && (
                              <div
                                className={cn(
                                  "border-l pl-3",
                                  res.status === "PASSED"
                                    ? "border-green-500/20"
                                    : "border-red-500/20",
                                )}
                              >
                                <div
                                  className={cn(
                                    "text-[9px] font-mono",
                                    res.status === "PASSED"
                                      ? "text-green-500/80"
                                      : "text-red-500",
                                  )}
                                >
                                  <span className="font-bold uppercase tracking-tighter mr-2">
                                    Stdout:
                                  </span>{" "}
                                  {res.actual_output}
                                </div>
                              </div>
                            )}
                            {res?.status === "ERROR" && (
                              <div className="text-[9px] font-mono text-orange-500 pl-3 border-l border-orange-500/20">
                                {res.error}
                              </div>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                  {!question && (
                    <TableRow>
                      <TableCell
                        colSpan={4}
                        className="h-64 text-center text-zinc-700 text-[10px] font-black uppercase tracking-[0.4em]"
                      >
                        Ready for Injection
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </ScrollArea>
          </div>
        </ResizablePanel>
      </ResizablePanelGroup>
      {showPicker && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-8 bg-black/80 backdrop-blur-sm">
          <div className="w-full max-w-2xl bg-zinc-950 border border-white/20 flex flex-col h-[70vh] overflow-hidden">
            <div className="flex-none p-6 border-b border-white/10 flex justify-between items-center bg-black">
              <div className="space-y-1">
                <h3 className="text-sm font-black uppercase tracking-widest">
                  Select Question File
                </h3>
                <p className="text-[9px] font-mono text-zinc-500 overflow-hidden text-ellipsis whitespace-nowrap max-w-md">
                  {explorerPath}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setShowPicker(false)}
              >
                <X className="w-4 h-4" />
              </Button>
            </div>

            <div className="flex-none p-4 flex gap-2 overflow-x-auto bg-zinc-900 border-b border-white/5">
              <Button
                variant="ghost"
                size="sm"
                className="text-[9px] font-black uppercase"
                onClick={() =>
                  openPicker(
                    explorerPath.split("/").slice(0, -1).join("/") || "/",
                  )
                }
              >
                <ChevronLeft className="w-3 h-3 mr-2" /> UP
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="text-[9px] font-black uppercase"
                onClick={async () => {
                  const resp = await fetch("/api/workspace/home");
                  const data = await resp.json();
                  openPicker(data.path);
                }}
              >
                HOME
              </Button>
            </div>

            <div className="flex-1 overflow-hidden">
              <ScrollArea className="h-full w-full">
                <div className="p-2">
                  {explorerFiles.map((file) => (
                    <button
                      key={file.path}
                      type="button"
                      onClick={() =>
                        file.is_directory
                          ? openPicker(file.path)
                          : handleFileSelect(file.path)
                      }
                      className="w-full flex items-center gap-3 p-3 text-[11px] font-medium border border-transparent hover:border-white/10 hover:bg-white/5 transition-all text-left group"
                    >
                      {file.is_directory ? (
                        <Folder className="w-4 h-4 text-zinc-500 group-hover:text-white" />
                      ) : (
                        <FileCode className="w-4 h-4 text-white" />
                      )}
                      <span
                        className={cn(
                          file.is_directory ? "text-zinc-400" : "text-white",
                          "group-hover:text-white",
                        )}
                      >
                        {file.name}
                      </span>
                    </button>
                  ))}
                </div>
              </ScrollArea>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function indexPadding(n: number) {
  return n < 10 ? `0${n}` : `${n}`;
}
