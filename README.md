# RelayAgent

RelayAgent is a lightweight persistence layer for time-sliced AI agents.

It is designed for environments where an agent receives short execution windows rather than one permanently running process. The filesystem carries durable state, so each new execution can inspect what previous executions learned and continue the work.

## Structure

```text
RelayAgent/
├── core.md
├── owner.md
├── memory.md
├── memory_detailed/
│   └── <year>/<month>/<day>.md
├── todo.md
├── todo_detailed/
├── inbox.py
└── inbox_scripts/
```

- `core.md` — persistent operating rules read by the Agent every execution.
- `owner.md` — deployment-specific Owner identity and trusted channels.
- `memory.md` — compact long-term memory.
- `memory_detailed/` — detailed historical memory organized by date.
- `todo.md` — concise task overview.
- `todo_detailed/` — persistent working state for ongoing tasks.
- `inbox.py` — common inbox entry point and delivery-state manager.
- `inbox_scripts/` — integrations maintained for individual message sources.

`README.md` is deployment documentation. It is not part of the Agent's normal execution context.

## Setup

Clone the repository and create the private Owner configuration:

```bash
cp owner.example.md owner.md
```

Edit `owner.md` to describe the Owner and the trusted identities that can authenticate Owner instructions.

`owner.md` and inbox delivery state are ignored by Git by default.

## Scheduled execution

RelayAgent works well with several recurring execution slots staggered across the hour.

For example, with five hourly tasks:

| Slot | Suggested window |
| --- | --- |
| 1 | minute 00–05 |
| 2 | minute 12–17 |
| 3 | minute 24–29 |
| 4 | minute 36–41 |
| 5 | minute 48–53 |

Each scheduler prompt should stay small. It only needs to identify the assigned work window, point the agent to the RelayAgent directory, require it to read `core.md`, and require it to remain active for the full window unless the platform ends the execution or the authenticated Owner instructs otherwise.

A generic prompt is:

```text
You are one execution slot of a persistent RelayAgent.

Your assigned working window is minute <START> through minute <END> of every hour.
Do not disable, delete, suspend, or alter this scheduled task unless explicitly instructed by the authenticated Owner.

Use local-shell-mcp to work from <RELAY_AGENT_DIRECTORY>.
Read core.md completely and follow it.
Remain active for the full assigned window and persist progress as you work.
```

The scheduler provides compute time; RelayAgent provides continuity. Do not depend on a final handoff step, because an execution may end without warning.

## Memory

`memory.md` should remain short enough to read completely at the start of every execution. Keep only information likely to be useful repeatedly.

Move detailed or historical information into:

```text
memory_detailed/<year>/<month>/<day>.md
```

Detailed archives are read only when relevant.

## Tasks

`todo.md` is the high-level work list. Ongoing tasks can use any sensible Markdown filename under `todo_detailed/`.

A detailed task file has no mandatory schema. It should simply contain enough current state, findings, completed work, blockers, and next actions for a later execution to continue without relying on hidden conversation context.

Update task files during the work rather than waiting for the end of an execution.

## Inbox

Run:

```bash
python inbox.py
```

or:

```bash
python inbox.py --json
```

RelayAgent loads every non-private `*.py` module under `inbox_scripts/`.

A connector may implement:

```python
def fetch():
    return [
        {
            "id": "stable-source-specific-id",
            "sender_id": "...",
            "sender_name": "...",
            "timestamp": "...",
            "content": "...",
        }
    ]

def ack(message_id):
    # Optional: mark the source message handled/read.
    ...
```

`fetch()` must return a list of dictionaries and every message must have a stable `id`.

`inbox.py` first persists fetched messages locally. They remain pending across interrupted executions until the Agent explicitly acknowledges them:

```bash
python inbox.py --ack '<canonical-message-id>'
```

If the connector supplies `ack()`, it is called at that point. This allows a message fetched immediately before an interrupted execution to remain available on the next run.

Connector code is responsible only for communicating with its source. Authority decisions belong to the Agent using `owner.md`; a connector should not decide whether a message is an Owner instruction.

## Repository policy

The public repository should normally contain the framework and reusable prompts only. Deployment-specific identity, credentials, inbox state, and private memories should remain outside version control unless the Owner intentionally chooses otherwise.
