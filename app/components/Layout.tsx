import { Link, Outlet } from "react-router";
import { Toaster } from "@/components/ui/sonner";
import { Separator } from "@/components/ui/separator";

export default function Layout({ children }: { children: React.ReactNode }) {
    return (
        <div className="h-screen bg-black text-white font-sans antialiased flex flex-col overflow-hidden">
            <header className="py-6 px-10 flex-none bg-black">
                <div className="flex items-center">
                    <Link to="/" className="text-2xl font-black tracking-tighter mr-12 hover:opacity-70 transition-opacity">
                        TANGERINE
                    </Link>
                    <nav className="flex items-center space-x-8 text-xs font-bold uppercase tracking-widest">
                        <Link to="/create" className="hover:text-muted-foreground transition-colors">Create</Link>
                        <Link to="/run" className="hover:text-muted-foreground transition-colors">Runner</Link>
                    </nav>
                </div>
            </header>
            <div className="px-10 flex-none">
                <Separator className="bg-white/10" />
            </div>
            <main className="flex-1 min-h-0 flex flex-col overflow-hidden">
                {children}
            </main>
            <Toaster />
        </div>
    );
}
