# NoteSoFast

A personal knowledge management tool that introduces desirable difficulties.

See Catalog.pdf for project details.

## Setup

Tested on Python 3.11.

```bash
python3.11 -m venv venv
source venv/bin/activate          # macOS / Linux
# venv\Scripts\activate           # Windows

pip install -r requirements.txt

cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env, or leave it blank to run in mock mode

python run.py
```

The app runs at http://localhost:3000.

### Mock mode

The application, by default, runs in mock mode so it doesn't incur API cost. To change it, add an API key and click the "Mock Mode" button in the sidebar of the chat to switch to "Live API". Then, the responses will mirror the example provided in the video walkthrough.

## Evaluation

The system was evaluated using a simulated student-teacher protocol (Phung et al., 2024). Claude Sonnet acts as the tutor, and Claude Haiku acts as the student under four behavioral profiles: novice, intermediate, expert, and gaming. Results are in `evaluation/logs/`. The analysis script (`evaluation/analyze.py`) produces the figures and statistics reported in the final paper.

To re-run the evaluation:

```bash
python evaluation/run_eval.py
```

Note 1: It will re-run the evaluation on the corpus of information stored locally, please change it to the desired content - if needed.

Note 2: The evaluation calls the live Anthropic API and will incur cost.

## Author

Jake Reinhart, MS Computer Science (AI specialization)
