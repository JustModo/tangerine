import "react-router";
import { createRequestHandler } from "@react-router/express";
import express from "express";

import { apiRouter } from "./routes/api";
import { learningRouter } from "./routes/learning";

export const app = express();

app.use(express.json()); // Required for JSON body parsing

app.use("/api", apiRouter);
app.use("/api/learning", learningRouter);

app.get("/api/health", (_req, res) => {
  res.status(200).send("OK");
});

app.use(
  createRequestHandler({
    build: () =>
      import("virtual:react-router/server-build"),
  }),
);

