# v1.2.0 native UI responsiveness checks

These controlled measurements use real Tk/Aqua widgets with fake camera, network, cache and dialog providers. They are not live USB, physical mouse-latency, universal FPS or every-machine assurances. [The machine-readable report](ui-performance-1.2.0.json) preserves workloads, environment, exact GUI source fingerprint and both cold-map/warmed results.

## Workloads and method

- Match baseline `202a4bc` and the current candidate on one host at 1160×760, 960×640 and 1400×900.
- Run the ordinary Tk `mainloop`; producers only enqueue callbacks. Do not manually invoke the queue scheduler or create duplicate timer loops.
- Pace 2,000 log lines over two seconds (ten lines every ten milliseconds), and separately enqueue a 10,000-line burst in 100 chunks.
- Measure timer heartbeat gaps, scheduled navigation plus widget paint, worker publication delay and full debounced filter completion.
- Keep a cold first-map run and a separate run realizing both tabs at the target geometry before steady-state measurement. Warmup is disclosed, not a replacement for cold behavior.

## Current candidate observations

The warmed 10,000-line burst heartbeat maximum was approximately **1,269–1,861 ms before** and **33–65 ms after**. This includes both batching/bounded scheduling and the user-selected retention change: the new Activity history settles at 5,000 rows and explicitly reports 5,000 older rows omitted; the baseline retained all 10,000.

Warmed navigation under paced load remained below the proposed 100 ms p95 target at all sizes. The largest-window idle navigation p95 was about 61 ms, exceeding the proposed 50 ms idle target in that run. Not every proposed timing target passed; no blanket smoothness guarantee is inferred.

Cold first mapping of the complete Store after a non-default geometry change still showed about **317–355 ms** native widget realization in the new GUI, also present (slower) in the baseline. Repeated warmed interactions and log load are different from that one-time mapping cost. Preserving the existing 26-card native Store does not justify hiding it.

Search input is debounced by 150 ms and rendered in bounded chunks. Full results settled in about 173–180 ms; this deliberately trades a short wait for avoiding repeated synchronous filtering on each keystroke. Do not describe it as instantaneous results or infer a generic speedup from just the keystroke handler.

## Required functional checks

Scrolling still needs exact 60 px/notch, packed vertical TouchpadScroll 1:1, horizontal-only no-op, Store-scoped bindtags and independent Activity scrolling. Focus, selection, filter generation, omission counts, Clear and retained-view Copy/Export are behavioral regressions, not timing-only checks.

Before publication, rerun after any reviewed GUI fix and fingerprint the final source. Real platform CI must also pass source tests, native Tk smoke and the final frozen runtime. Only then may release evidence reference these results; optional CI fixtures and physical-camera limits must remain explicit.
