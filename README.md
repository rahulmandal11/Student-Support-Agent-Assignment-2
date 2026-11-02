# Student Support Agent — Assignment 2

A Flask-based student-support agent that combines Assignment 1's tool-using assistant with identity-aware access control, privacy protections, approval-gated sensitive actions, staff workflows, and an audit trail. Bundled records are synthetic; use this project only with fictional data.

## Features

- Groq tool-calling agent for student records, fees, scholarships, handbook policies, support requests, and preferences.
- Student and staff/admin sign-in with role separation, CSRF protection, session controls, and throttling.
- Owner-scoped access to student data, chat history, traces, and preferences.
- Sensitive-message filtering before provider calls and local persistence.
- Two-stage programme-change workflow: student confirmation followed by staff approval; records change only after approval.
- Staff support-request replies and status updates, with admin audit and account views.
- SQLite persistence and offline evaluation with scripted model responses.

## Requirements

- Python 3.11 or newer
- A Groq API key for live AI responses (optional for the UI and offline tests)

## Setup

Create and activate a virtual environment, then install the project dependencies:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Edit `.env` locally:

- Set `DEMO_ACCOUNT_PASSWORD` to a unique password of at least 12 characters. It is shared only by the synthetic local demo accounts and is never included in this repository.
- Set `GROQ_API_KEY` to enable live model responses. Without it, the application and offline tests still run, but chat reports that the provider is not configured.
- `SECRET_KEY` can remain empty; the app generates an ignored local key on first run.
- Leave `ASSIGNMENT_PROFILE=a2`.

The demo account IDs are `STU001`, `STU002`, `STF001`, and `ADM001`. Use the password you set in your local `.env`. Never use real student records or credentials.

## Run

```powershell
python app.py
```
## Verify

```powershell
python -m pytest -q
python scripts/evaluate.py
```

The offline evaluator uses scripted model responses and makes no external API calls. Live evaluation is optional and requires a configured Groq key:

```powershell
python scripts/evaluate.py --live
```

The live evaluator may write chat outputs, traces, and result files locally. Those generated files are intentionally excluded from Git.

## Evaluation

Latest offline run used scripted responses and made **no live Groq calls**. Every automated
check passed. These checks cover tool orchestration and observable application/database effects;
they do not establish answer quality from a live language model.

| Metric | Assignment 1 profile | Assignment 2 profile |
|---|---:|---:|
| Automated scenarios passed | 10/10 | 16/16 |
| Mean orchestration latency | 6.60 ms | 8.12 ms |
| Model tokens | N/A (scripted provider) | N/A (scripted provider) |
| Live answer accuracy | Not measured | Not measured |

The Assignment 1 profile covers ten common student-support scenarios. Assignment 2 covers those
same ten scenarios plus six safety scenarios for cross-student data access, programme-change
approval/rejection, and sensitive inputs. Latency is local offline orchestration time, not live
Groq response time; results vary by machine and environment. Reproduce the checks with
`python scripts/evaluate.py`.

## Project layout

```text
app.py
student_support/   Flask app, agent, tools, database, UI
data/              Synthetic student/staff records and handbook
docs/              Privacy and approval design notes
scripts/           Offline/live evaluation runner
tests/             Automated tests
```

Local configuration, generated databases, session keys, caches, and evaluation output are excluded by `.gitignore`. See [the privacy and approval notes](docs/PRIVACY_AND_APPROVALS.md) for the application’s access-control and sensitive-action model.
