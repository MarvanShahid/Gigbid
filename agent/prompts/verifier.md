---
node: verifier
version: 1.0
---
Decide whether the EVIDENCE supports the CLAIM made by a freelancer about their own past work.
Answer "supported" only if every specific in the claim (skill, number, client type, result) appears in or follows
directly from the evidence; "partial" if the gist is supported but a specific is not; otherwise "unsupported".
CLAIM: {claim}
EVIDENCE: {evidence}
