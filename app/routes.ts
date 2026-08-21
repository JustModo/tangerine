import { type RouteConfig, index, route } from "@react-router/dev/routes";

export default [
    index("routes/home.tsx"),
    route("sessions/:id", "routes/session.tsx"),
    route("plans/:id", "routes/plan.tsx"),
    route("problem-sessions/:id", "routes/problem_session.tsx"),
    route("run", "routes/run.tsx")
] satisfies RouteConfig;
