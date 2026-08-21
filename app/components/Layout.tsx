import { Toaster } from "@/components/ui/sonner";
import { BusyIndicator, ErrorBanner, StatusProvider } from "~/lib/status";

export default function Layout({ children }: { children: React.ReactNode }) {
    return (
        <StatusProvider>
            <div className="h-screen bg-black text-white font-sans antialiased flex flex-col overflow-hidden">
                <ErrorBanner />
                <main className="flex-1 min-h-0 flex flex-col overflow-hidden">
                    {children}
                </main>
                <BusyIndicator />
                <Toaster />
            </div>
        </StatusProvider>
    );
}
