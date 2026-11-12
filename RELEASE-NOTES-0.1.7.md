# PyLoxone-Audio 0.1.7

Library **0.1.7**, reference adapter **0.1.7**, exact `PyLoxone-Audio==0.1.7`, frontend **r14**, based on PyLoxone **0.10.3**. Update both integration files and frontend; a library install alone does not replace them.

- Reuse authenticated command sessions for warm controls and sequential Browse requests.
- Improve nested Local Library browsing and native Group compatibility with Core 2026.11.1.
- Keep standard player volume room-only; use the custom manager's explicit **Group volume** to adjust the group while retaining room balance, subject to volume limits.
- Combine rapid custom-manager −/+ taps after a brief 300 ms pause.
- Provide supported follower mode controls and clearer volume errors.

[Install, upgrade and roll back](https://github.com/davehocking/PyLoxone-Audio/blob/main/preview-build/README.md) · [User guide](USER-GUIDE.md) · [Current limits](KNOWN-ISSUES.md)
