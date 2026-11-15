(() => {
  const field = document.getElementById("snack-field");
  const button = document.getElementById("tilt-snacks");
  if (!field) return;

  const snacks = Array.from(field.querySelectorAll(".snack"));
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const max = 6; // stay inside the snack rail
  const FOODS = [
    "🍜", "🍔", "🌮", "🍕", "🍓", "🍩", "🥑", "🍣", "🍰", "🍦",
    "🍇", "🍉", "🍒", "🥐", "🥗", "🍤", "🍱", "🍪", "🫐", "🥭",
    "🥝", "🍎", "🥨", "🥞", "🧋", "🥟", "🍙",
  ];
  let targetX = 0;
  let targetY = 0;
  let curX = 0;
  let curY = 0;
  let listening = false;

  function nextFood(current) {
    let pick = current;
    for (let i = 0; i < 8 && pick === current; i += 1) {
      pick = FOODS[Math.floor(Math.random() * FOODS.length)];
    }
    return pick;
  }

  function paint() {
    snacks.forEach((el) => {
      const depth = Number(el.dataset.depth || 1);
      el.style.setProperty("--tilt-x", `${(curX * depth).toFixed(2)}px`);
      el.style.setProperty("--tilt-y", `${(curY * depth).toFixed(2)}px`);
    });
  }

  function tick() {
    curX += (targetX - curX) * 0.07;
    curY += (targetY - curY) * 0.07;
    if (Math.abs(curX) > 0.05 || Math.abs(curY) > 0.05 || Math.abs(targetX) + Math.abs(targetY) > 0.05) {
      paint();
    }
    requestAnimationFrame(tick);
  }

  function clamp(value) {
    return Math.max(-max, Math.min(max, value));
  }

  function onOrient(event) {
    const gamma = Math.max(-28, Math.min(28, event.gamma || 0));
    const beta = Math.max(-28, Math.min(28, (event.beta || 45) - 45));
    targetX = clamp((gamma / 28) * max);
    targetY = clamp((beta / 28) * max);
  }

  function onMotion(event) {
    const accel = event.accelerationIncludingGravity;
    if (!accel) return;
    const shake = Math.hypot(accel.x || 0, accel.y || 0, accel.z || 0);
    if (shake < 12) return;
    targetX = clamp(targetX + (Math.random() * 6 - 3));
    targetY = clamp(targetY + (Math.random() * 6 - 3));
  }

  function startListening() {
    if (listening || reduced) return;
    window.addEventListener("deviceorientation", onOrient, { passive: true });
    window.addEventListener("devicemotion", onMotion, { passive: true });
    listening = true;
    field.classList.add("is-tilting");
    if (button) {
      button.hidden = true;
    }
  }

  async function enableTilt() {
    try {
      if (typeof DeviceOrientationEvent !== "undefined" && DeviceOrientationEvent.requestPermission) {
        const state = await DeviceOrientationEvent.requestPermission();
        if (state !== "granted") return;
      }
      if (typeof DeviceMotionEvent !== "undefined" && DeviceMotionEvent.requestPermission) {
        try {
          await DeviceMotionEvent.requestPermission();
        } catch (_) {
          /* orientation alone is enough */
        }
      }
      startListening();
    } catch (_) {
      /* ignore */
    }
  }

  snacks.forEach((el) => {
    el.addEventListener("click", (event) => {
      event.preventDefault();
      el.textContent = nextFood(el.textContent.trim());
      if (reduced) return;
      el.animate(
        [
          { transform: "scale(1) rotate(0deg)" },
          { transform: "scale(1.28) rotate(-10deg)", offset: 0.35 },
          { transform: "scale(1) rotate(0deg)" },
        ],
        { duration: 480, easing: "cubic-bezier(0.22, 0.75, 0.2, 1)" }
      );
    });
  });

  if (!reduced) {
    requestAnimationFrame(tick);
    const needsPrompt =
      typeof DeviceOrientationEvent !== "undefined" &&
      typeof DeviceOrientationEvent.requestPermission === "function";
    const coarse = window.matchMedia("(pointer: coarse)").matches;
    if (needsPrompt && button) {
      button.hidden = false;
      button.addEventListener("click", enableTilt);
    } else if (coarse || window.DeviceOrientationEvent) {
      startListening();
    }
  }
})();
