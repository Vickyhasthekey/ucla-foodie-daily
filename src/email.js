// Morning email rules imported from the n8n "Build AI request" and "Parse AI" nodes.

const MODEL = "openai/gpt-oss-20b:free";

const SYSTEM = [
  "You are a UCLA dining assistant. The menu is given as lines 'Hall | Meal | Dish'.",
  "Inputs: today's menu lines, a list of WANTED foods, an optional RECOMMENDATION PREFERENCE.",
  "Use ONLY dishes that appear in the menu lines, with their EXACT dish names and the Hall and Meal shown.",
  "If the menu is '(no dining service today)' or empty, set service_today=false.",
  "A) MATCHED = EVERY menu dish matching the WANTED foods, INCLUDING synonyms (bulgogi/carne asada/",
  "   brisket=beef; ribeye/sirloin=steak; lox=salmon). List ALL matches; omit none; add no non-matches.",
  "B) SUGGESTED = 3-5 OTHER dishes tailored to the PREFERENCE, ONLY if a preference is given",
  "   ('grow taller'->protein/calcium/vitamin-D; 'digestion'->easy-to-digest; 'premium'->seafood/steak/",
  "   prime cuts). If NO preference, set suggested=''. SUGGESTED must never repeat a dish in MATCHED.",
  "wanted_found=true iff MATCHED is non-empty.",
  "GROUP BY DISH: one line per UNIQUE dish (merge its halls/meals), format EXACTLY:",
  "- <Dish> — <Hall> (<Meal>), <Hall> (<Meal>)",
  "Reply ONLY JSON: { \"service_today\": bool, \"wanted_found\": bool, \"rec_theme\": string, \"matched\": string, \"suggested\": string }.",
  "matched/suggested = newline-separated dish lines or ''. rec_theme = short phrase naming SUGGESTED or ''.",
  "If service_today=false set matched='' suggested='' and put a short friendly no-service note in rec_theme.",
].join("\n");

function buildUserMessage(today, foods, pref, menuText) {
  const wanted = String(foods || "")
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
  return (
    "Today is " + today + ".\n" +
    "WANTED foods: " + wanted.join(", ") + "\n" +
    "RECOMMENDATION PREFERENCE: " + (String(pref || "").trim() || "(none)") + "\n\n" +
    "=== TODAY'S MENU (Hall | Meal | Dish) ===\n" +
    (menuText || "")
  );
}

function buildLocationMap(menuText) {
  const map = new Map();
  String(menuText || "").split("\n").forEach((line) => {
    const parts = line.split(" | ");
    if (parts.length < 3) return;
    const hall = parts[0].trim();
    const meal = parts[1].trim();
    const dish = parts.slice(2).join(" | ").trim();
    const loc = hall + " (" + meal + ")";
    if (!map.has(dish)) map.set(dish, []);
    if (map.get(dish).indexOf(loc) < 0) map.get(dish).push(loc);
  });
  return map;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function resolveLines(aiText, locMap) {
  const seen = new Set();
  const out = [];
  String(aiText || "").split("\n").forEach((line) => {
    const trimmed = line.replace(/^[-•]\s*/, "").trim();
    if (!trimmed) return;
    let sep = trimmed.indexOf(" — ");
    const dish = (sep > -1 ? trimmed.slice(0, sep) : trimmed).trim();
    const aiLocs = sep > -1 ? trimmed.slice(sep + 3).trim() : "";
    if (!dish || seen.has(dish)) return;
    seen.add(dish);
    const locs = locMap.get(dish);
    const locStr = locs && locs.length ? locs.join(", ") : aiLocs;
    out.push(dish + (locStr ? " — " + locStr : ""));
  });
  return out.sort();
}

function listItems(lines) {
  return lines.map((line) => {
    const sep = line.indexOf(" — ");
    if (sep > -1) {
      return "<li><strong>" + escapeHtml(line.slice(0, sep)) + "</strong> — " + escapeHtml(line.slice(sep + 3)) + "</li>";
    }
    return "<li>" + escapeHtml(line) + "</li>";
  }).join("");
}

function section(title, items) {
  if (!items) return "";
  return "<p style=\"margin:18px 0 2px;font-size:15px;font-weight:700\">" + title + "</p>" +
    "<ul style=\"line-height:1.8;padding-left:20px;font-size:15px;margin-top:6px\">" + items + "</ul>";
}

function renderEmail(options) {
  const today = options.today;
  const email = options.email;
  const parsed = options.parsed || {};
  const signupUrl = options.signupUrl;
  const unsubscribeUrl = options.unsubscribeUrl;
  const locMap = buildLocationMap(options.menuText);
  const theme = parsed.rec_theme || "other tasty picks";
  const matched = resolveLines(parsed.matched, locMap);
  const suggested = resolveLines(parsed.suggested, locMap);
  const matchedItems = listItems(matched);
  const suggestedItems = listItems(suggested);
  let intro = "";
  let body = "";
  if (!parsed.service_today) {
    intro = "Good morning! " + (parsed.rec_theme || "There's no dining service today.");
  } else if (matchedItems && suggestedItems) {
    intro = "Good morning! Here's what's good for you today 👇";
    body = section("⭐ Your favorites", matchedItems) + section("🌱 Also worth trying — " + escapeHtml(theme), suggestedItems);
  } else if (matchedItems) {
    intro = "Good morning! Here's where to find your favorite foods today 👇";
    body = "<ul style=\"line-height:1.8;padding-left:20px;font-size:15px;margin-top:6px\">" + matchedItems + "</ul>";
  } else if (suggestedItems) {
    intro = "Good morning! Today's menu doesn't have your picks — but here's what to try 👇";
    body = "<ul style=\"line-height:1.8;padding-left:20px;font-size:15px;margin-top:6px\">" + suggestedItems + "</ul>";
  } else {
    intro = "Good morning! Today's menu doesn't have your picks today.";
  }
  const footer = "You're receiving this because you subscribed to UCLA Foodie Daily." +
    "<br><span style=\"display:inline-block;margin-top:6px\">" +
    "<a href=\"" + signupUrl + "\" style=\"color:#999;text-decoration:underline\">Update my preferences</a>" +
    " &nbsp;·&nbsp; " +
    "<a href=\"" + unsubscribeUrl + "\" style=\"color:#999;text-decoration:underline\">Unsubscribe</a></span>";
  const html = "<div style=\"font-family:-apple-system,Segoe UI,Roboto,Helvetica,sans-serif;max-width:560px;margin:0 auto;color:#1a1a1a\">" +
    "<h2 style=\"margin:0 0 2px\">🍽️ UCLA Foodie Daily</h2>" +
    "<p style=\"color:#8a8a8a;margin:0 0 14px;font-size:13px\">" + escapeHtml(today) + "</p>" +
    "<p style=\"margin:0 0 6px;font-size:15px\">" + intro + "</p>" + body +
    "<p style=\"color:#b0b0b0;font-size:12px;margin-top:26px;border-top:1px solid #eee;padding-top:12px\">" + footer + "</p></div>";
  let text = "Good morning! \n\n";
  if (matchedItems) text += "Your favorites today:\n- " + matched.join("\n- ") + "\n\n";
  if (suggestedItems) text += (theme ? theme + ":\n" : "") + "- " + suggested.join("\n- ") + "\n\n";
  text += "— UCLA Foodie Daily\n\nUpdate your picks: " + signupUrl + "\nUnsubscribe: " + unsubscribeUrl;
  return {
    email: email,
    serviceToday: !!parsed.service_today,
    subject: "🍽️ Today's UCLA dining picks · " + today,
    html: html,
    text: text,
  };
}

const SAMPLE_MENU = [
  "Bruin Plate | Lunch | Beef Bulgogi",
  "De Neve | Lunch | Grilled Salmon",
  "Bruin Plate | Dinner | Beef Bulgogi",
  "Epicuria | Lunch | Tiramisu",
].join("\n");

const SAMPLE_PARSED = {
  service_today: true,
  wanted_found: true,
  rec_theme: "protein and calcium",
  matched: "- Beef Bulgogi — Bruin Plate (Lunch)\n- Grilled Salmon — De Neve (Lunch)",
  suggested: "- Tiramisu — Epicuria (Lunch)",
};
