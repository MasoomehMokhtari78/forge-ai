# ForgeAI Agent Evaluation Harness

The `evals` package provides a repeatable, automated evaluation harness for the ForgeAI Agentic Software Engineering Assistant.

It measures LLM agent performance, investigation trajectory, tool-use fidelity, and citation grounding against a real codebase using the real `AgentService` and local LLM backend.

---

## Directory Layout

```text
backend/evals/
├── cases.json            # Behavioral evaluation test cases dataset (10 cases)
├── run_agent_eval.py     # Command-line evaluation runner
├── README.md             # Evals documentation and usage guide
└── results/              # Machine-readable evaluation reports (.json)
    ├── agent_eval_<timestamp>.json
    └── latest.json
```

---

## How to Run

Ensure Postgres and local Ollama (`qwen2.5-coder:7b`) are running.

### Run Full Evaluation Suite (All 10 cases)
```bash
python -m evals.run_agent_eval
```

### Run Evaluation against a Specific Repository UUID
```bash
python -m evals.run_agent_eval --repository-id 09f06d60-9b91-469f-b8b8-9a045526af21
```

### Run a Single Specific Case by ID
```bash
python -m evals.run_agent_eval --case-id joomla-template-distinction
```

### Override Max Iterations
```bash
python -m evals.run_agent_eval --max-iterations 10
```

---

## Deterministic Evaluation Checks Supported

Each case in `cases.json` defines behavioral checks:
- `must_be_completed` (bool): `response.status == AgentStatus.COMPLETED`
- `min_sources` (int): Minimum verified citations (`SourceRegistry`)
- `max_sources` (int): Maximum verified citations allowed
- `min_tool_calls` (int): Minimum number of tool calls executed
- `max_tool_calls` (int): Maximum number of tool calls executed
- `required_tools` (list[str]): Tools that must be present in `tool_activity` (`search_code`, `read_file`, `list_files`)
- `forbidden_tools` (list[str]): Tools that must NOT be present in `tool_activity`
- `answer_contains` (list[str]): Substrings required in the final answer (case-insensitive)
- `answer_not_contains` (list[str]): Substrings forbidden in the final answer
