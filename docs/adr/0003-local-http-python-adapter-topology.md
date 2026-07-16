# Local HTTP gateway with Python application-service adapters

Status: proposed

`my-discord-bot` will call one long-lived `chat-assistant` gateway over local
HTTP/JSON. For the MVP, the gateway will call each enabled specialist through
that specialist's reviewed, versioned Python application-service contract in
the gateway process. The gateway adapter boundary must also support replacing
an in-process application service with an isolated local-service client later,
without changing the bot-to-gateway protocol. This gives the Discord consumer
one stable, portable service boundary while avoiding three additional services
before their isolation cost is justified.

This decision applies the accepted five-repository ownership boundary in
[`docs/ecosystem-architecture.md`](../ecosystem-architecture.md). It does not
approve a wire schema, identity or privacy policy, a specialist contract,
generic advisor behavior, health enablement, deployment secrets, or runtime
implementation. Those decisions remain with their owning issues.

## Context

The target dependency direction is:

```text
Discord user
  -> my-discord-bot
  -> chat-assistant
  -> lang-assistant, game-assistant, or health-assistant
  -> local Ollama
```

The current `bot.py` is a legacy Discord/Ollama runtime and is not evidence for
the target transport. The topology must instead preserve these constraints:

- `my-discord-bot` is the only Discord runtime and Discord-token owner.
- `chat-assistant` exposes one transport-neutral gateway to the bot.
- Specialists remain independently usable and own their domain behavior,
  prompts, model calls, validation, persistence, and private data.
- Repository boundaries use reviewed public contracts, never private imports,
  storage access, human-oriented CLI parsing, or adjacent checkout paths.
- The same topology works on Windows and Linux and does not need a cloud
  service, public ingress, CUDA, a second Discord token, or OS-specific IPC.
- Health is an optional capability that remains disabled and denied until all
  of its separate safety, privacy, evidence, contract, QA, and release gates
  pass. A health failure never falls back to generic chat.

## Decision

### Bot-to-gateway transport

`chat-assistant` is one long-lived local service. `my-discord-bot` is an HTTP
client configured with one gateway origin and sends and receives structured
JSON. The bot never calls a specialist or Ollama directly and never parses a
gateway CLI.

The exact resource paths, media types, envelopes, operation names, error
fields, progress representation, and compatibility rules belong to issues #3
and #13. This ADR fixes the HTTP/JSON boundary and its topology, not those
payload details. Raw Discord objects and Discord presentation fields do not
cross the boundary.

HTTP over TCP is selected instead of Unix-domain sockets, Windows named pipes,
or another platform-specific IPC mechanism. It has the same client/server
shape on supported Windows and Linux hosts, works with ordinary test doubles,
and carries forward to container deployment.

### Gateway-to-specialist boundary

For the MVP, each enabled specialist publishes a versioned,
Discord-independent Python application service. The gateway composition root
constructs an adapter against an installed, compatible public service; it does
not import private modules, discover a neighbouring checkout, parse a human
CLI, or read specialist storage.

The public application services are owned by:

- `lang-assistant` issue #62 for language operations;
- `game-assistant` issue #46 for game operations; and
- `health-assistant` issue #21 for health operations, only after its upstream
  safety, evidence, and privacy gates are approved.

The gateway owns its adapter interfaces and orchestration. A specialist owns
the implementation behind its public service. The boundary must preserve
structured domain results and stable domain errors without copying domain
rules into the gateway.

An adapter may be absent or incompatible. In that case its capability is
disabled or unavailable through a safe gateway result; startup of unrelated
capabilities is not blocked. Health is not loaded or advertised as invocable
merely because a package is installed. Policy enablement and caller
authorization are independent gates.

In-process application services share the gateway interpreter, dependency
environment, memory space, and process fate. That coupling is an explicit MVP
trade-off, not a new ownership boundary. Each gateway adapter must hide whether
its implementation is an in-process service or a client for a later isolated
service.

### Native and container topology

The default native deployment is one host with two independently supervised
long-lived processes:

```text
my-discord-bot process
        |
        | HTTP/JSON on a configured loopback origin
        v
chat-assistant process
        |
        | versioned Python public application services
        v
enabled specialist packages
```

The gateway binds only to a loopback interface in native mode. A wildcard,
LAN, VPN, or public bind is not authorized by this ADR. The bot uses a
configured origin; no personal path, checkout location, port, or executable is
hard-coded into a public contract.

In container mode, the bot and gateway are separate containers on one private,
host-local container network. The gateway may bind its container interface so
the bot container can reach it, but the gateway port is not published to the
host or an external network by default. Service discovery uses deployment
configuration, not a value embedded in protocol payloads.

Plain local HTTP is allowed only on the same host through loopback or the
private container network described above. Routing the boundary across hosts,
an untrusted shared network, or public ingress is outside this decision and
requires a separate TLS, authentication, threat-model, and deployment review.

### Process ownership and lifecycle

An external supervisor or an explicit developer launcher owns process startup,
restart, and final shutdown. Deployment issue #20 owns the concrete service
manager, container configuration, health checks, restart limits, and recovery
runbook.

The bot and gateway do not spawn, kill, or restart each other. The bot may
start before the gateway and must map connection failure or non-readiness to a
safe unavailable result. The gateway does not require Discord to start. In the
MVP, Python specialist application services are constructed within the gateway
process rather than supervised as separate processes.

Gateway startup performs bounded configuration and compatibility validation
before reporting ready. A capability whose optional dependency is absent,
disabled, unhealthy, or incompatible does not become ready. Liveness alone is
not proof of readiness, authorization, or health policy approval.

On graceful shutdown the gateway stops accepting new work, signals
cancellation to queued and running work, drains for a configured bounded
period, cleans gateway-owned temporary state, and exits. A restart does not
silently replay incomplete requests. A client may retry only when the protocol
marks the operation retry-safe and the original deadline and authorization are
still valid.

If a specialist later moves to an isolated local service, the external
supervisor owns that service too. The gateway observes its readiness and
restart effects but does not become a general-purpose process manager.

### Request flow

1. `my-discord-bot` authenticates the Discord interaction, applies Discord
   authorization, cooldown, acknowledgement, attachment, and presentation
   policy, and builds a minimized transport-neutral request.
2. The bot authenticates to the configured gateway origin and sends a
   versioned JSON request with caller context, a deadline, and no Discord token
   or raw Discord object.
3. The gateway authenticates the client, validates caller context and the
   request envelope, checks the deadline and compatible version, applies
   back-pressure, and selects one enabled capability adapter.
4. The adapter invokes only the specialist's reviewed public application
   service. The specialist performs domain authorization and validation owned
   by its contract, domain work, persistence, and model calls.
5. The adapter preserves the structured specialist result. The gateway maps
   orchestration and dependency failures to stable transport-safe results.
6. The bot maps the gateway result to Discord presentation. A delivery failure
   does not cause implicit replay or specialist state mutation.

The gateway is the only bot-facing endpoint. Adding, removing, or isolating a
specialist never gives the bot a second assistant endpoint.

### Deadlines and cancellation

The client supplies an end-to-end deadline in the versioned protocol. The
gateway applies the earlier of that deadline and its own configured maximum and
passes the remaining budget through the selected public application-service
contract. Timeout configuration does not replace the request deadline.

Client disconnect and explicit protocol cancellation both signal gateway
cancellation; a socket closing is not the only cancellation contract. The
gateway propagates one cooperative cancellation signal to work that has begun,
stops waiting for a late result, rejects that result as a successful response,
and runs gateway-owned cleanup. The specialist owns cleanup for domain work it
accepted.

Python cannot safely force-kill arbitrary work in the gateway process. A public
application service that cannot accept a deadline, cooperate with cancellation,
or return within a bounded period is therefore not production-compatible with
the in-process MVP topology. Issue #8 owns the concrete job state machine,
worker bounds, cancellation acknowledgements, and cleanup tests.

This limitation is a trigger for moving an adapter behind an isolated service:
process termination can then contain a non-cooperative dependency without
changing the bot boundary. Isolation is not a reason to weaken deadlines or
retain cancelled results.

### Version negotiation and compatibility

Both integration seams negotiate reviewed contract versions:

- the bot and gateway use the transport-neutral capability protocol owned by
  issue #3; and
- each gateway adapter declares the public application-service version range
  it supports against the version published by its specialist.

The gateway rejects a request or disables a capability before domain work when
there is no compatible version intersection. It does not guess, coerce a
payload, parse prose, or silently route to another capability. Discovery and
readiness expose only safe version-range and compatibility metadata; discovery
does not grant authorization.

Issue #3 owns exact version fields, unknown-field behavior, additive and
breaking change rules, deprecation, and fixtures. The producer contract issues
own their corresponding Python compatibility policy. Cross-repository tests
must cover both ends of every enabled seam.

### Local authentication and trust boundary

Loopback and a private container network reduce exposure but are not identity
or authorization. Except for a minimal content-free liveness probe, every
gateway request must authenticate the calling deployment of `my-discord-bot`
with a high-entropy, deployment-scoped credential carried in standard HTTP
authentication metadata outside the JSON application envelope.

The credential authenticates the bot process, not the Discord user and not a
capability grant. The gateway still validates the minimized caller context and
per-capability authorization defined by issue #4. Missing, malformed, expired,
or invalid client authentication or caller context fails closed before adapter
invocation.

Credentials must never appear in URLs, JSON payloads, logs, readiness output,
fixtures, source control, or public errors. Exact credential representation,
provisioning, rotation, comparison, caller mapping, audit policy, and
authenticated readiness/discovery rules belong to issues #4, #6, #13, and #20.
This ADR does not authorize trusting every local process, container, or user.

## Considered options

### Selected: local HTTP gateway plus in-process public application services

This option gives the bot one portable, testable failure boundary and one
stable origin. It keeps specialist domain APIs independent of Discord and
avoids operating a service per specialist during the MVP. The adapter seam
preserves a staged move to stronger isolation.

### Import the gateway into `my-discord-bot`

Rejected. It would combine Discord, gateway, provider, and specialist
dependencies in one process, weaken restart and failure boundaries, make the
bot responsible for gateway composition, and make later independent deployment
more disruptive.

### Invoke specialist machine CLIs as subprocesses

Rejected as the primary MVP integration. A dedicated machine CLI could isolate
dependencies, but it introduces executable discovery, environment and quoting
differences across Windows and Linux, per-request process overhead, stdout and
exit-code framing, weak readiness, and difficult cooperative cancellation.
Human-oriented CLI output is never an acceptable contract. A later isolated
adapter must use a reviewed machine service or contract, not revive prose
parsing.

### Run the gateway and every specialist as HTTP services immediately

Rejected for the MVP, retained as the isolation migration target. It provides
stronger process containment, independent dependency environments, native
health checks, and enforceable termination, but requires operating and securing
up to five long-lived services, coordinating ports and versions, and expanding
startup, restart, secret, and observability work before the contracts exist.

### Use Unix-domain sockets or Windows named pipes

Rejected. Each is useful on its native platform, but selecting both would add
two transports and platform-specific test/deployment behavior. TCP loopback is
portable and already matches the container migration shape.

### Extract a shared cross-repository package before contracts stabilize

Rejected. No proven common contract currently justifies coupling repository
release cycles, ownership, or dependency resolution through a shared package.
Each repository should implement only its side of the reviewed, versioned
public contract and may temporarily duplicate small protocol fixtures where
that keeps ownership explicit. A shared package can be reconsidered only after
real common behavior is demonstrated and separately reviewed; foundation work
must not assume that shared-package extraction is required by, or forms part
of, this ADR's deployment topology.

### Direct storage, private imports, public/cloud transport, or another bot

Rejected by the accepted architecture. Direct database/profile access, private
module imports, human CLI parsing, public Internet exposure, a required cloud
service, arbitrary caller-selected commands, and a second Discord token all
bypass ownership, security, or portability boundaries.

## Consequences

Benefits:

- The bot has one stable gateway origin and no specialist knowledge.
- Native and container deployments use the same HTTP client/server model on
  Windows and Linux.
- Unit and contract tests can replace the HTTP client and every specialist
  adapter without Discord, Ollama, network access, or other checkouts.
- Specialists keep public application services, standalone entry points,
  private storage, and independent domain ownership.
- Individual specialist adapters can later gain process isolation without a
  bot protocol migration.

Costs and risks:

- In-process specialists can create Python dependency conflicts, consume shared
  memory, block the interpreter, or crash the gateway. Version pins, bounded
  work, compatibility checks, and the isolation migration seam mitigate but do
  not eliminate this risk.
- Cooperative cancellation cannot forcibly stop arbitrary Python work. A
  non-cooperative contract is incompatible until fixed or isolated.
- Local HTTP introduces a listening socket and a deployment credential even on
  one laptop. Loopback/private-network binding, fail-closed authentication, and
  content-free diagnostics are mandatory.
- The MVP has logical adapter isolation rather than OS process isolation. Load,
  failure-injection, privacy, and release evidence must validate that trade-off
  before production release.
- Installing specialist packages into the gateway is a supply-chain and
  compatibility decision. Reviewed public releases and the repository's human
  dependency-approval gate apply.

## Migration strategy

1. Issue #5 replaces the legacy Discord runtime with the gateway package and a
   long-lived service entry point; it does not add domain behavior.
2. Issues #3, #4, #6, #7, #8, #9, and #13 define the protocol, trust policy,
   configuration, orchestration, health, and bot-facing API needed by the
   selected HTTP boundary.
3. Producer issues `lang-assistant#62`, `game-assistant#46`, and, when approved,
   `health-assistant#21` publish versioned Python public application services.
   Gateway issues #11, #12, and #30 implement adapters against those services.
4. `my-discord-bot#56` finalizes Discord-owned consumer semantics after issues
   #2-#4; `my-discord-bot#103` implements the client with shared fixtures after
   the server boundary is defined.
5. Issue #20 supplies reproducible native/container supervision, credentials,
   private networking, readiness, restart, and rollback evidence.
6. When failure containment, dependency conflicts, scaling, or non-cooperative
   cancellation justify it, replace one adapter implementation with a client
   for an independently supervised local service. Keep the gateway adapter
   contract and bot-facing protocol stable, add producer/consumer compatibility
   fixtures, and repeat security and deployment approval for that service.

No stage assumes adjacent source checkouts or shared mutable storage. Health
integration stays outside the critical path for the first generic/language/game
release and remains disabled unless every health-specific gate is satisfied.

## Follow-up contract ownership

| Decision or implementation | Owning work |
| --- | --- |
| HTTP resources, request/result envelopes, errors, progress, cancellation, and version rules | `chat-assistant#3` and `#13` |
| Client credential, caller identity, authorization, privacy, retention, replay, and audit policy | `chat-assistant#4` |
| Gateway package, service entry point, graceful lifecycle foundation | `chat-assistant#5` |
| Binding, origins, secrets, safe errors, and logging configuration | `chat-assistant#6` |
| Job deadlines, back-pressure, cooperative cancellation, and cleanup | `chat-assistant#8` |
| Dependency readiness and compatibility health | `chat-assistant#9` |
| Language, game, and gated health gateway adapters | `chat-assistant#11`, `#12`, and `#30` |
| Discord consumer semantics and authenticated client | `my-discord-bot#56` and `#103` |
| Language public application service | `lang-assistant#62` |
| Game public application service | `game-assistant#46` |
| Health public application service and safety/privacy prerequisites | `health-assistant#1`-`#4` and `#21` |
| Native/container supervision, secret delivery, readiness, restart, and rollback | `chat-assistant#20` and `my-discord-bot#111` |

## Approval, compatibility, and rollback

This ADR changes a cross-repository architecture boundary and defines a local
authentication assumption. It requires explicit human architecture and
security approval before its status changes to `accepted` or its PR is merged.

The change is documentation-only and introduces no endpoint, dependency,
secret, data migration, runtime behavior, or health enablement. Before runtime
implementation exists, rollback is a revert of this ADR. After dependent work
starts, superseding the decision requires a new ADR and migration evidence for
the bot client, gateway, enabled specialist contracts, deployment, and rollback
path; it must not silently reinterpret the versioned protocol.
