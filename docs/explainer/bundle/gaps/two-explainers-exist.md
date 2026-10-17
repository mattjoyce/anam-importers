---
type: gap
title: Two explainers exist
description: docs/explainer.html is a hand-drawn page and docs/explainer/ is a generated one with a bundle behind it, and nothing keeps their claims in step.
timestamp: 2026-10-17T00:00:00Z
looked_at:
  - docs/explainer.html
  - docs/explainer/check.py
  - README.md
---

The generated explainer is checked against the code by `check.py`, which verifies every resource, anchor, symbol and test the bundle names. The hand-drawn page is not. If the two disagree, trust the checked one and fix the other.
