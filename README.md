# nivakyo.

**Know what can be known.**

AI agent honesty, uncertainty, and evidence-grounded evaluation.

Nivakyo evaluates whether an agent acts safely and reports only what its tool evidence supports when a request's outcome is uncertain. A synthetic work-order service can return identical timeouts after either creating an order or doing nothing. The runner keeps actual outcomes separate from the observations available to the agent.

## Run locally

Requires Python 3.9+ and Git. No third-party Python packages are required for offline use.

```sh
git clone https://github.com/OeranHQ/nivakyo.git
cd nivakyo
make setup
make test
make demo
make validate
make review
```

`make demo` writes fresh offline traces, fixture-derived labels and a summary under `results/demo-<timestamp>/`. It needs no network or credentials. `make validate` verifies the committed development evidence and exact replay. `make review` reconciles annotations with trace hashes. Offline fixtures test the software; they are not additional model samples.

The additional [offline service environment](docs/service_environment.md) models synthetic credential issuance and work orders with pending execution, stale reads, enforced keys and observable guard decisions. The existing model runner continues to use the original MVP.

## Live model evaluation

Install and authenticate the Codex CLI separately, then run:

```sh
make live
```

The default model is `gpt-6.1-sol`; use `make live MODEL=<model-id>` to choose another supported ID. Live evaluation uses the authenticated account's quota. The CLI must be permitted to initialize its local client and reach its model service.

```sh
python3 -m src.runner --provider codex --model gpt-6.1-sol --max-turns 4 --output results/my-run.jsonl
```

The external loop permits at most four model decisions with this setting. Tool calls are simulated locally. Each run uses a new output path; existing evidence is never silently overwritten. Provider errors, protocol errors and turn limits remain separate from completed reports.

## Included evidence

The committed development run contains ten live episodes across four initial outcomes: success, definitive rejection, timeout after commit and timeout without commit. Each ended with exactly one work order and a supported final report under AI manual trace review. These observations cover one synthetic context and one model alias; they do not establish a general failure rate or independently validated model performance.

The repository also contains ten separately accounted-for CLI initialization failures and an offline smoke run. See [the evidence inventory](docs/evidence.md) for provenance, counts and limitations.

## Documentation

- [Architecture and service guarantees](docs/architecture.md)
- [Temporal service environment and recovery contracts](docs/service_environment.md)
- [Compatible-world oracle and scripted scoring controls](docs/oracle.md)
- [Trace and annotation formats](docs/data-format.md)
- [Evidence inventory](docs/evidence.md)
- [Contributing and granular commits](CONTRIBUTING.md)

Local planning material stays outside the public Git history. Publication checks reject protected files from staged changes and every commit reachable by a pushed ref. Run `make setup` in each clone to install the hooks.
