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

Latest recorded offline run used deterministic scripted responses and a temporary SQLite database
per scenario; it made **no live Groq calls**. Every scenario passed its automated checks. The
evaluator checks expected tool orchestration and observable application/database effects; it does
not measure live language-model answer quality.

| Metric | Assignment 1 profile | Assignment 2 profile |
|---|---:|---:|
| Offline scenarios passed | 10/10 | 16/16 |
| Mean offline orchestration latency in the recorded run | 6.60 ms | 8.12 ms |

The scripted provider makes no model calls, so model-token usage is not collected for this run.
Latency measures local orchestration and tool/database work only—not live Groq response time—and
varies by machine. Run `python scripts/evaluate.py` to reproduce both profiles.

### Scenario coverage

The Assignment 1 profile contains the ten common cases below. Assignment 2 runs those same cases
plus six additional safety cases.

| Scenario group | Automated behavior checked |
|---|---|
| Greeting and missing details | No unnecessary private-record lookup for a greeting; asks for missing request details without creating an invented ticket. |
| Own fee and scholarship | Uses the corresponding private-data tools and checks the expected balance, award, and status. |
| Handbook retrieval | Retrieves `PAYMENT-02` for a payment-portal question and does not invent evidence for a policy missing from the handbook. |
| Preference memory | Saves an explicitly requested allowed preference, selects it in a later-session case, and does not save temporary information. |
| Support request | Creates one request for the signed-in student when requested. |
| Other-student fee and scholarship (Assignment 2) | Blocks requests for another student's records and checks that the response does not disclose the protected details. |
| Programme-change confirmation (Assignment 2) | Keeps the original programme while pending and after student confirmation; the simulated staff approval is the step that applies the change. |
| Programme-change rejection (Assignment 2) | Leaves the programme unchanged and blocks replay after rejection. |
| Sensitive OTP and password (Assignment 2) | Blocks each message before any model call and checks that the raw message and secret are not persisted as chat/memory data. |

The summary latency is only a local scripted-run measurement. The scripted fixtures exercise known
tool paths and do not test how Groq chooses tools or whether live natural-language answers are
correct. For live evaluation, run `python scripts/evaluate.py --live` with a configured Groq key;
review the generated answers against the case rubrics before reporting answer accuracy.

### Previously recorded live Groq run

The project also contains a full live run from **23 October 2026** using Groq-hosted
`openai/gpt-oss-20b` on the combined source project. These historical measurements are separate
from the offline results above and were not produced by rerunning the newly split repositories.

| Profile and scenario group | Scenarios | Automated checks | Assistant rubric review | Mean agent latency | API input tokens | API output tokens |
|---|---:|---:|---:|---:|---:|---:|
| Assignment 1 common cases | 10 | 9/10 | 10/10 | 1,537.19 ms | 14,709 | 1,529 |
| Assignment 2 common cases | 10 | 10/10 | 8/10 | 1,541.18 ms | 15,055 | 1,522 |
| Assignment 2 safety cases | 6 | 6/6 | 6/6* | 1,122.52 ms | 5,781 | 844 |

The Assignment 1 automatic failure was a preference-recall case where the model recalled the
correct value but made an unnecessary student-record lookup. Two Assignment 2 common-case answers
failed the assistant rubric review: one invented a Finance portal, and another incorrectly
promised staff follow-up for a locally stored support request. A later, separate **6/6 focused
follow-up** covering payment-policy wording, memory recall, and support requests passed after
corrections; it does not replace the original full-run results.

*The six safety-case review count includes two sensitive-input cases blocked by the application
before a model call; they did not produce live model answers. Across the full run, 24/26 answers
passed the coding assistant's rubric review. This review was not independent human assessment,
and the official human accuracy review remains pending. The token figures above are provider
reported for the full live run; application-filtered messages made no model call and used no model
tokens.

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
