# Design QA — Pitchroom AI 3D presentation flow

## Review inputs

- **Selected visual direction:** bright editorial pitch-rehearsal page with a blue/cyan open particle halo, implemented as a responsive WebGL field rather than a bitmap.
- **Reference visual:** `/Users/arjeetanand/.codex/generated_images/01a0957a-9f08-7e22-b43d-103419a40c05/exec-f35c6196-23bf-4a6d-b873-ff12e9b4910a.png`
- **Desktop implementation capture:** `/private/tmp/pitchroom-depth-hero.jpg` (normal browser viewport, initial page entry with depth hierarchy).
- **Live-answer implementation capture:** `/private/tmp/pitchroom-depth-live-answer.jpg` (normal browser viewport, grounded typed-answer state).
- **Mobile implementation capture:** `/private/tmp/pitchroom-depth-mobile.jpg` (compact layout).

## States reviewed

| Area | State | Result |
| --- | --- | --- |
| Hero | Initial desktop entry | Pass — light canvas, two-line editorial headline, clear primary action, and open 3D particle field preserve the selected direction. |
| Story | Normal scrolling between five scenes | Pass — ordinary document scrolling changes the field without scroll-jacking. |
| Live room | Ready | Pass — the primary microphone action, VAD promise, and typed fallback are visible together. |
| Live room | Curated prompt → grounded answer | Pass — prompt fills and focuses the fallback question field; the answer and matching source evidence render in the same flow. |
| Motion | Pointer moved across the hero | Pass — depth bands, particle scale, cursor wake, and orbit rails follow with eased parallax and return smoothly toward rest. |
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
| P2 | Pointer response was too subtle to communicate depth. | Added eased pointer targets for camera drift, orbital tilt, and field parallax while retaining the reduced-motion gate. |
| P1 | Particles were visible through the live transcript and evidence surfaces. | Raised card opacity and added a light blur plane so the product UI stays readable while the field remains visible around it. |
| P1 | The original field still read as a flat ring: one PointsMaterial, near-uniform dots, and no per-particle z response. | Added an inline shader for cursor-driven z displacement, depth-based size/brightness, a velocity wake, varied foreground sparks, and three orbit rails; kept the semantic HTML layer untouched. |

## GitHub patterns reviewed

- [brunoimbrizi/interactive-particles](https://github.com/brunoimbrizi/interactive-particles) — off-screen pointer texture driving per-particle displacement; adapted here as a small inline shader so the app keeps its no-build vanilla frontend.
- [pmndrs/react-three-fiber](https://github.com/pmndrs/react-three-fiber) — strong scroll/GPGPU examples, but its React renderer would add a framework migration that is not justified for this page.
- [JudyZZ/threejs-parallax-skill](https://github.com/JudyZZ/threejs-parallax-skill) — useful layered 2.5D mouse/scroll parallax reference, but it assumes a stack of image assets rather than this procedural field.
- [mrdoob/three.js examples](https://github.com/mrdoob/three.js/tree/dev/examples) — GPGPU water/birds are true simulations, but heavier than a decorative presentation background needs.

## Final result

**Passed.** No unresolved P0, P1, or P2 visual, responsive, or interaction issues were found in the reviewed states.
