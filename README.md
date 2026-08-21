# Tangerine

Tangerine is a professional development tool for creating and executing local coding challenges. It provides a secure environment for test case verification using hashed outputs and a minimalist interface for question management.

## Core Features

### Security and Hashing
- Automated SHA-256 hashing of test case outputs.
- Encrypted verification: Expected outputs are never stored in plain text or exposed to the runner.
- Secure local file system browsing for source file selection.

### Runner
- Real-time execution and stdout tracking.
- Automated verification against hashed expectations.
- High-performance execution with support for multiple runtimes.

## Setup

### Prerequisites
- Node.js (Latest LTS recommended)
- Local compilers/runtimes for targeted languages (gcc, g++, python3, java)

### Installation
```bash
npm install
```

### Development
```bash
npm run dev
```

### Production Build
```bash
npm run build
```

## Architecture
The application is built using a modern full-stack architecture:
- **Frontend**: React Router v7 with Tailwind CSS.
- **Backend**: Express-based Node.js server for file system and code execution services.
- **Styling**: Strict monochrome design system for high-contrast visibility.
