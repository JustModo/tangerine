import {
  isRouteErrorResponse,
  Links,
  Meta,
  Outlet,
  Scripts,
  ScrollRestoration,
} from "react-router";

import type { Route } from "./+types/root";
import "./app.css";
import AppLayout from "./components/Layout";
import { HealthGate } from "./components/HealthGate";

export const links: Route.LinksFunction = () => [
  // SVG first for browsers that take it, .ico as the universal fallback. Both are a white
  // T on black, drawn natively at each size so the 16px tab icon stays sharp.
  { rel: "icon", href: "/favicon.svg", type: "image/svg+xml" },
  { rel: "icon", href: "/favicon.ico", sizes: "any" },
  { rel: "apple-touch-icon", href: "/apple-touch-icon.png" },
  { rel: "preconnect", href: "https://fonts.googleapis.com" },
  {
    rel: "preconnect",
    href: "https://fonts.gstatic.com",
    crossOrigin: "anonymous",
  },
  {
    rel: "stylesheet",
    href: "https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,100..900;1,14..32,100..900&display=swap",
  },
];

/** Fallback for any route that does not set its own. React Router uses the leaf route's
 * meta when there is one, so each screen below overrides this. */
export const meta: Route.MetaFunction = () => [
  { title: "Tangerine" },
  {
    name: "description",
    content:
      "Tangerine builds you a personal DSA course, then coaches you through it: a lesson plan, notes, practice problems, and a mentor that has read your code.",
  },
  { name: "theme-color", content: "#000000" },
];

export function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <Meta />
        <Links />
      </head>
      <body>
        {children}
        <ScrollRestoration />
        <Scripts />
      </body>
    </html>
  );
}

export default function App() {
  return (
    <HealthGate>
      <AppLayout>
        <Outlet />
      </AppLayout>
    </HealthGate>
  );
}

export function ErrorBoundary({ error }: Route.ErrorBoundaryProps) {
  let message = "Oops!";
  let details = "An unexpected error occurred.";
  let stack: string | undefined;

  if (isRouteErrorResponse(error)) {
    message = error.status === 404 ? "404" : "Error";
    details =
      error.status === 404
        ? "The requested page could not be found."
        : error.statusText || details;
  } else if (import.meta.env.DEV && error && error instanceof Error) {
    details = error.message;
    stack = error.stack;
  }

  return (
    <main className="p-10 container mx-auto">
      <h1 className="text-4xl font-bold mb-4">{message}</h1>
      <p className="text-lg mb-8">{details}</p>
      {stack && (
        <pre className="p-4 bg-muted rounded overflow-auto text-sm">
          <code>{stack}</code>
        </pre>
      )}
    </main>
  );
}
