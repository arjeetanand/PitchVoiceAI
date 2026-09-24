/*
 * Pitchroom motion layer
 *
 * The current Framer Motion package is Motion. This page is intentionally a
 * no-build HTML app, so it uses Motion's framework-agnostic JavaScript API
 * from a pinned ESM CDN import while keeping the product UI semantic HTML.
 */
(() => {
  const root = document.documentElement;
  const motionMedia = window.matchMedia("(prefers-reduced-motion: reduce)");
  const motionModuleUrl = "https://cdn.jsdelivr.net/npm/motion@13.2.0/+esm";
  const easing = [0.22, 0.84, 0.26, 1];

  root.dataset.motion = "loading";
  root.dataset.reducedMotion = String(motionMedia.matches);

  function reducedMotion() {
    return motionMedia.matches;
  }

  function setMotionStatus(status, ready = false) {
    root.dataset.motion = status;
    root.dataset.reducedMotion = String(reducedMotion());
    window.PitchroomMotion = {
      ready,
      reducedMotion: reducedMotion(),
      version: "13.2.0",
    };
  }

  function finaliseReducedTargets() {
    if (!reducedMotion()) return;
    document.querySelectorAll("[data-motion-target]").forEach((element) => {
      element.style.opacity = "";
      element.style.transform = "";
    });
  }

  motionMedia.addEventListener("change", () => {
    root.dataset.reducedMotion = String(reducedMotion());
    finaliseReducedTargets();
    if (window.PitchroomMotion) window.PitchroomMotion.reducedMotion = reducedMotion();
  });

  function markTarget(element, distance = 22) {
    if (!element) return;
    element.dataset.motionTarget = "true";
    if (reducedMotion()) return;
    element.style.opacity = "0";
    element.style.transform = `translateY(${distance}px)`;
  }

  function reveal(animate, element, options = {}) {
    if (!element) return;
    const distance = options.distance ?? 22;
    if (reducedMotion()) {
      animate(element, { opacity: 1 }, { duration: 0.01 });
      return;
    }
    animate(
      element,
      { opacity: [0, 1], y: [distance, 0] },
      {
        duration: options.duration ?? 0.72,
        delay: options.delay ?? 0,
        ease: easing,
      },
    );
  }

  function springPulse(animate, element, values = { scale: [0.965, 1], y: [3, 0] }) {
    if (!element) return;
    if (reducedMotion()) {
      animate(element, { opacity: [0.72, 1] }, { duration: 0.01 });
      return;
    }
    animate(element, values, {
      type: "spring",
      stiffness: 480,
      damping: 32,
      mass: 0.72,
    });
  }

  function setupIntro(animate, stagger) {
    const introSelector = [
      ".topbar-inner",
      ".hero-copy > .eyebrow",
      ".hero-copy > h1",
      ".hero-copy > .hero-lede",
      ".hero-copy > .hero-actions",
      ".hero-copy > .grounding-line",
      ".hero-console",
      ".hero-section > .story-signature",
    ].join(", ");
    const introTargets = [...document.querySelectorAll(introSelector)];
    introTargets.forEach((element) => markTarget(element, element.classList.contains("topbar-inner") ? 10 : 20));
    if (!introTargets.length) return;

    if (reducedMotion()) {
      animate(introTargets, { opacity: 1 }, { duration: 0.01 });
      return;
    }

    animate(
      introTargets,
      { opacity: [0, 1], y: [20, 0] },
      {
        duration: 0.72,
        delay: stagger(0.075, { startDelay: 0.08 }),
        ease: easing,
      },
    );
  }

  function setupScrollReveals(animate, inView) {
    const revealGroups = [
      [".problem-copy", 24],
      [".question-field", 30],
      [".live-section-head", 18],
      [".live-layout", 26],
      [".proof-copy", 24],
      [".proof-desk", 30],
      [".cta-copy", 24],
      [".cta-section > .story-signature", 18],
      [".footer", 12],
    ];

    revealGroups.forEach(([selector, distance]) => {
      document.querySelectorAll(selector).forEach((element) => {
        markTarget(element, distance);
        inView(
          element,
          () => reveal(animate, element, { distance }),
          { amount: 0.16, margin: "0px 0px -8% 0px" },
        );
      });
    });
  }

  function setupArrowFeedback(animate) {
    document.querySelectorAll(".button .button-arrow, .text-link svg").forEach((arrow) => {
      const trigger = arrow.closest("button, a");
      if (!trigger) return;
      const settle = () => animate(arrow, { x: 0 }, { type: "spring", stiffness: 480, damping: 30, mass: 0.7 });
      const lift = () => {
        if (reducedMotion()) return;
        animate(arrow, { x: 4 }, { type: "spring", stiffness: 480, damping: 30, mass: 0.7 });
      };
      trigger.addEventListener("pointerenter", lift);
      trigger.addEventListener("focus", lift);
      trigger.addEventListener("pointerleave", settle);
      trigger.addEventListener("blur", settle);
    });

    document.querySelectorAll(".button .button-icon").forEach((icon) => {
      const trigger = icon.closest("button");
      if (!trigger) return;
      const settle = () => animate(icon, { scale: 1 }, { type: "spring", stiffness: 520, damping: 30, mass: 0.68 });
      trigger.addEventListener("pointerdown", () => {
        if (!reducedMotion()) animate(icon, { scale: 0.9 }, { duration: 0.08, ease: "easeOut" });
      });
      trigger.addEventListener("pointerup", settle);
      trigger.addEventListener("pointercancel", settle);
      trigger.addEventListener("pointerleave", settle);
    });
  }

  function setupLiveFeedback(animate) {
    const stateChip = document.querySelector("#state-chip");
    const groundingBadge = document.querySelector("#grounding-badge");
    const answer = document.querySelector("#answer-copy");
    const halos = [...document.querySelectorAll(".voice-halo-line")];

    window.addEventListener("pitchroom:voice-phase", () => {
      springPulse(animate, stateChip);
      if (halos.length && !reducedMotion()) {
        animate(halos, { opacity: [0.32, 0.84, 0.62] }, { duration: 0.85, ease: easing });
      }
    });

    window.addEventListener("pitchroom:answer-grounding", () => {
      springPulse(animate, groundingBadge, { scale: [0.97, 1], y: [4, 0] });
      if (answer) reveal(animate, answer, { distance: 8, duration: 0.5 });
    });

    const evidenceList = document.querySelector("#evidence-list");
    if (!evidenceList) return;
    const evidenceObserver = new MutationObserver((records) => {
      records.forEach((record) => {
        [...record.addedNodes]
          .filter((node) => node.nodeType === Node.ELEMENT_NODE)
          .flatMap((node) => [node, ...node.querySelectorAll?.(".evidence-quote") || []])
          .filter((node) => node.matches?.(".evidence-quote"))
          .forEach((quote) => {
            markTarget(quote, 12);
            reveal(animate, quote, { distance: 12, duration: 0.48 });
          });
      });
    });
    evidenceObserver.observe(evidenceList, { childList: true });
  }

  async function start() {
    try {
      const { animate, inView, stagger } = await import(motionModuleUrl);
      if (typeof animate !== "function" || typeof inView !== "function" || typeof stagger !== "function") {
        throw new Error("Motion API unavailable");
      }
      setMotionStatus("ready", true);
      setupIntro(animate, stagger);
      setupScrollReveals(animate, inView);
      setupArrowFeedback(animate);
      setupLiveFeedback(animate);
      window.dispatchEvent(new CustomEvent("pitchroom:motion-ready"));
    } catch (_) {
      // Motion is a presentation enhancement. The full semantic UI remains
      // visible and functional if the optional module cannot load.
      setMotionStatus("unavailable", false);
    }
  }

  void start();
})();
