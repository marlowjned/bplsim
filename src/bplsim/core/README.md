# core: language and infrastructure

Used by everything else; depends on nothing else in bplsim except `units`.

| File | Role |
|---|---|
| `errors.py` | error types (`ConfigError`, `ResolveError`, `BackendError`, ...). Every user-facing error carries a file:line location when one is known; `ErrorList` collects them so `bplsim check` reports all at once |
| `expr.py` | the expression language of YAML values (rule R4): `${ ... }` expressions, evaluated lazily with memoisation and cycle detection (K5); `SlotPresent` guards for optional parts |
| `yamlio.py` | YAML loading that keeps the file and line of every value, so errors can point at them |
| `hashing.py` | canonical JSON and content hashes for cases and runs (plan §10), with value quantization so float noise does not change a hash |
