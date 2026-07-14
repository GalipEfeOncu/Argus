# Contract Checklist

Use this checklist when changing a REST endpoint, WebSocket command, or WebSocket event.

1. Update the authoritative Pydantic schema and validation.
2. Update schema/type generation inputs and generated TypeScript types.
3. Update the frontend event reducer and typed simulator fixture.
4. Cover ordering, replay/reconnect, malformed input, idempotency, and permission failures.
5. Update `docs/API.md` and any affected UX/security documentation.
6. Run the backend and frontend verification scopes, then inspect the diff.
