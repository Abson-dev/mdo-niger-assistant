# Security

## Reporting a problem

Please report a vulnerability, or any surveillance data you find in this repository, privately to the repository owner, not in a public issue. If a report concerns exposed data, it will also be raised with the data owners.

## What the design protects

- **The data.** Only `build_agent_data.py` reads the project's files, on the user's computer. The sources hold aggregate weekly counts per district, with no patient records. The repository holds no data, and a test fails if a data file is tracked.
- **The browser.** Model output is inserted as text and never runs as code. A Content-Security-Policy restricts scripts to the app itself, and no asset is loaded from outside.
- **The web app.** It refuses to start on a reachable host without a password. Sessions are signed and end after 12 hours or a restart, and unlock attempts are limited per address.

## What it does not protect

- **Sub-national counts leave the computer.** They are sent to the Anthropic API when a question needs them. Agree this with the data owners first.
- **Small counts can still point to people.** A few cases of a rare disease in a small district, in one week, can identify someone locally. The tools do not suppress small cells, because surveillance staff need them: do not publish such cells.
- **The browser keeps the conversation.** Chat history, which can quote these values, stays in the browser's local storage: avoid shared computers.
- **There is one shared password,** with no individual accounts or audit log, and the unlock limit is per address, so it needs a trusted proxy to be meaningful behind one.
- **HTTPS is not included.** Put it in front of any server reachable from a network.
- **Answers can be wrong.** Check the sources under each answer before using a figure.
