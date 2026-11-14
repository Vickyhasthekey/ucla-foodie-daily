(() => {
  const card = document.getElementById("hinge-card");
  const stack = document.getElementById("hinge-stack");
  const lede = document.getElementById("play-lede");
  const undoBtn = document.querySelector(".hinge-btn-undo");
  if (!card || !stack) return;

  const threshold = 110;
  let startX = 0;
  let startY = 0;
  let dx = 0;
  let dy = 0;
  let dragging = false;
  let locked = false;

  function setTransform(x, y, rot, stamps) {
    card.style.transform = `translate(${x}px, ${y}px) rotate(${rot}deg)`;
    if (stamps === false) return;
    card.style.setProperty("--like-opacity", Math.min(1, Math.max(0, x / threshold)));
    card.style.setProperty("--pass-opacity", Math.min(1, Math.max(0, -x / threshold)));
  }

  function resetCardMotion() {
    card.classList.remove("is-flying");
    card.style.transition = "none";
    setTransform(0, 0, 0);
    card.style.setProperty("--like-opacity", 0);
    card.style.setProperty("--pass-opacity", 0);
  }

  function escapeHtml(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function renderCard(next) {
    if (!next) return;
    stack.dataset.name = next.name || "";
    const vibeChips = (next.vibes || [])
      .map((chip) => `<span class="pill">${escapeHtml(chip)}</span>`)
      .join("");
    const allergenChips = (next.allergens || [])
      .map((chip) => `<span class="pill calm">${escapeHtml(chip)}</span>`)
      .join("");
    let prompts = "";
    if (next.vibes && next.vibes.length) {
      prompts += `<div class="hinge-prompt"><p class="hinge-prompt-label">My vibe today</p><div class="chip-row">${vibeChips}</div><button type="button" class="hinge-heart-inline" data-action="like" aria-label="Like this vibe">♥</button></div>`;
    }
    if (next.allergens && next.allergens.length) {
      prompts += `<div class="hinge-prompt"><p class="hinge-prompt-label">Menu notes</p><div class="chip-row">${allergenChips}</div></div>`;
    }
    if (!(next.vibes && next.vibes.length) && !(next.allergens && next.allergens.length)) {
      prompts += `<div class="hinge-prompt"><p class="hinge-prompt-label">Why try it</p><p class="meta">A dish from ${escapeHtml(next.hall)} for ${escapeHtml((next.meal || "").toLowerCase())}.</p><button type="button" class="hinge-heart-inline" data-action="like" aria-label="Like this dish">♥</button></div>`;
    }
    card.innerHTML = `
      <div class="hinge-stamp hinge-stamp-like" aria-hidden="true">Like</div>
      <div class="hinge-stamp hinge-stamp-pass" aria-hidden="true">Skip</div>
      <p class="meta hinge-kicker">${escapeHtml(next.meal)} · ${escapeHtml(next.hall)}</p>
      <h2 class="match-dish">${escapeHtml(next.name)}</h2>
      ${prompts}
    `;
    card.querySelectorAll("[data-action='like']").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        commit("like");
      });
    });
  }

  function updateChrome(data) {
    if (lede) {
      const meals = (data.meal_filter || []).join(", ");
      lede.textContent = `Like ${data.like_target} dishes. ${data.liked_count} liked · ${data.remaining} left in deck${meals ? ` · ${meals}` : ""}`;
    }
    if (undoBtn) {
      undoBtn.disabled = !data.can_undo;
    }
    if (data.show_save_prompt && !document.querySelector(".save-prompt")) {
      const dialog = document.createElement("dialog");
      dialog.className = "save-prompt";
      dialog.open = true;
      dialog.innerHTML = `
        <form method="dialog" class="card">
          <strong>Save your preferences</strong>
          <p class="meta">To keep Not for me ever and your dietary rules across devices, create an account or sign in.</p>
          <div class="prompt-actions">
            <a class="button" href="/account?next=${encodeURIComponent("/match")}&save_prefs=1">Create an account</a>
            <a class="ghost" href="/account?next=${encodeURIComponent("/match")}&save_prefs=1&mode=signin">Sign in</a>
            <button value="cancel" class="ghost">Keep playing</button>
          </div>
        </form>`;
      document.querySelector("main.wrap")?.appendChild(dialog);
    }
  }

  async function postAction(action) {
    const body = new FormData();
    body.set("action", action);
    const response = await fetch("/match/play", {
      method: "POST",
      body,
      headers: {
        Accept: "application/json",
        "X-Foodie-Ajax": "1",
      },
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error("swipe failed");
    return response.json();
  }

  async function finishAction(action, animated) {
    try {
      const data = await postAction(action);
      if (data.done) {
        window.location.href = data.redirect || "/match/result";
        return;
      }
      renderCard(data.card);
      updateChrome(data);
      resetCardMotion();
      // Soft entrance for the next card.
      if (animated) {
        card.style.transition = "none";
        setTransform(action === "like" ? 40 : action === "never" ? 0 : -40, action === "never" ? 24 : 12, 0, false);
        requestAnimationFrame(() => {
          card.style.transition = "transform 220ms ease";
          setTransform(0, 0, 0);
        });
      }
      locked = false;
      dx = 0;
      dy = 0;
    } catch (_) {
      // Fallback: classic submit if JSON path fails.
      const form = document.getElementById("swipe-form");
      const actionInput = document.getElementById("swipe-action");
      if (form && actionInput) {
        actionInput.value = action;
        form.submit();
      } else {
        locked = false;
      }
    }
  }

  function commit(action) {
    if (locked) return;
    locked = true;
    dragging = false;
    card.classList.add("is-flying");
    card.style.transition = "transform 480ms cubic-bezier(0.22, 0.7, 0.2, 1)";
    if (action === "like") {
      setTransform(window.innerWidth * 1.15, dy * 0.15 - 24, 18, false);
      card.style.setProperty("--like-opacity", 1);
      card.style.setProperty("--pass-opacity", 0);
    } else if (action === "never") {
      setTransform(0, window.innerHeight * 0.75, -8, false);
      card.style.setProperty("--like-opacity", 0);
      card.style.setProperty("--pass-opacity", 1);
    } else {
      setTransform(-window.innerWidth * 1.15, dy * 0.15 + 16, -18, false);
      card.style.setProperty("--like-opacity", 0);
      card.style.setProperty("--pass-opacity", 1);
    }
    window.setTimeout(() => finishAction(action, true), 420);
  }

  function undo() {
    if (locked || !undoBtn || undoBtn.disabled) return;
    locked = true;
    finishAction("undo", false);
  }

  function onDown(clientX, clientY) {
    if (locked) return;
    dragging = true;
    startX = clientX;
    startY = clientY;
    dx = 0;
    dy = 0;
    card.style.transition = "none";
  }

  function onMove(clientX, clientY) {
    if (!dragging || locked) return;
    dx = clientX - startX;
    dy = clientY - startY;
    setTransform(dx, dy * 0.15, dx / 18);
  }

  function onUp() {
    if (!dragging || locked) return;
    dragging = false;
    if (dx > threshold) commit("like");
    else if (dx < -threshold) commit("pass");
    else {
      card.style.transition = "transform 180ms ease";
      setTransform(0, 0, 0);
    }
  }

  card.addEventListener("pointerdown", (event) => {
    if (event.button != null && event.button !== 0) return;
    if (event.target.closest("button")) return;
    card.setPointerCapture(event.pointerId);
    onDown(event.clientX, event.clientY);
  });
  card.addEventListener("pointermove", (event) => onMove(event.clientX, event.clientY));
  card.addEventListener("pointerup", onUp);
  card.addEventListener("pointercancel", onUp);

  card.querySelectorAll("[data-action='like']").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      commit("like");
    });
  });

  document.querySelectorAll("form[data-swipe-action]").forEach((actionForm) => {
    actionForm.addEventListener("submit", (event) => {
      event.preventDefault();
      commit(actionForm.dataset.swipeAction);
    });
  });

  const undoForm = undoBtn?.closest("form");
  if (undoForm) {
    undoForm.addEventListener("submit", (event) => {
      event.preventDefault();
      undo();
    });
  }
})();
