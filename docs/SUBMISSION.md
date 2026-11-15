# Submission checklist (Google Classroom, one submission)

| # | Item the assignment asks for | Status | What Marvan does |
|---|---|---|---|
| 1 | Public GitHub repo in the required structure | code ready | Create a repo under **your own** account, then commit in steps (see below) and push |
| 2 | Deployed link, live until grades are released | config ready (`render.yaml`, `infra/docker/allinone.Dockerfile`) | Deploy on Render (steps below) and paste the URL in the README and Classroom |
| 3 | Reviewer login in a **private comment** (not in the repo) | text below | Paste it as a private comment on the submission |
| 4 | R&D report as a PDF | `docs/REPORT.pdf` (regenerate after the Groq runs) | Attach the PDF |
| 5 | Link to the 3-minute demo video | `docs/GigBid_demo_Marvan_Shahid_23i-0800.mp4` | Upload to YouTube (Unlisted) or Google Drive (anyone with link), paste the link |
| 6 | Portfolio MCP server published | `mcp_servers/portfolio/README.md` documents `uvx --from git+https://github.com/MarvanShahid/Gigbid gigbid-portfolio-mcp` | Replace `<you>` with your GitHub username after pushing |
| 7 | Technical write-up link (LinkedIn / Medium / blog, 1,200–1,800 words) | outline in `docs/WRITEUP.md` | Write it in your own words and publish |
| 8 | Judge calibration with your own labels | `evals/datasets/judge_labels.csv` | **You** score the 30 proposals 1–5; the kappa is meaningless if anyone else does it |

## 1. GitHub (your account)

```powershell
cd C:\Users\DELL\Documents\assignment2_agentic_AI
git init -b main
git config user.name "Marvan Shahid"
git config user.email "<your email>"
# commit in logical steps rather than one giant commit (the instructor reviews history)
git add pyproject.toml .gitignore .env.example Makefile README.md ; git commit -m "Project skeleton"
git add scripts/build_standin_data.py data sim gigsim ; git commit -m "Synthetic stand-in data and GigSim simulator"
git add mcp_servers agent/marketplace_port.py agent/mcp_client.py agent/health.py ; git commit -m "MCP servers, marketplace port, tool gateway"
git add rag ; git commit -m "RAG: ingestion, variants, claim verification"
git add agent ; git commit -m "LangGraph bid and conversation graphs, memory, X4"
git add apps/api worker ; git commit -m "FastAPI backend and Celery worker"
git add apps/web ; git commit -m "Next.js web app and Playwright tests"
git add tests evals infra .github render.yaml ; git commit -m "Tests, evaluations, CI and deployment"
git add docs ; git commit -m "Docs and R&D report"
git add -A ; git commit -m "Remaining files"
git remote add origin https://github.com/MarvanShahid/Gigbid.git
git push -u origin main
```

Check `git status` before pushing: `.env` must **not** be listed (it is in `.gitignore`).

## 2. Deploy on Render (free)

1. render.com → sign in with GitHub → **New → Blueprint** → select the `gigbid` repo (it reads `render.yaml`).
2. When asked, set `GROQ_API_KEY` (your key) and `REVIEWER_PASSWORD` (choose one). Create.
3. Wait for the build (about 10 minutes the first time), then open `https://gigbid-xxxx.onrender.com/login`.
4. Sign in with `reviewer@gigbid.dev` and your reviewer password, click **Scout now**, and check that jobs appear.
5. Free instances sleep after 15 minutes idle. Open the URL shortly before the grading window and the viva.
   The SQLite data resets when the instance restarts, which is fine for a demo; Postgres is optional (`DATABASE_URL`).

## 3. Private comment for the submission (paste, fill in)

```
Reviewer login for GigBid: <deployed URL>/login
Email: reviewer@gigbid.dev
Password: <the REVIEWER_PASSWORD you set on Render>
The account is preloaded with the AI/ML-engineer persona. Click "Scout now" in the inbox to start.
```

## 4. Submission text (Classroom)

```
GigBid — Marvan Shahid (23i-0800)
Live app: <deployed URL>   (reviewer login in private comment)
GitHub: https://github.com/MarvanShahid/Gigbid
Demo video: <YouTube/Drive link>
Portfolio MCP server: https://github.com/MarvanShahid/Gigbid/tree/main/mcp_servers/portfolio
Technical write-up: <LinkedIn/Medium link>
R&D report: attached (REPORT.pdf)
Note: the GigSim starter kit was not available to me, so results are on a documented synthetic stand-in (docs/DATA_CARD.md).
```

## 5. After the Groq runs

```powershell
python scripts\check_models.py          # fix any model marked NOT AVAILABLE in agent\config.yaml
python -m evals.runners.tool_granularity
python -m evals.runners.architecture_compare --profile open
python -m evals.runners.graph_eval --profile open --per-persona 50
python -m evals.runners.judge_calibration --score      # after you fill judge_labels.csv
python scripts\make_tables.py
```

Then update `docs/REPORT.md` sections 3, 5 and 9 with the new numbers, and rebuild the PDF (open REPORT.md in VS Code →
"Markdown PDF" extension, or paste it into Google Docs and export as PDF).
