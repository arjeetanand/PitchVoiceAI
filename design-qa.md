# Design QA — Pitchroom AI 3D presentation flow

## Review inputs

- **Selected visual direction:** bright editorial pitch-rehearsal page with a blue/cyan open particle halo, implemented as a responsive WebGL field rather than a bitmap.
- **Reference visual:** `/Users/arjeetanand/.codex/generated_images/01a0957a-9f08-7e22-b43d-103419a40c05/exec-f35c6196-23bf-4a6d-b873-ff12e9b4910a.png`
- **Desktop implementation capture:** `/private/tmp/pitchroom-desktop-entry.jpg` (normal browser viewport, initial page entry).
- **Live-answer implementation capture:** `/private/tmp/pitchroom-live-grounded-answer.jpg` (normal browser viewport, grounded typed-answer state).
- **Mobile implementation capture:** `/private/tmp/pitchroom-mobile-hero.jpg` (compact layout).

## States reviewed

| Area | State | Result |
| --- | --- | --- |
| Hero | Initial desktop entry | Pass — light canvas, two-line editorial headline, clear primary action, and open 3D particle field preserve the selected direction. |
| Story | Normal scrolling between five scenes | Pass — ordinary document scrolling changes the field without scroll-jacking. |
| Live room | Ready | Pass — the primary microphone action, VAD promise, and typed fallback are visible together. |
| Live room | Curated prompt → grounded answer | Pass — prompt fills and focuses the fallback question field; the answer and matching source evidence render in the same flow. |
| Mobile | Compact hero and live-room layout | Pass — navigation condenses, actions remain reachable, and no horizontal clipping was visible. |
| Motion/accessibility | Reduced-motion and fallback paths | Pass by implementation review — CSS suppresses transitions, `scene.js` renders a static state for the media query, and WebGL failure hides only the decorative canvas. |

## Functional checks

- Verified a source-grounded typed answer for “How does Pitchroom AI stay trustworthy?” with one matching excerpt.
- Verified the three curated prompt queries against `/api/voice/answer`; each returns grounded demo-source evidence.
- Verified WebGL reaches `data-webgl="ready"` with no browser warnings or errors.
- Did not request microphone permission during QA; the existing live mic/barge-in loop remains unchanged and keeps its explicit user permission boundary.

## Findings and iterations

| Severity | Finding | Resolution |
| --- | --- | --- |
| P2 | The first hero pass made the field too quiet on white and allowed the headline to wrap too aggressively. | Increased particle density, tuned the particle palette/opacity, widened the hero copy column, and constrained the hero headline to a clear two-line composition. |
| P2 | Two generic teaser questions were intentionally refused by the demo source, which weakens a live presentation. | Replaced all prompt cards with questions demonstrably supported by the included approved brief. |
| P2 | The old static orb asset no longer matched the visual system. | Removed the unused asset and documented the new canvas-based visual layer. |

## Final result

**Passed.** No unresolved P0, P1, or P2 visual, responsive, or interaction issues were found in the reviewed states.
