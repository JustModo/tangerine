import "react-router";
import { createRequestHandler } from "@react-router/express";
import express from "express";

export const app = express();

app.get("/api/health", (_req, res) => {
  res.status(200).send("OK");
});

app.use(
  createRequestHandler({
    build: () =>
      import("virtual:react-router/server-build"),
  }),
);

