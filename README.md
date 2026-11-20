# k8s-yaml-evaluator

Evaluate a Kubernetes Deployment manifest for deployment correctness and production-readiness — with rubric-based written feedback, not just a pass/fail.

```bash
python evaluator.py examples/good/deployment.yaml
# Score: 100/100 — Verdict: Deploy

python evaluator.py examples/bad/deployment.yaml
# Score: 0/100 — Verdict: Do not deploy
```

## What it does

Given a Deployment YAML, it checks the things that decide whether that manifest is safe to deploy:

| Area | What it checks |
|---|---|
| **Structure** | `kind: Deployment`, `apps/v1`, selector matches pod-template labels |
| **Image** | Pinned tag — not `:latest`, not missing |
| **Resources** | CPU/memory requests *and* limits are set |
| **Security** | `runAsNonRoot`, `allowPrivilegeEscalation: false`, no `privileged`, drop `ALL` capabilities, read-only root FS |
| **Reliability** | `replicas: 2+`, liveness + readiness probes |
| **Identity** | ServiceAccount token not auto-mounted unless needed |

Each finding has a severity (`FAIL` / `WARN` / `PASS`), a location, and a plain-English reason. Score is 100 − 15 per FAIL − 5 per WARN.

- **100:** Deploy
- **< 100, no FAILs:** Deploy with fixes
- **Any FAIL:** Do not deploy

## Why I built this

I do production GKE support work, and in October 2026 I worked for Mercor as an AI Generalist — creating research questions, answers, and evaluation materials to train LLMs. For my Mercor task I recorded a workflow I know well: analysing Kubernetes manifest files and picking the correct one for deployment, explaining my reasoning on screen. It passed quality review.

This repo is the sanitized, runnable version of that rubric — the same checks I was applying by hand, now as a script I can run, test, and defend in an interview.

No cluster access needed. Static evaluation only. No real manifests, credentials, or client data in here — the examples are invented.

## How to run it

```bash
pip install -r requirements.txt

# One file
python evaluator.py examples/good/deployment.yaml

# A whole directory
python evaluator.py examples/

# Machine-readable output for CI / Mercor-style review
python evaluator.py examples/bad/deployment.yaml --json
```

Exit codes: `0` = Deploy, `1` = Deploy with fixes, `2` = Do not deploy / parse error.

## Example output

```
examples/bad/deployment.yaml
  Score:   0/100
  Verdict: Do not deploy
  [FAIL] image: Image 'registry.example.com/api:latest' is unpinned (:latest or no tag). A redeploy can silently pull a different image. Pin to a digest or an explicit version, e.g. app:1.4.2.
  [FAIL] resources: No CPU/memory requests. The scheduler cannot place this reliably...
  [FAIL] security: privileged: true. Almost never needed for an app container - drop it.
  ...
```

See [RUBRIC.md](RUBRIC.md) for the full rubric — what each check is, why it matters, and what a fix looks like.

## Tech decisions & trade-offs

- **Python + PyYAML only.** The point is the evaluation logic, not a framework. Anyone can read `evaluator.py` in one sitting and argue with it.
- **Static checks, no cluster.** I deliberately don't `kubectl apply --dry-run` or call the API. That keeps it runnable in CI and in an interview, with no credentials.
- **Scoring is blunt on purpose.** −15 per FAIL, −5 per WARN. A manifest with one real security fail should not score 85/100 and look "mostly fine." The verdict is what matters, the score is a summary.
- **Selector-match is a FAIL, not a WARN.** If the selector doesn't match the pod labels, the Deployment never owns its Pods. That is silent and total, so it fails the whole manifest.
- **I don't check everything.** No NetworkPolicy, PodDisruptionBudget, HPA, image vulnerability scanning, or admission policy. Those are real, they're just out of scope for a manifest evaluator — see below.

## What I'd improve

1. Support `StatefulSet` / `DaemonSet` / `CronJob`, not just `Deployment`.
2. Add a `--strict` mode where WARNs also block deployment.
3. Check `imagePullPolicy: Always` when the tag is mutable, and flag images without a digest for high-risk workloads.
4. Add PodDisruptionBudget + topology spread checks for multi-replica services.
5. Wire the JSON output into a GitHub Action that comments the verdict on PRs.

## Tests

```bash
pip install -r requirements.txt
python -m pytest tests/ -q
```

CI runs the same checks on every push (`.github/workflows/ci.yml`).

## Files

```
evaluator.py                  # the evaluator
examples/good/deployment.yaml # deployable example — scores 100
examples/bad/deployment.yaml  # :latest, privileged, no resources/probes
examples/bad/selector-mismatch.yaml # selector doesn't match pod labels
RUBRIC.md                     # full rubric with fixes
tests/test_evaluator.py       # good scores 100, bad fails, mismatch fails
```
