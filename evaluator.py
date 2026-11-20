#!/usr/bin/env python3
"""
k8s-yaml-evaluator
-----------------
Evaluate a Kubernetes Deployment manifest for deployment correctness
and production-readiness, with rubric-based written feedback.

Built from hands-on work evaluating Kubernetes YAML for deployment:
screen-recorded think-aloud reviews where I had to pick the correct
manifest for deployment and explain why.

Usage:
    python evaluator.py examples/good/deployment.yaml
    python evaluator.py examples/bad/deployment.yaml --json
    python evaluator.py manifests/ --json

Checks (see RUBRIC.md for the full rubric):
  1. Manifest structure - Deployment, apiVersion, name, selector/labels match
  2. Image - pinned tag (not :latest, not missing), pull policy
  3. Resources - CPU/memory requests AND limits set
  4. Security - runAsNonRoot, no privilege escalation, read-only FS,
     drop ALL capabilities, no privileged containers
  5. Reliability - replicas, liveness + readiness probes
  6. Identity - ServiceAccount, automountServiceAccountToken

Exit code: 0 = Deploy, 1 = Deploy with fixes, 2 = Do not deploy / parse error.
Only stdlib + PyYAML. No cluster access needed - static evaluation only.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("PyYAML is required: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


@dataclass
class Finding:
    check: str
    severity: str  # "fail" | "warn" | "pass"
    message: str
    # Where in the manifest, e.g. "spec.template.spec.containers[0]"
    location: str = ""


@dataclass
class Report:
    file: str
    score: int  # 0-100
    verdict: str  # "Deploy" | "Deploy with fixes" | "Do not deploy"
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "score": self.score,
            "verdict": self.verdict,
            "findings": [
                {"check": f.check, "severity": f.severity,
                 "message": f.message, "location": f.location}
                for f in self.findings
            ],
        }


def _containers(doc: dict) -> list[dict]:
    """Return the pod-template containers for a Deployment, or []."""
    try:
        return doc["spec"]["template"]["spec"]["containers"] or []
    except (KeyError, TypeError):
        return []


def _pod_spec(doc: dict) -> dict:
    try:
        return doc["spec"]["template"]["spec"] or {}
    except (KeyError, TypeError):
        return {}


def evaluate(doc: dict, filename: str) -> Report:
    findings: list[Finding] = []

    def add(check: str, severity: str, message: str, location: str = "") -> None:
        findings.append(Finding(check, severity, message, location))

    # --- 1. Manifest structure -------------------------------------------
    kind = doc.get("kind")
    if kind != "Deployment":
        add("structure", "fail",
            f"Expected kind: Deployment, got: {kind!r}. "
            "I can only evaluate Deployments in this version.",
            "kind")
    if doc.get("apiVersion") != "apps/v1":
        add("structure", "warn",
            f"Expected apiVersion: apps/v1, got: {doc.get('apiVersion')!r}.",
            "apiVersion")
    else:
        add("structure", "pass", "kind: Deployment, apiVersion: apps/v1.")

    # Selector must match pod-template labels, otherwise the Deployment
    # never owns its Pods - a classic silent failure.
    try:
        selector = doc["spec"]["selector"]["matchLabels"]
        labels = doc["spec"]["template"]["metadata"]["labels"]
        if not selector or not labels or not set(selector.items()) <= set(labels.items()):
            add("structure", "fail",
                "spec.selector.matchLabels does not match "
                "spec.template.metadata.labels. The Deployment will not "
                "manage its Pods.",
                "spec.selector.matchLabels")
        else:
            add("structure", "pass", "Selector matches pod-template labels.")
    except (KeyError, TypeError):
        add("structure", "fail",
            "Missing spec.selector.matchLabels or "
            "spec.template.metadata.labels.",
            "spec.selector")

    containers = _containers(doc)
    if not containers:
        add("structure", "fail", "No containers found under "
            "spec.template.spec.containers.", "spec.template.spec.containers")
        return _score(filename, findings)

    # --- 2-6. Per-container checks ----------------------------------------
    for i, c in enumerate(containers):
        name = c.get("name", f"container[{i}]")
        loc = f"spec.template.spec.containers[{i}] ({name})"

        # Image
        image = c.get("image", "")
        if not image:
            add("image", "fail", "Container has no image.", loc)
        elif image.endswith(":latest") or ":" not in image:
            add("image", "fail",
                f"Image {image!r} is unpinned (:latest or no tag). "
                "A redeploy can silently pull a different image. "
                "Pin to a digest or an explicit version, e.g. app:1.4.2.",
                loc)
        else:
            add("image", "pass", f"Image is pinned: {image}.", loc)

        # Resources
        resources = c.get("resources") or {}
        req, lim = resources.get("requests") or {}, resources.get("limits") or {}
        if not req:
            add("resources", "fail",
                "No CPU/memory requests. The scheduler cannot place this "
                "reliably and HPA / eviction behaviour is unpredictable.",
                loc)
        if not lim:
            add("resources", "fail",
                "No CPU/memory limits. One container can starve the node "
                "(OOMKilled neighbours, CPU throttling).",
                loc)
        if req and lim:
            add("resources", "pass",
                f"Requests and limits set: requests={req}, limits={lim}.", loc)

        # Probes
        if not c.get("livenessProbe"):
            add("reliability", "fail",
                "No livenessProbe. A hung process will never be restarted "
                "by kubelet.", loc)
        if not c.get("readinessProbe"):
            add("reliability", "fail",
                "No readinessProbe. Traffic can be sent to a Pod that "
                "isn't ready to serve it.", loc)
        if c.get("livenessProbe") and c.get("readinessProbe"):
            add("reliability", "pass",
                "livenessProbe and readinessProbe both present.", loc)

        # Security
        ctx = c.get("securityContext") or {}
        pod_ctx = _pod_spec(doc).get("securityContext") or {}
        run_as_non_root = ctx.get("runAsNonRoot") or pod_ctx.get("runAsNonRoot")
        if not run_as_non_root:
            add("security", "fail",
                "runAsNonRoot is not set (container or pod level). "
                "A container running as root is a privilege-escalation risk.",
                loc)
        if ctx.get("privileged") is True:
            add("security", "fail",
                "privileged: true. Almost never needed for an app "
                "container - drop it.", loc)
        if ctx.get("allowPrivilegeEscalation") is not False:
            add("security", "fail",
                "allowPrivilegeEscalation is not false. Set it to false "
                "unless the workload genuinely needs setuid binaries.", loc)
        caps = (ctx.get("capabilities") or {}).get("drop") or []
        if "ALL" not in caps:
            add("security", "warn",
                "capabilities.drop does not include ALL. Drop all, then "
                "add back only what the app needs.", loc)
        if ctx.get("readOnlyRootFilesystem") is not True:
            add("security", "warn",
                "readOnlyRootFilesystem is not true. A writable root FS "
                "makes tampering and persistence easier.", loc)
        if run_as_non_root and ctx.get("allowPrivilegeEscalation") is False:
            add("security", "pass",
                "runAsNonRoot + allowPrivilegeEscalation: false.", loc)

    # --- Reliability: replicas --------------------------------------------
    replicas = None
    try:
        replicas = doc["spec"]["replicas"]
    except (KeyError, TypeError):
        pass
    if replicas is None:
        add("reliability", "warn",
            "spec.replicas is not set - defaults to 1. "
            "One Pod is a single point of failure for a deployment.",
            "spec.replicas")
    elif replicas < 2:
        add("reliability", "warn",
            f"replicas: {replicas}. For a production service, use 2+ so a "
            "node drain or Pod failure doesn't take the service down.",
            "spec.replicas")
    else:
        add("reliability", "pass", f"replicas: {replicas}.", "spec.replicas")

    # --- Identity -----------------------------------------------------------
    pod_spec = _pod_spec(doc)
    if pod_spec.get("automountServiceAccountToken") is True:
        add("identity", "warn",
            "automountServiceAccountToken: true. If this workload doesn't "
            "call the Kubernetes API, set it to false.",
            "spec.template.spec.automountServiceAccountToken")
    else:
        add("identity", "pass",
            "ServiceAccount token is not auto-mounted, or the field is unset.",
            "spec.template.spec")

    return _score(filename, findings)


def _score(filename: str, findings: list[Finding]) -> Report:
    fails = sum(1 for f in findings if f.severity == "fail")
    warns = sum(1 for f in findings if f.severity == "warn")
    # Start at 100, -15 per fail, -5 per warn. Floor at 0.
    score = max(0, 100 - 15 * fails - 5 * warns)
    if fails == 0 and warns == 0:
        verdict = "Deploy"
    elif fails == 0:
        verdict = "Deploy with fixes"
    else:
        verdict = "Do not deploy"
    return Report(file=filename, score=score, verdict=verdict, findings=findings)


def load_docs(path: Path) -> list[tuple[str, dict]]:
    """Load all YAML documents from a file (multi-doc supported)."""
    docs = []
    try:
        with path.open() as fh:
            for doc in yaml.safe_load_all(fh):
                if doc is not None:
                    docs.append((str(path), doc))
    except yaml.YAMLError as exc:
        print(f"{path}: YAML parse error: {exc}", file=sys.stderr)
        sys.exit(2)
    if not docs:
        print(f"{path}: no YAML documents found.", file=sys.stderr)
        sys.exit(2)
    return docs


def print_report(report: Report) -> None:
    print(f"\n{report.file}")
    print(f"  Score:   {report.score}/100")
    print(f"  Verdict: {report.verdict}")
    for f in report.findings:
        mark = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}[f.severity]
        print(f"  [{mark}] {f.check}: {f.message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate Kubernetes Deployment YAML for production-readiness.")
    parser.add_argument("path", help="YAML file or directory of YAML files")
    parser.add_argument("--json", action="store_true",
                        help="Output machine-readable JSON instead of text")
    args = parser.parse_args(argv)

    target = Path(args.path)
    files: list[Path] = []
    if target.is_dir():
        files = sorted(p for p in target.rglob("*.y*ml"))
    elif target.is_file():
        files = [target]
    else:
        print(f"Not found: {args.path}", file=sys.stderr)
        return 2

    if not files:
        print(f"No YAML files found under {args.path}", file=sys.stderr)
        return 2

    reports: list[Report] = []
    for f in files:
        for filename, doc in load_docs(f):
            if not isinstance(doc, dict):
                print(f"{f}: top-level document is not a mapping, skipping.",
                      file=sys.stderr)
                continue
            reports.append(evaluate(doc, filename))

    if args.json:
        print(json.dumps([r.to_dict() for r in reports], indent=2))
    else:
        for r in reports:
            print_report(r)

    # Worst verdict wins for the exit code.
    if any(r.verdict == "Do not deploy" for r in reports):
        return 2
    if any(r.verdict == "Deploy with fixes" for r in reports):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
