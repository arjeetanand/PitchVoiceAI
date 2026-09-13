/*
 * Pitchroom's visual layer is deliberately separate from the conversation UI.
 * The canvas is decorative; voice controls, source evidence, and transcripts
 * remain normal semantic HTML so the app works even when WebGL is unavailable.
 */
(() => {
  const canvas = document.querySelector("#particle-canvas");
  if (!canvas) return;

  const sections = [...document.querySelectorAll("[data-scene]")];
  const counters = [...document.querySelectorAll("[data-scene-count]")];
  const motionMedia = window.matchMedia("(prefers-reduced-motion: reduce)");
  const state = {
    activeScene: 0,
    targetScene: 0,
    phase: document.documentElement.dataset.voicePhase || "ready",
    audioLevel: 0,
    grounded: null,
    noMotion: motionMedia.matches,
  };

  function setScene(index) {
    const next = Math.max(0, Math.min(4, index));
    if (next === state.targetScene) return;
    state.targetScene = next;
    document.documentElement.dataset.storyScene = String(next);
    const label = String(next + 1).padStart(2, "0");
    counters.forEach((counter) => { counter.textContent = label; });
    window.dispatchEvent(new CustomEvent("pitchroom:scene-change", { detail: { scene: next } }));
  }

  function syncScrollScene() {
    if (!sections.length) return;
    const centre = window.innerHeight * 0.5;
    let closest = 0;
    let distance = Number.POSITIVE_INFINITY;
    sections.forEach((section, index) => {
      const rect = section.getBoundingClientRect();
      const sectionCentre = rect.top + rect.height * 0.5;
      const nextDistance = Math.abs(sectionCentre - centre);
      if (nextDistance < distance) {
        distance = nextDistance;
        closest = Number(section.dataset.scene ?? index);
      }
    });
    state.activeScene = closest;
    setScene(closest);
  }

  window.PitchroomScene = {
    setPhase(phase) {
      state.phase = phase || "ready";
      document.documentElement.dataset.voicePhase = state.phase;
    },
    setAudioLevel(level) {
      state.audioLevel = Math.max(0, Math.min(0.12, Number(level) || 0));
    },
    setGrounded(grounded) {
      state.grounded = Boolean(grounded);
      document.documentElement.dataset.answerGrounded = String(state.grounded);
    },
  };

  window.addEventListener("pitchroom:voice-phase", (event) => {
    window.PitchroomScene.setPhase(event.detail?.phase);
  });
  window.addEventListener("pitchroom:answer-grounding", (event) => {
    window.PitchroomScene.setGrounded(event.detail?.grounded);
  });
  window.addEventListener("scroll", syncScrollScene, { passive: true });
  window.addEventListener("resize", syncScrollScene, { passive: true });
  motionMedia.addEventListener("change", (event) => {
    state.noMotion = event.matches;
    document.documentElement.dataset.reducedMotion = String(event.matches);
  });
  syncScrollScene();

  const THREE_URL = "https://cdn.jsdelivr.net/npm/three@0.186.0/build/three.module.js";

  import(THREE_URL)
    .then((THREE) => initialiseScene(THREE))
    .catch(() => {
      // The content remains complete and readable if a presentation network
      // blocks the optional pinned Three.js module.
      document.documentElement.dataset.webgl = "unavailable";
      canvas.hidden = true;
    });

  function initialiseScene(THREE) {
    const compact = window.matchMedia("(max-width: 700px)").matches;
    const particleCount = compact ? 1700 : 6000;
    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false, powerPreference: "high-performance" });
    } catch (_) {
      document.documentElement.dataset.webgl = "unavailable";
      canvas.hidden = true;
      return;
    }

    document.documentElement.dataset.webgl = "ready";
    renderer.setClearColor(0xffffff, 0);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, compact ? 1.2 : 1.5));
    if ("outputColorSpace" in renderer) renderer.outputColorSpace = THREE.SRGBColorSpace;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(39, 1, 0.1, 100);
    camera.position.set(0, 0, 9.4);

    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(particleCount * 3);
    const targets = new Float32Array(particleCount * 3);
    const colors = new Float32Array(particleCount * 3);
    const angle = new Float32Array(particleCount);
    const radius = new Float32Array(particleCount);
    const drift = new Float32Array(particleCount);
    const depth = new Float32Array(particleCount);

    for (let index = 0; index < particleCount; index += 1) {
      const pointer = index * 3;
      const seed = mulberry32(index * 7919 + 17);
      // Leave an arc unfilled so the field reads as an open halo, never a ball.
      angle[index] = -0.56 + seed() * Math.PI * 1.72;
      // Bias toward the inner orbit, then feather outward. This creates a
      // convincing luminous field without a heavy full-screen simulation.
      radius[index] = 0.36 + Math.pow(seed(), 0.72) * 1.72;
      drift[index] = seed() * Math.PI * 2;
      depth[index] = (seed() - 0.5) * 1.7;
      positions[pointer] = 4 + (seed() - 0.5) * 0.2;
      positions[pointer + 1] = (seed() - 0.5) * 0.2;
      positions[pointer + 2] = depth[index];

      const cyanWeight = seed();
      colors[pointer] = 0.02 + cyanWeight * 0.13;
      colors[pointer + 1] = 0.31 + cyanWeight * 0.48;
      colors[pointer + 2] = 0.9 + cyanWeight * 0.1;
    }

    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geometry.computeBoundingSphere();

    const sprite = createSpriteTexture(THREE);
    const material = new THREE.PointsMaterial({
      alphaMap: sprite,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      map: sprite,
      opacity: 0.82,
      size: compact ? 0.076 : 0.068,
      sizeAttenuation: true,
      transparent: true,
      vertexColors: true,
    });
    const particles = new THREE.Points(geometry, material);
    particles.frustumCulled = false;
    scene.add(particles);

    let targetDirty = true;
    let previousTarget = -1;
    let frame = 0;
    let lastTime = 0;
    let paused = document.hidden;
    let pointerX = 0;
    let pointerY = 0;
    let cameraX = 0;
    let cameraY = 0;

    function rebuildTargets(sceneIndex) {
      for (let index = 0; index < particleCount; index += 1) {
        const destination = targetForScene(sceneIndex, index, angle[index], radius[index], drift[index], depth[index]);
        const pointer = index * 3;
        targets[pointer] = destination.x;
        targets[pointer + 1] = destination.y;
        targets[pointer + 2] = destination.z;
      }
      previousTarget = sceneIndex;
      targetDirty = false;
    }

    function resize() {
      const width = Math.max(1, window.innerWidth);
      const height = Math.max(1, window.innerHeight);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, width < 700 ? 1.2 : 1.5));
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      targetDirty = true;
      if (state.noMotion) renderFrame(performance.now());
    }

    function renderFrame(time) {
      frame = 0;
      if (paused) return;
      if (targetDirty || previousTarget !== state.targetScene) rebuildTargets(state.targetScene);

      const delta = Math.min(48, Math.max(8, time - lastTime || 16));
      lastTime = time;
      const phaseMotion = state.phase === "thinking" ? 1.8 : state.phase === "speaking" ? 1.35 : state.phase === "listening" ? 1.1 : 0.75;
      const audioLift = Math.min(1, state.audioLevel * 17);
      const blend = state.noMotion ? 0.22 : Math.min(0.095, 0.026 + delta * 0.0018);
      const activePositions = geometry.attributes.position.array;

      for (let pointer = 0; pointer < activePositions.length; pointer += 1) {
        activePositions[pointer] += (targets[pointer] - activePositions[pointer]) * blend;
      }
      geometry.attributes.position.needsUpdate = true;

      if (!state.noMotion) {
        particles.rotation.z += delta * 0.000025 * phaseMotion;
        particles.rotation.y = Math.sin(time * 0.00018) * 0.11 + pointerX * 0.045;
        particles.position.y = Math.sin(time * 0.00029) * 0.1 + pointerY * 0.03;
      } else {
        particles.rotation.set(0, 0, 0);
        particles.position.y = 0;
      }
      const desiredSize = (compact ? 0.076 : 0.068) + audioLift * (state.phase === "listening" ? 0.055 : 0.025);
      material.size += (desiredSize - material.size) * (state.noMotion ? 1 : 0.16);
      const desiredOpacity = state.phase === "error" ? 0.22 : state.noMotion ? 0.34 : state.phase === "speaking" ? 0.92 : 0.82;
      material.opacity += (desiredOpacity - material.opacity) * 0.08;

      cameraX += (pointerX * 0.16 - cameraX) * 0.04;
      cameraY += (-pointerY * 0.12 - cameraY) * 0.04;
      camera.position.x = cameraX;
      camera.position.y = cameraY;
      camera.lookAt(0, 0, 0);
      renderer.render(scene, camera);

      if (!state.noMotion) frame = window.requestAnimationFrame(renderFrame);
    }

    function requestFrame() {
      if (!paused && !frame) frame = window.requestAnimationFrame(renderFrame);
    }

    window.addEventListener("resize", resize, { passive: true });
    window.addEventListener("scroll", () => {
      targetDirty = true;
      if (state.noMotion) renderFrame(performance.now());
      else requestFrame();
    }, { passive: true });
    window.addEventListener("pointermove", (event) => {
      if (state.noMotion) return;
      pointerX = (event.clientX / Math.max(1, window.innerWidth) - 0.5) * 2;
      pointerY = (event.clientY / Math.max(1, window.innerHeight) - 0.5) * 2;
      requestFrame();
    }, { passive: true });
    document.addEventListener("visibilitychange", () => {
      paused = document.hidden;
      if (paused && frame) {
        window.cancelAnimationFrame(frame);
        frame = 0;
      } else if (!paused) {
        lastTime = performance.now();
        requestFrame();
      }
    });
    motionMedia.addEventListener("change", () => {
      targetDirty = true;
      if (state.noMotion) {
        if (frame) window.cancelAnimationFrame(frame);
        frame = 0;
        renderFrame(performance.now());
      } else {
        requestFrame();
      }
    });

    resize();
    rebuildTargets(state.targetScene);
    requestFrame();
  }

  function targetForScene(sceneIndex, index, baseAngle, baseRadius, drift, baseDepth) {
    const wobble = Math.sin(drift * 3.1 + index * 0.17) * 0.18;
    const arcRadius = 1.95 + baseRadius * 0.86;
    const c = Math.cos(baseAngle);
    const s = Math.sin(baseAngle);

    if (sceneIndex === 0) {
      return { x: 2.45 + c * (arcRadius + wobble), y: s * (1.42 + baseRadius * 0.34), z: baseDepth + c * 0.28 };
    }
    if (sceneIndex === 1) {
      const spread = 0.55 + baseRadius * 1.55;
      return { x: 1.55 + c * spread * 1.72 + Math.sin(drift * 2) * 0.42, y: s * spread * 1.05, z: baseDepth * 1.5 + c * 0.52 };
    }
    if (sceneIndex === 2) {
      return { x: -1.48 + c * (arcRadius * 0.92), y: s * (1.34 + baseRadius * 0.26), z: baseDepth + s * 0.42 };
    }
    if (sceneIndex === 3) {
      const stream = (baseAngle + 0.56) / (Math.PI * 1.72);
      return { x: 1.0 + c * (arcRadius * 0.86) + stream * 1.45, y: s * (1.2 + baseRadius * 0.18), z: baseDepth + stream * 1.25 };
    }
    const forward = (baseAngle + 0.56) / (Math.PI * 1.72);
    return { x: 1.75 + forward * 3.2 + c * (0.44 + baseRadius * 0.22), y: s * (1.1 + baseRadius * 0.22) * (1 - forward * 0.38), z: baseDepth + forward * 2.2 };
  }

  function createSpriteTexture(THREE) {
    const spriteCanvas = document.createElement("canvas");
    spriteCanvas.width = 64;
    spriteCanvas.height = 64;
    const context = spriteCanvas.getContext("2d");
    const gradient = context.createRadialGradient(32, 32, 0, 32, 32, 32);
    gradient.addColorStop(0, "rgba(255,255,255,1)");
    gradient.addColorStop(0.32, "rgba(255,255,255,0.94)");
    gradient.addColorStop(1, "rgba(255,255,255,0)");
    context.fillStyle = gradient;
    context.fillRect(0, 0, 64, 64);
    const texture = new THREE.CanvasTexture(spriteCanvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    return texture;
  }

  function mulberry32(seed) {
    return function random() {
      let value = seed += 0x6D2B79F5;
      value = Math.imul(value ^ value >>> 15, value | 1);
      value ^= value + Math.imul(value ^ value >>> 7, value | 61);
      return ((value ^ value >>> 14) >>> 0) / 4294967296;
    };
  }
})();
