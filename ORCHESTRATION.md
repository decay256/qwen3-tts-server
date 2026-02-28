# Orchestration — Qwen3 TTS Server

> This document is maintained by the Orchestrator agent.
> Rendered to PDF via: `bash skills/swarm-dev/scripts/render-docs.sh`
> Last updated: (auto-update on each orchestrator run)

## Agent Pipeline

```mermaid
flowchart TD
    PM[Product Manager\nwrite requirements] --> ARCH[Architect\ndesign + contracts]
    ARCH --> BE[Backend Engineer]
    ARCH --> FE[Frontend Engineer]
    ARCH --> DEVOPS[DevOps]
    BE --> CR[Code Reviewer\nno context]
    FE --> CR
    CR -->|approved| QA[QA Engineer\nno context]
    CR -->|changes requested| BE
    QA -->|pass| SEC[Security Reviewer\nno context]
    QA -->|fail| BE
    SEC -->|approved| MERGE[Merge to develop]
    SEC -->|issues| BE
    MERGE --> TW[Technical Writer\nupdate docs]
    TW --> DONE[Done ✓]
```

## Ticket Lifecycle

```mermaid
stateDiagram-v2
    [*] --> backlog : Orchestrator creates issue
    backlog --> in_progress : Agent picks up
    in_progress --> review : PR opened
    review --> in_progress : Changes requested
    review --> done : Approved + merged
    in_progress --> blocked : Dependency missing
    blocked --> backlog : Blocker resolved
    done --> [*]
```

## Maturity Gate Flow

```mermaid
flowchart LR
    PoC -->|de-risks core assumption| Prototype
    Prototype -->|functional component| MVP
    MVP -->|owner can use it| Product

    style PoC fill:#FFA500
    style Prototype fill:#FFD700
    style MVP fill:#90EE90
    style Product fill:#008000,color:#fff
```

## Component Status

| Component | Maturity | Owner | Status |
|-----------|---------|-------|--------|
| (none yet) | — | — | — |

## Active Decisions

| # | Decision | Made by | Date |
|---|---------|---------|------|
| — | — | — | — |

## Pipeline Rules

1. No implementation without a contract (`contracts/<component>.yaml` must exist)
2. Critics (reviewer/qa/security) receive only the artifact — no backstory
3. Separation of concerns: cross-component imports are a blocking review finding
4. Every agent action is logged to `agent.log`
5. Maturity gates must be checked before closing any issue as done
