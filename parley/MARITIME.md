# Putting Parley agents on Maritime (one micro-VM per participant)

Maritime builds from a GitHub repo with a Dockerfile at its root. `parley/Dockerfile` runs one
agent (`agent.service:app`) on `$PORT`, keeps its state in `/data`, and answers `GET /health` and
`POST /chat` as Maritime's container contract asks. The orchestrator stays on the laptop.

The signup and payment steps below are for a person, not Claude: sign up at maritime.sh, open Billing, subscribe to the Growth plan, and enter promo code `HACKNCSTATE`.

1. Push `parley/` to GitHub so that `Dockerfile` sits at the repo root. `.env` is gitignored, so keep it out.
2. Install the CLI and sign in:
   ```bash
   curl -fsSL https://maritime.sh/install.sh | sh
   maritime onboard --json        # follow sign_in.url; verify your email
   ```
3. Create one agent box per sibling. Every box uses the same repo; the orchestrator tells each box who it is:
   ```bash
   maritime create parley-ana  --repo https://github.com/<you>/<repo> --public --port 8080 --json
   maritime create parley-ben  --repo https://github.com/<you>/<repo> --public --port 8080 --json
   maritime create parley-cara --repo https://github.com/<you>/<repo> --public --port 8080 --json
   ```
4. For Gemma inside the agents, put the key in Maritime's secret store, not in the repo:
   ```bash
   maritime env set parley-ana GEMINI_API_KEY=... GEMMA_MODEL=gemma-4-26b-a4b-it --reload --json
   ```
5. Wait for `maritime status parley-ana --json` to report `active`, then find the public URL in that output or on the dashboard at maritime.sh/agents. Check it with `curl <url>/health`.
6. Start the laptop side, pointing slot 1, 2 or 3 at the Maritime URL. Any slot without a URL gets a local agent:
   ```bash
   AGENT1_URL=https://<parley-ana-url> ./run_local.sh
   ```
   That sibling's phone form is now `https://<parley-ana-url>/`.

If a build fails, `maritime history parley-ana --json` shows the build log. To redeploy, run `maritime deploy parley-ana --json`.
