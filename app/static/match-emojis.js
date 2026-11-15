(() => {
  const field = document.querySelector(".match-emoji-field");
  if (!field) return;

  const emojis = Array.from(field.querySelectorAll(".match-emoji"));
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const max = 5;
  const FOODS = [
    "🍜", "🍔", "🌮", "🍕", "🍓", "🍩", "🥑", "🍣", "🍰", "🍦",
    "🍇", "🍉", "🍒", "🥐", "🥗", "🍤", "🍱", "🍪", "🫐", "🥭",
    "🥝", "🍎", "🥨", "🥞", "🧋", "🥟", "🍙",
  ];
  let targetX = 0;
  let targetY = 0;
  let curX = 0;
  let curY = 0;

  function rand(min, max) {
    return min + Math.random() * (max - min);
  }

  function nextFood(current) {
    let pick = current;
    for (let i = 0; i < 8 && pick === current; i += 1) {
      pick = FOODS[Math.floor(Math.random() * FOODS.length)];
    }
    return pick;
  }

  const storageKey = "foodie_match_emoji_layout";

  function layoutSignature() {
    const faces = emojis.map((el) => (el.querySelector(".match-emoji-face") || el).textContent.trim()).join("");
    return `${emojis.length}:${faces}:${window.matchMedia("(max-width: 760px)").matches ? "narrow" : "wide"}`;
  }

  function applyLayout(spots) {
    emojis.forEach((el, index) => {
      const spot = spots[index];
      if (!spot) return;
      el.style.setProperty("--x", spot.x);
      el.style.setProperty("--y", spot.y);
      el.style.setProperty("--size", spot.size);
      el.dataset.depth = spot.depth;
    });
  }

  function buildLayout() {
    const narrow = window.matchMedia("(max-width: 760px)").matches;
    // Alternate left/right gutters; keep clear of the centered text column.
    const leftBand = narrow ? [0, 3.5] : [0.8, 7.5];
    const rightBand = narrow ? [93, 97.5] : [91, 97.5];
    const usedY = [];
    return emojis.map((el, index) => {
      const leftSide = index % 2 === 0;
      const [x0, x1] = leftSide ? leftBand : rightBand;
      let y = rand(6, 90);
      for (let attempt = 0; attempt < 8; attempt += 1) {
        if (usedY.every((other) => Math.abs(other - y) > 12)) break;
        y = rand(6, 90);
      }
      usedY.push(y);
      return {
        x: `${rand(x0, x1).toFixed(2)}%`,
        y: `${y.toFixed(2)}%`,
        size: `${(narrow ? rand(38, 50) : rand(60, 86)).toFixed(0)}px`,
        depth: rand(0.55, 1).toFixed(2),
      };
    });
  }

  function placeInMargins(forceNew) {
    const signature = layoutSignature();
    if (!forceNew) {
      try {
        const saved = JSON.parse(sessionStorage.getItem(storageKey) || "null");
        if (saved && saved.signature === signature && Array.isArray(saved.spots) && saved.spots.length === emojis.length) {
          applyLayout(saved.spots);
          return;
        }
      } catch (_) {
        /* ignore bad cache */
      }
    }
    const spots = buildLayout();
    applyLayout(spots);
    try {
      sessionStorage.setItem(storageKey, JSON.stringify({ signature, spots }));
    } catch (_) {
      /* private mode, etc. */
    }
  }

  function paint() {
    emojis.forEach((el) => {
      const depth = Number(el.dataset.depth || 1);
      el.style.setProperty("--tilt-x", `${(curX * depth).toFixed(2)}px`);
      el.style.setProperty("--tilt-y", `${(curY * depth).toFixed(2)}px`);
    });
  }

  function tick() {
    curX += (targetX - curX) * 0.08;
    curY += (targetY - curY) * 0.08;
    paint();
    requestAnimationFrame(tick);
  }

  function clamp(value) {
    return Math.max(-max, Math.min(max, value));
  }

  function onOrient(event) {
    const gamma = Math.max(-24, Math.min(24, event.gamma || 0));
    const beta = Math.max(-24, Math.min(24, (event.beta || 45) - 45));
    targetX = clamp((gamma / 24) * max);
    targetY = clamp((beta / 24) * max);
  }

  function pop(face) {
    if (!face || reduced) return;
    face.animate(
      [
        { transform: "scale(1) rotate(0deg) translateY(0)" },
        { transform: "scale(1.4) rotate(-14deg) translateY(-10px)", offset: 0.32 },
        { transform: "scale(1.12) rotate(10deg) translateY(-2px)", offset: 0.62 },
        { transform: "scale(1) rotate(0deg) translateY(0)" },
      ],
      { duration: 520, easing: "cubic-bezier(0.22, 0.75, 0.2, 1)" }
    );
  }

  emojis.forEach((el) => {
    const face = el.querySelector(".match-emoji-face") || el;
    el.addEventListener("click", (event) => {
      event.preventDefault();
      face.textContent = nextFood(face.textContent.trim());
      pop(face);
    });
    el.addEventListener("pointerdown", () => el.classList.add("is-pressed"));
    el.addEventListener("pointerup", () => el.classList.remove("is-pressed"));
    el.addEventListener("pointerleave", () => el.classList.remove("is-pressed"));
    el.addEventListener("pointercancel", () => el.classList.remove("is-pressed"));
  });

  placeInMargins(false);
  window.addEventListener("resize", () => {
    window.clearTimeout(placeInMargins._t);
    // Only rebuild when crossing mobile/desktop; keep spots stable across swipes.
    placeInMargins._t = window.setTimeout(() => placeInMargins(false), 120);
  });

  if (!reduced) {
    requestAnimationFrame(tick);
    if (window.DeviceOrientationEvent) {
      window.addEventListener("deviceorientation", onOrient, { passive: true });
    }
  }
})();
