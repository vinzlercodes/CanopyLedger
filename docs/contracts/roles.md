# Role and Privilege Matrix v1

| Role | Mutable facility data | Immutable outputs | Approve | Query analytics | Render reports |
|---|---|---|---|---|---|
| Analyst | Read/write permitted scope | Read | No | Yes | Draft only |
| Credit approver | Read | Read | Yes, subject to separation | Yes | Current official |
| Auditor | Read | Read | No | Yes | Historical audit |
| Pipeline worker | No | Insert via fenced publication | No | No | No |
| Report worker | Read approved package only | Insert report artifacts | No | No | Yes |
| Analytics reader DB role | Curated views only | Curated views only | No | Read only | No |

No self-approval. Override requires two distinct policy-qualified approvers. Runtime DB roles own no objects.

