# Measurement provenance

The recovered original drill log confirms:
- In-scope DynamoDB access allowed and out-of-scope access denied.
- Three failed generation attempts.
- CloudWatch notification after 200.1 seconds.
- Replay completed in 4.7 seconds in this particular synthetic drill.

The resume's 172 ms submission, 18.5 s generation, and 26 s replay numbers are historical claims supplied in the resume. No matching raw log for those exact numbers was present in the recovered files. The included log does not establish those figures. Use scripts/benchmark.py and scripts/replay_dlq.py to record new observations with the environment and model used.

This repository contains deployable source and mocked AWS tests. It does not imply that the infrastructure is currently deployed. The original drill used special fault/recovery modes; it did not call a real model during synthetic recovery.
