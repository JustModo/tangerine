import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

export default function Home() {
  return (
    <div className="flex-1 overflow-y-auto w-full">
      <div className="max-w-6xl mx-auto flex flex-col gap-20 py-20 px-10">
        <div className="space-y-4 text-center">
          <h1 className="text-8xl font-black tracking-tighter uppercase leading-none">
            Local<br />Testcases
          </h1>
          <p className="text-zinc-500 text-sm font-bold uppercase tracking-[0.5em]">Tangerine Engine v1.0</p>
        </div>

        <div className="grid md:grid-cols-2 gap-1 px-10">
          <section className="p-12 hover:bg-zinc-950 transition-colors group space-y-8 flex flex-col items-start border-l border-white/5">
            <div className="space-y-4 flex-1">
              <h2 className="text-2xl font-black uppercase tracking-tight group-hover:translate-x-2 transition-transform underline decoration-white/10 underline-offset-8">Question Creator</h2>
              <p className="text-zinc-500 text-xs font-medium uppercase tracking-widest leading-relaxed">
                Design complex competitive programming problems. Define metadata, test cases, and multi-language boilerplates in a unified interface.
              </p>
            </div>
            <Button asChild className="w-full h-14 text-xs tracking-[0.3em]" variant="default">
              <Link to="/create">INITIALIZE CREATOR</Link>
            </Button>
          </section>

          <section className="p-12 hover:bg-zinc-950 transition-colors group space-y-8 flex flex-col items-start border-l border-white/5">
            <div className="space-y-4 flex-1">
              <h2 className="text-2xl font-black uppercase tracking-tight group-hover:translate-x-2 transition-transform underline decoration-white/10 underline-offset-8">Test Runner</h2>
              <p className="text-zinc-500 text-xs font-medium uppercase tracking-widest leading-relaxed">
                Import question schemas and execute code against local compilers. Real-time feedback, performance metrics, and file-watching integration.
              </p>
            </div>
            <Button asChild className="w-full h-14 text-xs tracking-[0.3em]" variant="outline">
              <Link to="/run">LAUNCH RUNNER</Link>
            </Button>
          </section>
        </div>

        <div className="flex justify-center flex-col items-center gap-10 opacity-30">
          <Separator className="w-32 bg-white/20" />
          <span className="text-[10px] font-black uppercase tracking-[1em]">System Standby</span>
        </div>
      </div>
    </div>
  );
}
