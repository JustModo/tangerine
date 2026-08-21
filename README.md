# Tangerine

Tangerine builds you a personal DSA course, then coaches you through it.

Tell it what you want to get better at. It writes a lesson plan, and each step gives you
notes, a problem, an editor, and a mentor that has actually read your code.

## What you can do

**Ask for what you need.** "I'm new to binary search." "Three medium graph problems in
Java." Stuck on a LeetCode question? Paste it in, and you get a short course that ends with
that exact problem.

**Change the plan.** Add a step, drop one, make problem 3 harder. Just say so.

**Read the notes.** Every step comes with a short cheat sheet: the idea, the pattern, a
worked example, and the shortcuts worth knowing.

**Write only the function.** No boilerplate, no reading input, no printing. Run against the
visible examples as often as you like, then submit to be graded on hidden tests.

**Ask for help.** The chat beside the editor sees your code and your last test run. Ask why
a test failed, or whether your solution can be faster. It gives you the answer if you ask
outright, and a hint if you don't.

Python, C, C++ and Java. Your code runs in a real sandbox, not your browser.

## Getting started

You need [Docker](https://docs.docker.com/get-started/) and a free
[Gemini API key](https://aistudio.google.com/apikey).

```bash
docker compose up --build
```

Open **http://localhost:8000** and paste your key when it asks. It's checked with Google
first, then stored encrypted on your machine, so you won't be asked again. Use the gear
icon on the home page to change or remove it later.

### From source

```bash
pnpm install
cd agent && uv sync
```

Copy `.env.example` to `.env`, add your key, then run `pnpm dev` from the project root.
You'll also need a [Citron](https://github.com/JustModo/citron) sandbox running for code
execution. Docker starts one for you; this way you supply your own.

## Notes

No accounts, no login. Tangerine runs on your machine and only listens on localhost.
Your plans, your code and your key stay in a local database.
