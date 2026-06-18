# Go Instructions

Paste the relevant lines into a project `CLAUDE.md`. Keep only what's true for the repo.

## Style

- `gofmt`/`goimports` own formatting — run them; never hand-format. Follow Effective Go
  and the project's existing patterns.
- Short, clear names; exported identifiers get doc comments starting with the name.
- Accept interfaces, return concrete types. Keep interfaces small and defined by the
  consumer.

## Errors

- Errors are values: check every one. Wrap with context using `fmt.Errorf("...: %w", err)`
  so the chain is inspectable with `errors.Is`/`errors.As`.
- Don't panic for ordinary errors — return them. Reserve panic for truly unrecoverable
  programmer errors.
- `defer` for cleanup (close, unlock) right after acquiring the resource.

## Concurrency

- Don't start a goroutine without knowing how it stops. Propagate `context.Context` for
  cancellation and deadlines.
- Protect shared state with a mutex or channel — pick one ownership model and keep it.
- Run tests with `-race`. A data race is a bug even if it "works."

## Idioms

- Zero values are useful — design types so the zero value is valid where possible.
- Prefer the standard library; add dependencies sparingly.
- Table-driven tests with subtests (`t.Run`). Keep tests deterministic.

## Before done

- `gofmt`, `go vet`, the linter (golangci-lint), and `go test -race ./...` all clean.
