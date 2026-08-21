import { Link, Outlet } from "react-router";
import { Toaster } from "@/components/ui/sonner";
import { Separator } from "@/components/ui/separator";
import { BusyIndicator, ErrorBanner, StatusProvider } from "~/lib/status";

export default function Layout({ children }: { children: React.ReactNode }) {
    return (
        <StatusProvider>
            <div className="h-screen bg-black text-white font-sans antialiased flex flex-col overflow-hidden">
                <ErrorBanner />
                <header className="py-6 px-10 flex-none bg-black">
                    <div className="flex items-center">
                        <Link to="/" className="text-2xl font-black tracking-tighter hover:opacity-70 transition-opacity">
                            TANGERINE
                        </Link>
                    </div>
                </header>
                <div className="px-10 flex-none">
                    <Separator className="bg-white/10" />
                </div>
                <main className="flex-1 min-h-0 flex flex-col overflow-hidden">
                    {children}
                </main>
                <BusyIndicator />
                <Toaster />
            </div>
        </StatusProvider>
    );
}
