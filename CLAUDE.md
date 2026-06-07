<!-- SPECKIT START -->
Active feature: **001-morning-coaching-brief** (MVP Morning Coaching Brief).

For technologies, project structure, and key decisions, read the current plan and its
design artifacts:
- Plan: `specs/001-morning-coaching-brief/plan.md`
- Spec: `specs/001-morning-coaching-brief/spec.md`
- Research / decisions: `specs/001-morning-coaching-brief/research.md`
- Data model: `specs/001-morning-coaching-brief/data-model.md`
- Contracts: `specs/001-morning-coaching-brief/contracts/`
- Quickstart / validation: `specs/001-morning-coaching-brief/quickstart.md`
- Constitution (non-negotiable principles): `.specify/memory/constitution.md`

Stack: Python 3.11+, FastAPI, LangGraph (explicit DAG — no autonomous loops), Amazon
Bedrock (Claude; model id from config) + Titan embeddings, SQLite/DuckDB + FAISS/Chroma
behind a clean data-access interface, pytest. Synthetic data only in the POC.
<!-- SPECKIT END -->
