import { z } from "zod";

export const LanguageEnum = z.enum(["javascript", "python", "cpp", "c", "java"]);

export const TestCaseSchema = z.object({
    id: z.string().uuid().optional(),
    input: z.string(),
    output: z.string(),
    isHidden: z.boolean().default(false),
});

export const BoilerplateSchema = z.object({
    language: LanguageEnum,
    code: z.string(),
});

export const QuestionMetadataSchema = z.object({
    title: z.string().min(1, "Title is required"),
    description: z.string().min(1, "Description is required"), // Markdown content
    constraints: z.string().optional(),
    inputFormat: z.string().optional(),
    outputFormat: z.string().optional(),
    languages: z.array(LanguageEnum).default([]),
    boilerplates: z.array(BoilerplateSchema).default([]),
    versionTags: z.record(z.string(), z.string()).optional(), // e.g., { "python": "3.10", "node": "18" }
});

export const QuestionExportSchema = QuestionMetadataSchema.extend({
    testCases: z.array(TestCaseSchema),
});

export type QuestionMetadata = z.infer<typeof QuestionMetadataSchema>;
export type QuestionExport = z.infer<typeof QuestionExportSchema>;
export type Language = z.infer<typeof LanguageEnum>;

export type ExecutionResult = {
    id: string; // Testcase ID
    status: "PENDING" | "PASSED" | "FAILED" | "ERROR" | "TIMEOUT";
    input: string;
    expectedOutput: string;
    actualOutput?: string;
    error?: string;
    executionTime?: string; // ms
};
