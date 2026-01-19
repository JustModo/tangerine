import { type RouteConfig, index, route } from "@react-router/dev/routes";

export default [
    index("routes/home.tsx"),
    route("create", "routes/create.tsx"),
    route("run", "routes/run.tsx")
] satisfies RouteConfig;
