# ForgeAI

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![PostgreSQL 17](https://img.shields.io/badge/PostgreSQL-17-336791.svg?logo=postgresql)](https://www.postgresql.org/)
[![pgvector](https://img.shields.io/badge/pgvector-0.8+-blueviolet.svg)](https://github.com/pgvector/pgvector)
[![Ollama](https://img.shields.io/badge/Ollama-Local_Inference-black.svg)](https://ollama.ai)
[![Backend Tests](https://img.shields.io/badge/pytest-207_passed-success.svg)](backend/tests)
[![E2E Tests](https://img.shields.io/badge/Playwright-39_passed-success.svg)](frontend/e2e)
[![Retrieval Eval](https://img.shields.io/badge/retrieval_eval-MRR_1.0000-brightgreen.svg)](backend/evals)
[![RAG Eval](https://img.shields.io/badge/rag_eval-3%2F3_passed_(100%25)-brightgreen.svg)](backend/evals)

> **ForgeAI is a local AI software-engineering assistant that can inspect and reason about Git repositories using retrieval-augmented generation and a tool-using agent.**

ForgeAI is designed backend-first for repository understanding and controlled exploration. It ingests public Git repositories, indexes code with PostgreSQL and `pgvector`, runs a deterministic hybrid retrieval pipeline (semantic + lexical + path relevance with Reciprocal Rank Fusion), and provides both grounded RAG and an iterative, read-only agent equipped with path-safe repository inspection tools.

---

## Why ForgeAI?

* **Local LLM inference with Ollama:** Runs local models without sending repository code to third-party APIs.
* **Hybrid code retrieval with Reciprocal Rank Fusion (RRF):** Combines dense vector similarity, PostgreSQL native full-text search with code identifier awareness, and hierarchical path relevance to suppress noise files (`package-lock.json`, `components.json`) and elevate genuine implementation code.
* **Grounded RAG for repository questions:** Answers targeted single-hop queries within explicit character budgets and extracts programmatic citations.
* **Bounded tool-using agents:** Explores repositories iteratively with hard iteration, tool-call, line-slicing, and context limits.
* **Programmatic source tracking (`SourceRegistry`):** Allocates verified source IDs exclusively when tool executions read repository files.
* **Repository and path isolation:** Enforces repository-scoped access and prevents path traversal, absolute path usage, or symlink escapes.
* **Deterministic automated tests:** 207-test pytest suite and 39-test Playwright E2E suite for reproducible CI/CD.
* **Behavioral evaluation against a real local LLM:** Automated evaluation harnesses testing hybrid retrieval (MRR 1.0000) and end-to-end RAG/agent performance against Ollama.

---

## Overview

### The Problem

Standard AI coding assistants rely on large context windows to process codebases. When applied to real-world software repositories, this approach introduces significant challenges:

1. **Context Bloat & Cost:** Shoveling whole files or directories into LLM prompts quickly exhausts context limits and incurs high latency and compute cost.
2. **Hallucination & Misattribution:** General-purpose LLMs frequently guess project structure, fabricate import paths, and assert behavior without referencing source code.
3. **Single-Hop Retrieval Inadequacy:** Complex software questions (*"How does auth work across services?"* or *"What dependencies govern this build target?"*) cannot be answered in a single vector search; they require iterative discovery, directory browsing, and targeted code inspection.
4. **Data Privacy & Security:** Commercial repositories often cannot be sent to third-party model APIs, and autonomous agents executing arbitrary shell commands or write operations pose security risks.

### What ForgeAI Solves

ForgeAI addresses these problems through **controlled exploration and verifiable grounding**:

* **Local-First Execution:** Embeddings (`BAAI/bge-small-en-v1.5`) and LLM inference (`Qwen2.5-Coder 7B` via Ollama) run entirely on local infrastructure. When using the Ollama provider, repository content and LLM inference remain on the local machine.
* **Dual-Mode Repository Reasoning:** Offers single-hop RAG for targeted questions, plus an iterative multi-hop agent for exploratory questions requiring multi-file investigation.
* **Read-Only Agent Execution:** The agent interacts with the repository exclusively through three strictly read-only tools: `list_files`, `search_code`, and `read_file`. It cannot write files, delete files, or execute shell commands through its available tools.
* **Authoritative Source Registration:** The model cannot fabricate citations. Citations are registered programmatically in a runtime `SourceRegistry` exclusively when tool executions read actual code chunks.
* **Tool-Error Recovery & Path Correction:** If a tool call fails because of an invalid path or similar recoverable error, the agent can inspect the error and attempt a corrected tool call within its configured limits.

---

## Current Capabilities

* **Repository Ingestion:** Validates public GitHub HTTPS URLs, performs shallow git clones into an isolated storage root, and runs deterministic file discovery.
* **Artifact Filtering:** Automatically ignores non-code directories (`.git`, `node_modules`, `dist`, `__pycache__`, `.venv`), binary extensions, images, media, and files exceeding size thresholds (default 2 MB).
* **Local Code Indexing:** Chunks source code deterministically (50 lines, 10-line overlap) while recording exact 1-indexed line spans, generating 384-dimensional dense vectors using local Sentence Transformers.
* **Hybrid Code Retrieval Pipeline:** Multi-channel candidate generation combining:
  1. Dense semantic vector retrieval (`BAAI/bge-small-en-v1.5` with pgvector cosine distance).
  2. Native PostgreSQL full-text lexical search (`to_tsvector`/`to_tsquery`) with deterministic code-aware rescoring for identifiers, declaration patterns, and distinct-token coverage.
  3. Path and filename relevance scoring token matches across directory structures and filenames.
* **Reciprocal Rank Fusion (RRF) & Noise Deprioritization:** Deterministically merges candidates using RRF ($K=60$) with an automatic 0.1x penalty on build manifests and lock files (`package-lock.json`, `components.json`, `yarn.lock`), guaranteeing clean source-code evidence for RAG.
* **Retrieval Quality Metrics Suite:** Standardized evaluation runner measuring Precision@K, Recall@K, and Mean Reciprocal Rank (MRR) across code identifier, configuration, styling, and semantic queries.
* **Grounded Single-Hop RAG:** Context budget packing (up to 4,000 characters) with prompt encapsulation of untrusted code snippets and programmatic citation extraction.
* **Read-Only Investigation Agent:** A bounded iterative loop where an LLM dynamically selects tools, observes file content, and accumulates evidence.
* **Interactive Next.js Workspace:** Full-stack frontend with repository dashboard, file explorer tree, line-level code viewer with deep-linking, grounded chat interface, and Cmd/Ctrl+K code search with neutral relevance indicators.
* **Strict Safety Boundaries:** Rejection of path traversal (`..`), user home paths (`~`), Windows drive letters, absolute paths, and symlinks escaping the repository root.
* **Grounding Safeguard:** Rejects premature final answers if the agent fails to inspect repository evidence for repository-specific queries.
* **Tool-Error Recovery & Path Correction:** Intercepts path/file resolution failures and injects recovery guidance, allowing the agent to inspect the error and attempt a corrected tool call within its configured limits.
* **Deterministic Testing & Automated Evals:** 207-test pytest suite using a mock LLM for repeatable CI/CD, paired with 39 Playwright E2E tests and behavioral evaluation harnesses for hybrid retrieval (MRR 1.0000) and RAG generation against local Ollama.

---

## Architecture

ForgeAI separates data ingestion, vector indexing, retrieval orchestration, and agent inference into clear layers:

```mermaid
flowchart TD
    subgraph Ingestion_Indexing ["1. Ingestion & Indexing Pipeline"]
        Repo["GitHub Repository\n(HTTPS)"] --> Ingest["Repository Ingestion\n(URL Validation, Shallow Clone)"]
        Ingest --> Discovery["File Discovery & Filtering\n(Path Traversal & Symlink Guards)"]
        Discovery --> Chunker["Line Chunker\n(50 lines / 10 overlap)"]
        Chunker --> LocalEmbed["Local Embeddings\n(BAAI/bge-small-en-v1.5)"]
        LocalEmbed --> PGVector[("PostgreSQL 17 + pgvector\n(repositories, code_files, code_chunks)")]
    end

    subgraph Reasoning_Engine ["2. Hybrid Retrieval & Agent Engine"]
        Client["Developer / Client Request"] --> Router{"API Router\n(/repositories)"}
        Router -->|"POST /{id}/search"| Search["Hybrid Retrieval Pipeline\n(Semantic + Lexical + Path + RRF)"]
        Router -->|"POST /{id}/chat"| RAG["Single-Hop RAG\n(Budget Packing + PromptBuilder)"]
        Router -->|"POST /{id}/agent"| Agent["Bounded Agent Loop\n(State, Memory, Grounding Guard)"]
        
        Search --> PGVector
        RAG --> Search

        Agent <-->|"Structured Tool Calls\n& JSON Observations"| AgentTools["Read-Only Agent Tools\n- list_files\n- search_code\n- read_file"]
        AgentTools -->|"Hybrid Code Search"| Search
        AgentTools -->|"Safe Line Slicing"| LocalDisk["Isolated Cloned Files\n(./data/repositories/<uuid>)"]
    end

    subgraph Inference_Layer ["3. LLM Provider Abstraction"]
        Agent --> LLMAbstraction["AgentLLMService Protocol"]
        RAG --> LLMAbstraction
        
        LLMAbstraction --> Ollama["Ollama Provider\n(Qwen2.5-Coder 7B)\nNative + Tagged Tool Calls"]
        LLMAbstraction -.-> Mock["MockAgentLLM\n(Deterministic Scripted\n& Heuristic Testing)"]
        LLMAbstraction -.-> Gemini["Google Gemini\n(Optional Cloud Provider)"]
    end

    subgraph Verification_Output ["4. Verification & Grounding"]
        AgentTools --> SourceRegistry["Runtime SourceRegistry\n(Allocates stable src_X IDs)"]
        Agent --> GroundingGuard["Grounding Safeguard\n(Checks verified evidence)"]
        GroundingGuard --> Response["AgentResponse\n- Final Answer\n- Verified Source Citations\n- Full Tool Activity Log"]
        RAG --> Response
    end
```

---

## Agent Architecture

The agent orchestrator (`AgentService`) runs a bounded, stateful investigation cycle designed for precision and safety.

```text
User Question
    │
    ▼
Validate Repository Readiness (Status, Disk Files, Indexed Chunks)
    │
    ▼
┌────────────────── Agent Iteration Loop ───────────────────┐
│                                                           │
│  1. Check Boundaries (max_iterations: 8, max_tool_calls: 12)
│  2. Build Context (System Prompt + History + Observations)│
│  3. Call LLM (Ollama / Qwen2.5-Coder 7B)                  │
│                                                           │
│  Decision Fork:                                           │
│  ├── If Tool Call:                                        │
│  │   ├── Validate tool arguments (Pydantic schema)        │
│  │   ├── Enforce path security & repo boundary            │
│  │   ├── Execute read-only tool                           │
│  │   │   ├── Succeeded -> Register Source in SourceRegistry│
│  │   │   └── Failed -> Inject Tool-Error Recovery Guidance │
│  │   └── Append Observation to history & Continue         │
│  │                                                        │
│  └── If Final Answer:                                     │
│      ├── Grounding Check: Did agent inspect evidence?     │
│      │   ├── No (0 sources) -> Reject answer, demand tool │
│      │   └── Yes -> Resolve citations (src_X) and exit    │
└───────────────────────────────────────────────────────────┘
    │
    ▼
Format AgentResponse (Answer + Citations + Tool Activity)
```

### Available Tools (Strictly Read-Only)

| Tool | Purpose | Key Parameters | Safeguards |
| :--- | :--- | :--- | :--- |
| `list_files` | Explores repository directory structure and finds file paths | `path` (relative), `max_files` (1–500) | Path traversal protection, ignores `.git`/binaries |
| `search_code` | Performs semantic vector retrieval across indexed code chunks | `query` (string), `top_k` (1–50) | Repository UUID isolation in pgvector query |
| `read_file` | Reads exact lines from a specific repository file | `path` (relative), `start_line`, `end_line` | Path traversal check, symlink escape check, file size cap (2 MB), read cap (500 lines) |

### Programmatic Grounding (`SourceRegistry`)

Rather than trusting the LLM to write citations in its output, ForgeAI maintains a deterministic `SourceRegistry` in `AgentState`:
1. When `search_code` or `read_file` successfully accesses file content, a unique identifier (`src_1`, `src_2`, ...) is registered with the exact relative path and line numbers.
2. The agent is instructed to cite these source IDs in its text.
3. Upon completion, ForgeAI maps these tags to structured `SourceCitation` objects, preventing hallucinated file references.

### Tool-Error Recovery & Path Correction

When a tool call fails because of an invalid path or similar recoverable error, the agent can inspect the error and attempt a corrected tool call within its configured limits.

* When a path resolution error occurs, the observation returns structured recovery guidance:
  ```json
  {
    "error": "File not found: '.gitignore'",
    "recovery_guidance": "The requested path was not found. This does NOT mean the requested information is unavailable in the repository. Do not invent filenames blindly or conclude evidence is unavailable. Use 'list_files' to discover directory contents or 'search_code' to search for relevant keywords and locate the correct file path."
  }
  ```
* This prompts the agent to call `list_files` or `search_code`, locate the genuine file path, and complete the investigation within its configured limits.

---

## Hybrid Retrieval Pipeline

ForgeAI employs a multi-channel hybrid retrieval pipeline that addresses the core limitation of semantic-only vector search—specifically, that pure semantic similarity frequently ranks irrelevant files (such as `package-lock.json` or `components.json`) alongside authentic implementation code.

```text
User Query
    │
    ├── 1. Semantic Candidate Retrieval (Top 20)
    │      pgvector cosine distance <=> using BAAI/bge-small-en-v1.5 embeddings
    │
    ├── 2. Lexical Candidate Retrieval (Top 20)
    │      PostgreSQL to_tsvector / to_tsquery with code-aware rescoring:
    │      - Distinct query token match weighting
    │      - Exact code identifier recognition (PascalCase, camelCase, snake_case)
    │      - Definition / declaration bonus (const, function, class, export, def)
    │
    └── 3. Path & Filename Relevance (Top 20)
           Deterministic token overlap across filenames and directory paths:
           - Filename matches (+3.0 per token) vs directory matches (+1.0 per token)
           - Component root export prioritization
    │
    ▼
Candidate Deduplication & Identifier Mapping (UUID-keyed chunk pool)
    │
    ▼
Reciprocal Rank Fusion (RRF) Reranking
    RRF(chunk) = W_sem / (K + rank_sem) + W_lex / (K + rank_lex) + W_path / (K + rank_path)
    + Noise / Build manifest penalty (0.1x for package-lock.json, components.json, etc.)
    │
    ▼
Top-K Chunks Passed to ContextBuilder & RAG Pipeline
```

### Retrieval Stages

1. **Semantic Channel:** Embeds the query and computes cosine distance against indexed chunks in PostgreSQL via `pgvector`, partitioned by `WHERE code_files.repository_id = :repo_id`.
2. **Lexical Channel:** Evaluates text relevance via PostgreSQL full-text search (`ts_rank_cd`). A Python rescoring stage then prioritizes chunks matching exact code identifiers (e.g. `CardSpotlight` or `getFileContent`), distinct token coverage, and symbol declaration patterns.
3. **Path Relevance Channel:** Analyzes file paths for query token overlap, heavily weighting filename matches over directory paths and boosting root component files over deep utility lines.
4. **Reciprocal Rank Fusion (RRF):** Fuses the multi-channel candidate rankings into a unified score without assuming semantic and lexical scores share a common numerical scale:
   $$\text{Score}(c) = \sum_{m \in \{\text{sem}, \text{lex}, \text{path}\}} \frac{W_m}{K + \text{Rank}_m(c)}$$
   Configured with $K=60$ and weights $W=1.0$. A $0.1\times$ penalty is applied to lock and configuration manifest files unless the query specifically requests them.

---

## RAG Pipeline

For direct repository queries, ForgeAI provides a grounded RAG endpoint (`POST /repositories/{id}/chat`):

1. **Hybrid Retrieval:** The user question is processed through the 4-channel hybrid retrieval pipeline (semantic, lexical, path relevance, and RRF reranking) to select the highest-quality code chunks.
2. **Repository-Isolated Retrieval:** All retrieval queries are strictly scoped by `repository_id` UUID at the database level.
3. **Budget-Aware Context Packing:** `ContextBuilder` packs chunks in order of fused RRF score up to `rag_max_context_chars` (default 4,000 characters). Chunks exceeding the budget are dropped.
4. **Prompt Encapsulation:** Untrusted code content is wrapped in distinct structural boundaries with system instructions forbidding prompt injection.
5. **Deterministic Citation Extraction:** Citations are extracted exclusively from the verified chunks that fit into the context window.

---

## Local LLM Inference

ForgeAI is built to operate independently of external SaaS APIs using local models:

* **Ollama Integration:** Connects to Ollama's local HTTP API (`http://localhost:11434`) via `httpx.AsyncClient`.
* **Model Configuration:** The current development setup uses `qwen2.5-coder:7b` through Ollama.
* **Dual Parsing Engine:** The `OllamaAgentLLMService` parses both native Ollama JSON tool calls and Qwen XML-style tags (`<tool_call>` / `<tool_response>`).
* **Provider Abstraction:** The `AgentLLMService` interface also supports `MockAgentLLMService` for deterministic unit testing and Google Gemini as an optional cloud provider.
* **Why Local Inference for Codebases?**
  * **Local Inference:** Repository content is not sent to a third-party LLM API when using Ollama.
  * **No External API Costs:** Local execution avoids third-party API token charges and external provider rate limits during local development and evaluation.
  * **Local Autonomy:** Once dependencies, models, and repository data are available locally, the agent and inference pipeline can operate without a third-party LLM API.

---

## Engineering Decisions

### Why Mock LLM Services?
LLM APIs are non-deterministic, network-dependent, and introduce latency into CI/CD pipelines. ForgeAI implements `MockAgentLLMService`, which supports both scripted deterministic responses and rule-based heuristics. This allows the full agent loop, tool execution, security guards, and citation logic to be verified across 188 unit tests in seconds without calling an external model.

### Why Local Ollama?
Running Qwen2.5-Coder 7B locally via Ollama eliminates dependencies on external cloud providers during development and evaluation. It ensures privacy for repository analysis and provides predictable performance without token metering.

### Why an Agent for Repositories?
Single-turn RAG is effective when a query maps cleanly to specific semantic snippets. However, real-world software questions often require discovery (*"Where is the database configuration?"*), verification (*"Does this repo use Makefiles?"*), or cross-referencing multiple files. An iterative agent can inspect directory trees, search code, and read specific lines sequentially until it has sufficient evidence.

### Why Bounded Execution?
Uncontrolled autonomous agent loops can run indefinitely, consume excessive compute, or blow out context windows. ForgeAI enforces strict hard limits: `agent_max_iterations` (default 8), `agent_max_tool_calls` (default 12), `agent_max_file_read_lines` (default 500), and `agent_max_context_chars` (default 12,000).

### Why Read-Only Tools?
Software exploration and code understanding must be safe. By restricting the agent to read-only repository tools, ForgeAI prevents the current agent workflow from modifying repository files, deleting files, or executing shell commands.

---

## Safety and Reliability

| Guard | Implementation Mechanism | Guarantee |
| :--- | :--- | :--- |
| **Repository Isolation** | Foreign keys & SQL constraints (`WHERE repository_id = :id`) | Database queries and repository tools enforce repository-scoped access. |
| **Path Traversal Protection** | Rejection of traversal components (`..`, `~`), leading path separators (`/`, `\`), and Windows drive letters (`C:`) | Tools reject attempts to navigate outside the cloned repository's assigned directory. |
| **Symlink Protection** | Canonical path resolution via `Path.resolve()` validated against `repo_root.resolve()` | Symbolic links resolving outside the repository root are ignored during file discovery and rejected with a security error during tool reads. |
| **File Size Constraints** | Pre-read stat checks (`max_file_size_bytes = 2MB`) | Prevents memory exhaustion from large generated binaries or minified bundles. |
| **Read Line Constraints** | Windowed line slicing (`agent_max_file_read_lines = 500`) | Protects model context from being overwhelmed by oversized source files. |
| **Grounding Safeguard** | Validation against `SourceRegistry` before final answer acceptance | Rejects answers that attempt to make claims about repository code without having inspected files. |

---

## Evaluation

ForgeAI includes an automated behavioral evaluation harness (`backend/evals`) that evaluates the end-to-end `AgentService` against local Ollama running `qwen2.5-coder:7b`. This is an internal behavioral regression harness designed to evaluate agent tool-use fidelity, investigation trajectory, and citation grounding on a real codebase, not a standardized industry benchmark.

### Evaluation Methodology
* **Target Repository:** GitHub's `github/gitignore` repository, containing templates for multiple languages and technologies.
* **Execution:** Real agent loop, real PostgreSQL + pgvector database, real disk file tools, real local LLM inference.
* **Deterministic Verification:** Every test case checks behavioral invariants:
  * `must_be_completed`: Agent reached a concluded state.
  * `min_sources` / `max_sources`: Verified citations produced in `SourceRegistry`.
  * `min_tool_calls` / `max_tool_calls`: Valid tool interaction trajectory.
  * `required_tools`: Specific tools required for the task (`search_code`, `read_file`, `list_files`).
  * `answer_contains`: Factual assertions that must be present in the grounded answer.

### Current Evaluation Results

| Suite | Scope | Result | Status |
| :--- | :--- | :--- | :--- |
| **Hybrid Retrieval Evaluation** | 4 multi-channel ranking benchmarks against PostgreSQL | **MRR: 1.0000** \| **Recall@3: 1.0000** \| **P@3: 0.67** | Verified |
| **RAG Behavioral Evaluation** | 3 grounded repository Q&A queries (Real Ollama + Qwen2.5-Coder 7B) | **3 / 3 Passed** (100%) | Verified |
| **Agent Behavioral Evaluation** | 10 repository investigation cases (Ollama + Qwen2.5-Coder 7B) | **10 / 10 Passed** (100%) | Verified |
| **Pytest Unit & Integration Suite** | Backend unit, integration, retrieval, security, RAG, and agent contracts | **207 Passed, 1 Skipped** | Verified |
| **Playwright E2E Suite** | Full-stack user flows (Dashboard, Workspace, File Viewer, Search, Chat) | **39 / 39 Passed** (100%) | Verified |

*(The single skipped pytest is an unprivileged Windows symlink creation check).*

#### Hybrid Retrieval Quality Benchmark Breakdown

Evaluated against the indexed portfolio repository (`MasoomehMokhtari78/Portfolio`, 29 files, 230 chunks):

| Benchmark Case | Representative Query | Top Retrieved Code Files | P@3 | R@3 | RR | Noise Suppression |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| **Case 1: Section Discovery** | *"Where is the projects section handled or rendered?"* | `Projects.tsx`, `page.tsx` | 1.00 | 1.00 | 1.00 | `package-lock.json` & `components.json` eliminated |
| **Case 2: Style Configuration** | *"Where are global styles and fonts configured?"* | `globals.css`, `layout.tsx` | 0.67 | 1.00 | 1.00 | Manifests suppressed |
| **Case 3: Code Identifier** | *"Where is CardSpotlight implemented?"* | `card-spotlight.tsx`, `card.tsx` | 0.33 | 1.00 | 1.00 | Exact implementation file ranked #1 |
| **Case 4: Semantic Concept** | *"Where does the developer introduce herself?"* | `page.tsx`, `Introduction.tsx` | 0.67 | 1.00 | 1.00 | 100% Noise-free top-2 |

* **Mean Reciprocal Rank (MRR):** **1.0000**
* **Mean Recall@3:** **1.0000**
* **Mean Precision@3:** **0.6667**

### Engineering Insights from Evaluation
1. **Agent Path Recovery:** The model initially guessed generic filenames (`.gitignore`) instead of repository-specific templates (`Python.gitignore`). We implemented structured error detection in `_is_recoverable_path_error` and injected actionable `recovery_guidance`. Guided by the error observation, the agent falls back to `list_files` or `search_code`, discovers the correct path, and reaches a 10/10 (100%) pass rate.
2. **Hybrid Retrieval Noise Elimination:** Semantic vector embeddings frequently scored `package-lock.json` and `components.json` highly for general code questions because of high token density. Implementing PostgreSQL full-text search with code-aware symbol weighting and Reciprocal Rank Fusion ($K=60$) with a 0.1x noise penalty completely eliminated manifest pollution, lifting MRR to 1.0000.


---

## Example Agent Flow

Here is an actual investigation trajectory recorded by the evaluation harness for the query:
> *"What specific file patterns and rules are configured in Joomla.gitignore?"*

```text
User Question
    │
    ▼
Iteration 1: Agent decides it needs to locate and read Joomla.gitignore
    │
    ├── Tool Call: read_file(path="Joomla.gitignore", start_line=1, end_line=100)
    │   ├── Security Check: Path within repo bounds? (Yes)
    │   ├── File Read: 54 lines read from cloned repository
    │   └── Source Registration: Registered as [src_1] (Joomla.gitignore:L1-54)
    │
    ▼
Iteration 2: Agent analyzes file content from Observation [src_1]
    │
    ├── Evidence Observed:
    │   - Installation directories: /installation/
    │   - Configuration files: configuration.php
    │   - Cache & log folders: /cache/*, /administrator/cache/*, /logs/*
    │
    └── Final Answer Produced:
        "Based on Joomla.gitignore (src_1), the configured rules exclude:
         1. Configuration files (configuration.php)
         2. Cache and temporary directories (/cache/*, /administrator/cache/*)
         3. Log files and error logs (/logs/*)
         4. Installation directories (/installation/)"
    │
    ▼
Programmatic Citation Verification:
    - src_1 -> path: "Joomla.gitignore", lines: 1-54, type: "read"
    - Status: COMPLETED (Iterations: 2, Tool Calls: 1, Sources: 1)
```

---

## Tech Stack

| Component | Technology | Role |
| :--- | :--- | :--- |
| **Backend Framework** | [FastAPI](https://fastapi.tiangolo.com/) | High-performance asynchronous API framework |
| **Runtime & ASGI** | [Python 3.10+](https://www.python.org/) & [Uvicorn](https://www.uvicorn.org/) | Modern asynchronous runtime |
| **Relational Database** | [PostgreSQL 17](https://www.postgresql.org/) | Relational storage for repositories, files, and chunks |
| **Vector & Search** | [pgvector](https://github.com/pgvector/pgvector) + PostgreSQL FTS | Hybrid vector and lexical search with Reciprocal Rank Fusion |
| **ORM & Migrations** | [SQLAlchemy 2.0](https://www.sqlalchemy.org/) & [Alembic](https://alembic.sqlalchemy.org/) | Asynchronous database access and schema migrations |
| **Embeddings** | [Sentence Transformers](https://sbert.net/) (`BAAI/bge-small-en-v1.5`) | Local 384-dimensional dense code embeddings |
| **Local LLM Inference** | [Ollama](https://ollama.ai/) (`Qwen2.5-Coder 7B`) | Local LLM for function-calling, grounded RAG, and agent reasoning |
| **Testing & CI** | [pytest](https://pytest.org/) (207 tests) & [Playwright](https://playwright.dev/) (39 E2E tests) | Deterministic automated backend and frontend validation |
| **Evaluation** | Automated Evaluation Harnesses | Benchmarks for Hybrid Retrieval (MRR), RAG grounding, and Agent trajectory |
| **Containerization** | [Docker Compose](https://docs.docker.com/compose/) | Full-stack orchestration (PostgreSQL, FastAPI backend, Next.js frontend) |
| **Frontend** | [Next.js](https://nextjs.org/) + TypeScript + Tailwind + shadcn/ui | Full-featured developer workspace (dashboard, viewer, search, chat) |

---

## Running Locally

### Prerequisites

* **Docker & Docker Compose** (for running the full stack)
* **Ollama** installed and running on the host machine (not containerized, providing direct GPU access)
* **Git** installed on your system PATH
* *(Optional for local host testing)* **Python 3.10+** and **Node.js 18+**

### 1. Clone the Repository

```bash
git clone https://github.com/MasoomehMokhtari78/forge-ai.git
cd forge-ai
```

### 2. Set Up Local Ollama Model (Host Machine)

ForgeAI connects to Ollama running on your **host machine** (accessible to containers via `host.docker.internal:11434`):

```bash
# Pull the recommended model if you haven't already
ollama pull qwen2.5-coder:7b

# Ensure Ollama is running
ollama run qwen2.5-coder:7b
```

### 3. Configure Environment

Create your `.env` file from the provided example if you need custom credentials:
```bash
cp backend/.env.example backend/.env
```

> **Note on Network Architecture:**
> * Docker Compose automatically injects `DATABASE_URL=postgresql+psycopg://forgeai:forgeai@postgres:5432/forgeai` and `OLLAMA_BASE_URL=http://host.docker.internal:11434` into the backend container.
> * If running scripts or tests directly on the host machine, the default `.env` points to `localhost:5432` and `http://localhost:11434`.

### 4. Start Full-Stack Environment

Start the database, FastAPI backend, and Next.js frontend with a single command:

```bash
docker compose up --build
```

Verify that all three services are running:
```bash
docker compose ps
```

### 5. Access Local Services

Once started, the services are available at:

* **Frontend:** [http://localhost:3000](http://localhost:3000)
* **Backend API:** [http://localhost:8000](http://localhost:8000)
* **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
* **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

### Development & Testing

#### Database Migrations
Migrations are managed with Alembic. When needed, run from the backend:
```bash
cd backend
alembic upgrade head
```

#### Running Backend Pytest Suite
To run tests against the dedicated test database, initialize it once in Docker:
```bash
docker compose exec postgres createdb -U forgeai forgeai_test
```

Then run pytest from the `backend/` directory:
```bash
cd backend
pytest
```
*Expected: 207 passed, 1 skipped.*

#### Running Frontend Playwright Suite
Run the full browser end-to-end test suite from the `frontend/` directory:
```bash
cd frontend
npx playwright test
```
*Expected: 39 passed.*

#### Running Evaluation Suites
With Ollama running `qwen2.5-coder:7b` on the host:
```bash
cd backend

# Hybrid Retrieval Benchmark (P@3, R@3, MRR)
python -m evals.run_retrieval_eval

# RAG Behavioral Evaluation (Grounded Q&A against live Ollama)
python -m evals.run_rag_eval

# Agent Behavioral Evaluation Harness (Multi-turn tool-using agent)
python -m evals.run_agent_eval
```

---

## API Quickstart

### Ingest a Repository
```bash
curl -X POST http://localhost:8000/repositories \
  -H "Content-Type: application/json" \
  -d '{"url": "https://github.com/github/gitignore"}'
```
*Response returns repository JSON with an `id` field. Replace `<repository_id>` in subsequent commands with the returned UUID.*

### Index the Repository
```bash
curl -X POST http://localhost:8000/repositories/<repository_id>/index
```

### Query via Grounded RAG (Hybrid Retrieval + Ollama)
```bash
curl -X POST http://localhost:8000/repositories/<repository_id>/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Where is the projects section handled or rendered?"}'
```

### Query via Grounded Agent
```bash
curl -X POST http://localhost:8000/repositories/<repository_id>/agent \
  -H "Content-Type: application/json" \
  -d '{"question": "What patterns are ignored in Python.gitignore?", "max_iterations": 8}'
```

---

## Roadmap

### Completed (Current Foundation)
- [x] **Repository Ingestion & Cloning:** Git cloning, file discovery, size limits, and artifact filtering.
- [x] **Code Chunking & Local Embeddings:** Line-tracked chunking with local `BAAI/bge-small-en-v1.5` embeddings.
- [x] **Hybrid Code Retrieval & RRF Reranking:** Dense vector + PostgreSQL lexical FTS + path relevance + noise manifest suppression (MRR 1.0000).
- [x] **Grounded RAG Pipeline:** Context budget packing and programmatic citation extraction using hybrid evidence.
- [x] **Read-Only Repository Agent:** Bounded iterative loop with `list_files`, `search_code`, and `read_file`.
- [x] **Local LLM Provider:** Ollama integration running `Qwen2.5-Coder 7B` with native and tagged tool calling.
- [x] **Interactive Web Frontend:** Next.js application for repository management, visual code exploration, grounded chat, and search.
- [x] **Security Constraints:** Path traversal, symlink resolution, and repository boundary protection.
- [x] **Grounding Safeguard & Citations:** `SourceRegistry` verifying evidence before answer acceptance.
- [x] **Tool-Error Recovery & Path Correction:** Interception of missing file paths with recovery guidance allowing corrected tool attempts.
- [x] **Behavioral Evaluation Harnesses:** Automated evaluation suites for Hybrid Retrieval, RAG Q&A, and Agent Trajectory.
- [x] **Deterministic Test Suites:** 207 backend unit/integration tests and 39 Playwright E2E browser tests.

### Planned Work
- [ ] **Design Pattern & Architecture Analysis:** High-level architectural reasoning and dependency graph analysis.
- [ ] **Tree-sitter AST Chunking:** Syntactic boundary preservation to avoid splitting code functions across chunks.
- [ ] **Code Modification Agent:** Controlled, branch-isolated code generation and refactoring agent.
- [ ] **Test-Driven Code Changes:** Validation agent that executes test suites to verify generated modifications.
