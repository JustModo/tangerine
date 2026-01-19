import { useState } from "react";
import { useForm, useFieldArray } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import Editor from "@monaco-editor/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import Papa from "papaparse";
import { toast } from "sonner";
import { FileJson, Upload, Plus, Trash2, ChevronRight } from "lucide-react";
import { QuestionMetadataSchema } from "../../server/schemas/question_schema";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Form, FormControl, FormField, FormItem, FormMessage } from "@/components/ui/form";
import { Separator } from "@/components/ui/separator";
import { z } from "zod";
import { cn } from "~/lib/utils";

const QuestionFormSchema = QuestionMetadataSchema.extend({
    testCases: z.array(z.object({
        id: z.string().uuid().optional(),
        input: z.string(),
        output: z.string(),
        isHidden: z.boolean().default(false),
    })).default([]),
});

type QuestionFormValues = z.infer<typeof QuestionFormSchema>;

export default function CreateQuestion() {
    const [activeTab, setActiveTab] = useState<"metadata" | "markdown" | "boilerplate" | "testcases">("metadata");
    const [markdownMode, setMarkdownMode] = useState<"write" | "preview">("write");

    const form = useForm<QuestionFormValues>({
        resolver: zodResolver(QuestionFormSchema) as any,
        defaultValues: {
            title: "",
            description: "# Problem Title\n\nDescription goes here...",
            languages: ["javascript", "python", "cpp", "c", "java"],
            boilerplates: [],
            testCases: []
        }
    });

    const { fields: testCaseFields, append: appendTestCase, remove: removeTestCase } = useFieldArray({
        control: form.control,
        name: "testCases"
    });

    const { append: appendBoilerplate } = useFieldArray({
        control: form.control,
        name: "boilerplates"
    });

    const exportToJson = (data: QuestionFormValues) => {
        const jsonString = JSON.stringify(data, null, 2);
        const blob = new Blob([jsonString], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = `${data.title.replace(/\s+/g, "_").toLowerCase() || "question"}.json`;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => {
            if (document.body.contains(a)) document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }, 100);
        toast.success("EXPORT SUCCESS");
    };

    const handleCsvImport = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        Papa.parse(file, {
            complete: (results) => {
                const data = results.data as string[][];
                let importedCount = 0;
                data.forEach((row, idx) => {
                    if (results.meta.fields && (row as any).input && (row as any).output) {
                        appendTestCase({ input: (row as any).input, output: (row as any).output, isHidden: false });
                        importedCount++;
                    } else if (row.length >= 2) {
                        if (idx === 0 && row[0].toLowerCase() === "input") return;
                        appendTestCase({ input: row[0], output: row[1], isHidden: false });
                        importedCount++;
                    }
                });
                toast.success(`IMPORTED ${importedCount} CASES`);
            },
            header: false
        });
    };

    return (
        <div className="h-full flex flex-col overflow-hidden bg-black text-white px-10 pt-10">
            <div className="flex-none flex items-center justify-between mb-10 pr-4">
                <div className="space-y-1">
                    <h1 className="text-4xl font-black tracking-tighter uppercase">Question Creator</h1>
                    <p className="text-zinc-500 text-xs font-bold uppercase tracking-[0.2em]">Build local testcases</p>
                </div>
                <Button variant="default" onClick={async () => {
                    const isValid = await form.trigger();
                    if (isValid) exportToJson(form.getValues());
                    else toast.error("VALIDATION FAILED");
                }} className="h-12 border border-white hover:bg-white hover:text-black">
                    <FileJson className="mr-3 h-4 w-4" /> EXPORT JSON
                </Button>
            </div>

            <Form {...form}>
                <form className="flex-1 flex gap-12 min-h-0 overflow-hidden pb-10">
                    {/* Sidebar / Configuration */}
                    <div className="w-80 flex flex-col gap-8 flex-none overflow-hidden px-2">
                        <section className="space-y-4">
                            <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">Metadata</h3>
                            <FormField control={form.control} name="title" render={({ field }) => (
                                <FormItem>
                                    <FormControl><Input {...field} placeholder="PROBLEM TITLE" className="bg-transparent border-white/10" /></FormControl>
                                    <FormMessage className="text-[10px] uppercase font-bold" />
                                </FormItem>
                            )} />
                        </section>

                        <section className="space-y-4">
                            <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">Langs</h3>
                            <FormField control={form.control} name="languages" render={({ field }) => (
                                <FormItem>
                                    <div className="flex flex-col gap-2">
                                        {["javascript", "python", "cpp", "c", "java"].map(lang => (
                                            <button
                                                key={lang}
                                                type="button"
                                                onClick={() => {
                                                    const current = field.value;
                                                    if (current.includes(lang as any)) field.onChange(current.filter(l => l !== lang));
                                                    else field.onChange([...current, lang]);
                                                }}
                                                className={cn(
                                                    "flex items-center justify-between px-4 py-3 text-[10px] font-black uppercase tracking-widest transition-colors border border-white/10",
                                                    field.value.includes(lang as any) ? "bg-white text-black border-white" : "hover:bg-white/5"
                                                )}
                                            >
                                                {lang === "cpp" ? "C++" : lang}
                                                {field.value.includes(lang as any) && <ChevronRight className="w-3 h-3" />}
                                            </button>
                                        ))}
                                    </div>
                                    <FormMessage />
                                </FormItem>
                            )} />
                        </section>

                        <Separator className="bg-white/5" />

                        <nav className="flex flex-col gap-2">
                            <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500 mb-2">View</h3>
                            {[
                                { id: "metadata", label: "Description" },
                                { id: "boilerplate", label: "Boilerplate" },
                                { id: "testcases", label: `Tests (${testCaseFields.length})` }
                            ].map(tab => (
                                <button
                                    key={tab.id}
                                    type="button"
                                    onClick={() => setActiveTab(tab.id as any)}
                                    className={cn(
                                        "text-left px-4 py-2 text-[10px] font-black uppercase tracking-widest transition-all",
                                        activeTab === tab.id ? "text-white translate-x-1" : "text-zinc-500 hover:text-zinc-300"
                                    )}
                                >
                                    {tab.label}
                                </button>
                            ))}
                        </nav>
                    </div>

                    {/* Main Workspace */}
                    <div className="flex-1 min-w-0 bg-zinc-950 border-l border-white/10 relative">
                        <div className="absolute inset-0 overflow-hidden flex flex-col">
                            {activeTab === "metadata" && (
                                <div className="flex-1 flex flex-col min-h-0">
                                    <div className="flex-none flex bg-black border-b border-white/5">
                                        <button
                                            type="button"
                                            onClick={() => setMarkdownMode("write")}
                                            className={cn(
                                                "px-8 py-4 text-[10px] font-black uppercase tracking-widest transition-colors",
                                                markdownMode === "write" ? "bg-white text-black" : "text-zinc-500 hover:text-zinc-300"
                                            )}
                                        >
                                            Write
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => setMarkdownMode("preview")}
                                            className={cn(
                                                "px-8 py-4 text-[10px] font-black uppercase tracking-widest transition-colors",
                                                markdownMode === "preview" ? "bg-white text-black" : "text-zinc-500 hover:text-zinc-300"
                                            )}
                                        >
                                            Preview
                                        </button>
                                    </div>

                                    <div className="flex-1 overflow-hidden relative">
                                        {markdownMode === "write" ? (
                                            <FormField control={form.control} name="description" render={({ field }) => (
                                                <textarea
                                                    className="w-full h-full bg-transparent p-12 text-sm font-mono border-0 focus:outline-none resize-none text-white/80 overflow-y-auto leading-relaxed"
                                                    placeholder="MARKDOWN DESCRIPTION"
                                                    {...field}
                                                />
                                            )} />
                                        ) : (
                                            <div className="h-full overflow-y-auto p-12 prose dark:prose-invert max-w-none bg-black">
                                                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                                    {form.watch("description")}
                                                </ReactMarkdown>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            )}

                            {activeTab === "boilerplate" && (
                                <ScrollArea className="h-full">
                                    <div className="max-w-4xl space-y-12 p-8">
                                        {form.watch("languages").map((lang) => (
                                            <div key={lang} className="space-y-4">
                                                <h3 className="text-xs font-black uppercase tracking-[0.2em]">{lang === "cpp" ? "C++" : lang}</h3>
                                                <div className="h-80 border border-white/10">
                                                    {typeof window !== "undefined" && (
                                                        <Editor
                                                            height="100%"
                                                            defaultLanguage={lang === "cpp" ? "cpp" : lang === "c" ? "c" : lang === "python" ? "python" : "javascript"}
                                                            theme="vs-dark"
                                                            value={form.getValues().boilerplates.find(b => b.language === lang)?.code || ""}
                                                            onChange={(value) => {
                                                                const current = form.getValues().boilerplates;
                                                                const idx = current.findIndex(b => b.language === lang);
                                                                if (idx >= 0) {
                                                                    current[idx].code = value || "";
                                                                    form.setValue("boilerplates", [...current]);
                                                                } else {
                                                                    appendBoilerplate({ language: lang as any, code: value || "" });
                                                                }
                                                            }}
                                                            options={{
                                                                padding: { top: 20 },
                                                                minimap: { enabled: false },
                                                                fontSize: 12,
                                                                fontFamily: "JetBrains Mono, monospace"
                                                            }}
                                                        />
                                                    )}
                                                </div>
                                            </div>
                                        ))}
                                        {form.watch("languages").length === 0 && <p className="text-zinc-500 font-bold uppercase text-[10px]">No languages enabled</p>}
                                    </div>
                                </ScrollArea>
                            )}

                            {activeTab === "testcases" && (
                                <div className="h-full flex flex-col p-12 gap-8 min-h-0">
                                    <div className="flex-none flex justify-between items-center bg-black p-4 border-l-2 border-white">
                                        <h3 className="text-sm font-black uppercase tracking-widest">Test Database</h3>
                                        <div className="flex gap-4">
                                            <div className="relative">
                                                <input type="file" accept=".csv" className="absolute inset-0 opacity-0 cursor-pointer" onChange={handleCsvImport} />
                                                <Button variant="ghost" size="sm" className="text-[10px]"><Upload className="w-3 h-3 mr-2" /> IMPORT CSV</Button>
                                            </div>
                                            <Button size="sm" onClick={() => appendTestCase({ input: "", output: "", isHidden: false })} className="text-[10px]"><Plus className="w-3 h-3 mr-2" /> ADD CASE</Button>
                                        </div>
                                    </div>
                                    <div className="flex-1 overflow-y-auto">
                                        <div className="space-y-4 pr-4 pb-32">
                                            {testCaseFields.map((field, index) => (
                                                <div key={field.id} className="flex gap-4 p-4 bg-zinc-900 overflow-hidden relative group">
                                                    <div className="flex-none w-8 text-[10px] font-black text-zinc-600 self-center">{index + 1}</div>
                                                    <div className="flex-1 grid grid-cols-2 gap-4">
                                                        <div className="space-y-2">
                                                            <Label className="text-[8px] font-black uppercase text-zinc-500 tracking-tighter">Input</Label>
                                                            <Textarea
                                                                {...form.register(`testCases.${index}.input` as const)}
                                                                className="min-h-[80px] bg-black border-zinc-800 focus-visible:ring-zinc-600 text-[10px] font-mono"
                                                            />
                                                        </div>
                                                        <div className="space-y-2">
                                                            <Label className="text-[8px] font-black uppercase text-zinc-500 tracking-tighter">Output</Label>
                                                            <Textarea
                                                                {...form.register(`testCases.${index}.output` as const)}
                                                                className="min-h-[80px] bg-black border-zinc-800 focus-visible:ring-zinc-600 text-[10px] font-mono"
                                                            />
                                                        </div>
                                                    </div>
                                                    <Button
                                                        variant="ghost"
                                                        size="icon"
                                                        onClick={() => removeTestCase(index)}
                                                        className="opacity-0 group-hover:opacity-100 transition-opacity self-center"
                                                    >
                                                        <Trash2 className="w-4 h-4 text-red-500" />
                                                    </Button>
                                                </div>
                                            ))}
                                            {testCaseFields.length === 0 && <p className="text-center p-20 text-zinc-500 font-bold uppercase text-[10px]">Test database is empty</p>}
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                </form>
            </Form>
        </div>
    );
}
