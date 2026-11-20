# Rubric — how a manifest is judged

Score: 100 − 15 per FAIL − 5 per WARN.

Verdict:
- **Deploy** — no FAILs, no WARNs
- **Deploy with fixes** — no FAILs, some WARNs
- **Do not deploy** — any FAIL

## 1. Structure

| Check | Fail if | Why it matters | Fix |
|---|---|---|---|
| kind / apiVersion | kind is not `Deployment`, apiVersion is not `apps/v1` | This evaluator is scoped to Deployments; a wrong kind means the rest of the checks don't apply | Set `apiVersion: apps/v1`, `kind: Deployment` |
| Selector matches labels | `spec.selector.matchLabels` is not a subset of `spec.template.metadata.labels` | The Deployment never owns its Pods. `kubectl rollout status` hangs, scaling does nothing, and nothing errors loudly | Make selector and template labels identical |

## 2. Image

| Check | Fail if | Why it matters | Fix |
|---|---|---|---|
| Pinned tag | Image ends in `:latest` or has no tag | A redeploy can silently pull a different image than the one you tested | Pin it: `api:1.4.2`, or better, a digest `api@sha256:…` |

## 3. Resources

| Check | Fail if | Why it matters | Fix |
|---|---|---|---|
| Requests set | No CPU/memory `requests` | Scheduler placement is guesswork; HPA and eviction behave unpredictably | Set requests to what the app actually uses at steady state |
| Limits set | No CPU/memory `limits` | One container can starve the node — OOMKilled neighbours, CPU throttling | Set limits above requests, with headroom for spikes |

## 4. Security

| Check | Fail if | Why it matters | Fix |
|---|---|---|---|
| runAsNonRoot | Not set at container or pod level | A container running as root is a privilege-escalation risk if it escapes | `runAsNonRoot: true` (pod or container `securityContext`) |
| allowPrivilegeEscalation | Not `false` | Lets a process gain more privileges than its parent, e.g. via setuid binaries | `allowPrivilegeEscalation: false` |
| privileged | `privileged: true` | Full host access. Almost never needed for an app container | Remove it; use specific capabilities instead |
| Drop ALL capabilities | `capabilities.drop` doesn't include `ALL` | Default Linux capabilities are broader than most apps need | Drop `ALL`, add back only what you need |
| Read-only root FS | Not `true` (WARN, not FAIL) | A writable root FS makes tampering and persistence easier | `readOnlyRootFilesystem: true`, with `emptyDir` volumes for temp/cache |

## 5. Reliability

| Check | Fail if | Why it matters | Fix |
|---|---|---|---|
| livenessProbe | Missing | A hung process is never restarted by kubelet | Add an `httpGet` / `exec` liveness probe |
| readinessProbe | Missing | Traffic is sent to a Pod that isn't ready to serve it | Add a readiness probe on your ready endpoint, not just `/` |
| Replicas | Not set, or `< 2` (WARN) | One Pod is a single point of failure during a node drain or crash | `replicas: 2` minimum for a production service; 3 if you want quorum-style safety |

## 6. Identity

| Check | Fail if | Why it matters | Fix |
|---|---|---|---|
| automountServiceAccountToken | `true` (WARN) | The Pod gets a token that can call the Kubernetes API, even if it never needs to | `automountServiceAccountToken: false` unless the workload calls the API |

## What this rubric deliberately does NOT cover

NetworkPolicy, PodDisruptionBudget, HPA, Pod Security Standards enforcement, image vulnerability scanning, and admission control. Those are real production concerns, but they live outside a single Deployment manifest — in cluster policy, CI scanning, and platform config. A manifest can score 100 here and still be wrong for your cluster. This is a manifest check, not a cluster audit.
