# NoteSoFast

A Flask-based personal knowledge management (PKM) system that uses retrieval-augmented generation, a knowledge graph, and Bayesian Knowledge Tracing to deliver adaptive study sessions over a learner's own notes.

Final project for CS 6460: Educational Technology, Georgia Tech OMSCS.

## Overview

NoteSoFast turns a user's notes into an interactive study tool. Notes are ingested into a vector store and a knowledge graph; the system then generates questions over that material, adapts difficulty based on learner performance, and provides progressively scaffolded hints when the learner struggles.

Core features:
- RAG-backed question generation grounded in the learner's own notes
- Knowledge graph for concept relationships and retrieval context
- Adaptive difficulty across four levels (L1 to L4)
- Bayesian Knowledge Tracing to estimate concept mastery
- Progressive hint scaffolding tied to BKT state

## Architecture

- **Backend:** Flask
- **Vector store:** FAISS
- **Knowledge graph:** [graph store you used]
- **LLM:** [model/provider]
- **Frontend:** [what you used]

See `/docs/architecture.md` for the full design.

## Setup

Tested on Python 3.11.

```bash
# 1. Create and activate a virtual environment
python3.11 -m venv venv
source venv/bin/activate    # macOS/Linux
# venv\Scripts\activate     # Windows

# 2. Install dependencies
pip install -r src/requirements.txt

# 3. Set environment variables
cp src/.env.example src/.env
# Edit src/.env and add your LLM API key

# 4. Run the app
cd src
flask run
```

The app will be available at `http://localhost:5000`.

If you do not have an LLM API key, set `MOCK_MODE=true` in `.env` to run the UI against canned responses. A recorded demo of the full system running with a real key is available in `/demo`.

A step-by-step walkthrough is in `/test/test_script.md`.

## Repository Structure

```
NoteSoFast/
├── Catalog.pdf              Archive contents and submission catalog
├── README.md                This file
├── src/                     Application code
├── data/                    Sample notes, knowledge graph, FAISS index
├── docs/                    Proposal, architecture, design decisions
├── evaluation/              Simulated BKT evaluation
│   ├── final_paper.pdf
│   ├── logs/                Per-profile run logs (novice, intermediate, expert, gaming)
│   └── analysis/            Scripts and notebooks used to generate figures
├── demo/                    Recorded screencast of full system run
└── test/                    Test walkthrough
```

## Evaluation

The system was evaluated using a simulated student-teacher protocol with four behavioral profiles (novice, intermediate, expert, gaming). Logged statistics for each profile and the analysis pipeline that produced the paper's figures are in `/evaluation`. The full write-up is in `evaluation/final_paper.pdf`.

## AI Assistance Disclosure

Per the CS 6460 AI Collaboration Policy, the following disclosure documents AI use on this project.

**Tools used:** [Claude / ChatGPT / GitHub Copilot / etc., list every tool you used]

**What AI assisted with:**
- Scaffolding Flask routes and project structure
- Implementing portions of the RAG pipeline and FAISS integration
- Drafting and debugging the Bayesian Knowledge Tracing update logic
- Generating boilerplate frontend code
- Debugging runtime errors and dependency issues
- Drafting the simulated student profile prompts used in evaluation

**What is original to me:**
- Project conception, scope, and proposal
- System architecture and the integration decisions linking RAG, the knowledge graph, BKT, and the hint scaffolding system
- The simulated student-teacher evaluation protocol, including the four-profile design and the metrics chosen
- All analysis and interpretation of evaluation results
- All natural-language writing in the final paper, design documents, and this README, in accordance with the policy that final paper and presentation text must be the student's own

AI-generated code segments are marked inline where they were used substantially without modification, following the format described in the academic honesty policy.

## Author

Jake Reinhart
Georgia Tech OMSCS, MS Computer Science (AI specialization)

## License

This submission is provided for evaluation in CS 6460. Public release rights are retained by the author per the course's content-sharing policy.