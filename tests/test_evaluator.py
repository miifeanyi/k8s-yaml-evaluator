"""Tests for evaluator.py — good deploys, bad does not."""

from pathlib import Path

import yaml

from evaluator import evaluate

ROOT = Path(__file__).resolve().parent.parent


def _load(rel: str) -> dict:
    with (ROOT / rel).open() as fh:
        return yaml.safe_load(fh)


def test_good_manifest_scores_100_and_deploys():
    doc = _load("examples/good/deployment.yaml")
    report = evaluate(doc, "good")
    assert report.score == 100
    assert report.verdict == "Deploy"
    assert all(f.severity == "pass" for f in report.findings)


def test_bad_manifest_does_not_deploy():
    doc = _load("examples/bad/deployment.yaml")
    report = evaluate(doc, "bad")
    assert report.verdict == "Do not deploy"
    assert report.score < 50
    failed = {f.check for f in report.findings if f.severity == "fail"}
    # The bad example must fail on the big four.
    assert {"image", "resources", "security", "reliability"} <= failed


def test_selector_mismatch_is_a_fail():
    doc = _load("examples/bad/selector-mismatch.yaml")
    report = evaluate(doc, "mismatch")
    assert report.verdict == "Do not deploy"
    assert any(
        f.check == "structure" and f.severity == "fail"
        for f in report.findings
    )


def test_latest_tag_fails_but_pinned_tag_passes():
    good = _load("examples/good/deployment.yaml")
    assert evaluate(good, "good").verdict == "Deploy"

    bad = _load("examples/good/deployment.yaml")
    bad["spec"]["template"]["spec"]["containers"][0]["image"] = "api:latest"
    report = evaluate(bad, "latest")
    assert report.verdict == "Do not deploy"
    assert any(
        f.check == "image" and f.severity == "fail"
        for f in report.findings
    )
