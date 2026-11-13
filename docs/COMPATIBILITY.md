# Compatibility and known limits

| Situation | Behavior / evidence scope |
| --- | --- |
| One physical monitor | Normalized restore retains available connectors only; modeled and exercised as the sole active physical output. |
| Extended/mirrored layouts | Regression tests cover order, rotation, geometry and scale; physical integration was exercised in the predecessor installation. |
| No physical monitor | Requires a usable reserve output provisioned outside this project. |
| Software-only virtual output without DRM connector | Unsupported by the initial capture-sync profile; readiness refuses it. |
| No usable output | Cannot supply a capture framebuffer; retries do not create a virtual driver. |
| Monitor off at its button | May still advertise EDID. Its part of the extended desktop can remain; no panel-power detection is claimed. |
| Physical input during a stream | Return request latches; active ownership vetoes topology/capture changes. |
| Lost journal records or journal process | Independent packet-health checks and bounded cleanup; EOF is not a stream disconnect. |
| Input device missing/unreadable | Coverage is explicit; errors use degraded idle fallback and retry scanning. |
| Observer restarts/outages | Grace is bounded; input wholly inside a gap may be lost. |
| Moving a Moonlight window | Stop/reconnect to negotiate dimensions for its new screen. |
| HDR, multiple GPUs, third monitor, multiple accounts/streams | Not certified in this initial release. |
| Boot/login screen, logout, suspend/resume | Not certified end to end; user policy needs a graphical user session. |
| KDE/wlroots/Windows/macOS hosts | Host policy unsupported; it depends on Mutter's D-Bus interfaces. |
| Sandboxed Sunshine or Moonlight | Paths, journal, capabilities and process access vary; validate separately. |

Sunshine connector names, service scope, capture backend and outgoing video port
must match your installation. The packet observer is port-based, not an
authenticated identity for each session. Unrelated applications using that port
can affect health inference. Keep the supported single-stream/hook contract.

This project deliberately does not auto-install a kernel EDID override, force a
PCI connector, replace GPU firmware or install display-manager hooks. Those
steps are hardware-dependent and can remove local access when misconfigured.
