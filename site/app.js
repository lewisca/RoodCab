/* Rood Cab landing — tiny, dependency-free interactions. */
(function () {
  "use strict";

  // Rood Cab Python API (server.py). If set, signup registers a provider here and the
  // offers step saves to it. Leave "" for local-demo mode (validates + advances, no calls).
  //   e.g. var API_BASE = "http://localhost:8000";
  var API_BASE = "";

  // Node connect-server (connect-server/) that mints Zapier connect-links. If set, the
  // "Connect with Zapier" button opens a real connect URL. Leave "" to simulate it.
  //   e.g. var CONNECT_LINK_ENDPOINT = "http://localhost:8787/connect-link";
  var CONNECT_LINK_ENDPOINT = "";

  // Per-provider identity captured at registration (real mode); used by connect + offers.
  var providerId = null, apiToken = null;

  // Manual-fallback webhook host (Zapier "Webhooks by Zapier → POST" target). The
  // per-account path + secret are generated below; matches webhook.py intake.
  var WEBHOOK_HOST = "https://hooks.roodcab.io/v1/intake";

  var $ = function (id) { return document.getElementById(id); };

  // --- current year in footer ---
  if ($("year")) $("year").textContent = new Date().getFullYear();

  // --- scroll reveal ---
  var reveals = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
      });
    }, { threshold: 0.12 });
    reveals.forEach(function (el) { io.observe(el); });
  } else {
    reveals.forEach(function (el) { el.classList.add("in"); });
  }

  // --- helpers ---
  function slugify(s) {
    return (s || "client").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 24) || "client";
  }
  function randHex(n) {
    var b = new Uint8Array(n);
    (window.crypto || window.msCrypto).getRandomValues(b);
    return Array.prototype.map.call(b, function (x) { return ("0" + x.toString(16)).slice(-2); }).join("");
  }
  function storeConnection(conn) {
    try {
      var conns = JSON.parse(localStorage.getItem("roodcab_connections") || "[]");
      conns.push(Object.assign({ connected_at: new Date().toISOString() }, conn));
      localStorage.setItem("roodcab_connections", JSON.stringify(conns));
    } catch (e) { /* storage off — ignore */ }
  }

  // --- signup form (phase 1) ---
  var form = $("signup-form");
  if (!form) return;
  var verify = $("onboard-verify");
  var onboard = $("onboard");
  var pendingCompany = "client";

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    if (!form.checkValidity()) { form.reportValidity(); return; }

    var data = {
      company: form.company.value.trim(), contact: form.contact.value.trim(),
      email: form.email.value.trim(), phone: form.phone.value.trim(),
      crm: form.crm.value, clients: form.clients.value, notes: form.notes.value.trim(),
      consent: form.consent.checked, submitted_at: new Date().toISOString()
    };

    var btn = form.querySelector('button[type="submit"]');
    btn.disabled = true; btn.textContent = "Sending…";

    function toVerifying() {
      form.hidden = true;
      verify.hidden = false;
      // Simulated verification gate. A real backend would confirm the account here.
      setTimeout(function () { verify.hidden = true; showOnboarding(data); }, 1300);
    }

    if (API_BASE) {
      // Real mode: register the provider in the Rood Cab API; capture their id + token.
      fetch(API_BASE + "/v1/providers", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ company: data.company, contact: data.contact, email: data.email })
      }).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      }).then(function (j) {
        providerId = j.provider_id; apiToken = j.api_token;
        toVerifying();
      }).catch(function () {
        btn.disabled = false; btn.textContent = "Request access";
        alert("Couldn't reach the Rood Cab API — please try again.");
      });
    } else {
      // Demo mode: stash the lead locally so nothing is silently lost, then advance.
      try {
        var all = JSON.parse(localStorage.getItem("roodcab_signups") || "[]");
        all.push(data); localStorage.setItem("roodcab_signups", JSON.stringify(all));
      } catch (e) { /* ignore */ }
      toVerifying();
    }
  });

  function showOnboarding(data) {
    pendingCompany = data.company;
    onboard.hidden = false;
    onboard.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  // Curated partner catalog (mirrors data/offers_sample.json). In production this would
  // come from your backend so the catalog stays in sync with the agent's offers config.
  var CATALOG = [
    { id: "creditbuilder-co", partner: "CreditBuilder Co", product: "credit-builder card", bands: ["B1"], priority: 10, apply: "https://creditbuilderco.com/affiliates", respa: false },
    { id: "drivenow-auto", partner: "DriveNow Auto", product: "subprime auto loan", bands: ["B2", "B3"], priority: 20, apply: "https://drivenow.com/partners", respa: false },
    { id: "firstcard-unsecured", partner: "FirstCard", product: "first unsecured card", bands: ["B2"], priority: 10, apply: "https://firstcard.com/affiliate", respa: false },
    { id: "lendfast-personal", partner: "LendFast", product: "personal loan", bands: ["B3", "B4"], priority: 15, apply: "https://lendfast.com/partners", respa: false },
    { id: "primecard-rewards", partner: "PrimeCard", product: "premium rewards card", bands: ["B4", "B5"], priority: 10, apply: "https://primecard.com/affiliates", respa: false },
    { id: "homeloan-partners", partner: "HomeLoan Partners", product: "mortgage pre-qualification", bands: ["B5"], priority: 20, apply: "https://homeloanpartners.com/licensed-referral", respa: true }
  ];

  function renderOffers() {
    var list = $("offers-list");
    if (!list || list.childElementCount) return;   // render once
    CATALOG.forEach(function (o) {
      var badges = o.bands.map(function (b) {
        return '<span class="tier-badge' + (o.respa ? ' respa' : '') + '">' + b + '</span>';
      }).join("");
      var row = document.createElement("div");
      row.className = "offer-row";
      row.dataset.id = o.id;
      row.innerHTML =
        '<div class="offer-top"><div class="offer-id"><b>' + o.partner + '</b>' +
        '<small>' + o.product + '</small></div><div class="tier-badges">' + badges + '</div></div>' +
        '<div class="offer-aff"><input type="url" class="aff-link" placeholder="Your affiliate link (e.g. https://' +
        o.id + '.com/apply?aff=YOURID&subid={subid})" /></div>' +
        '<div class="house-hint">' + (o.respa
          ? 'RESPA: mortgage must route via a licensed-partner / marketing-fee link — not a per-referral affiliate link.'
          : 'No link yet? Leave blank to use the Rood Cab house link. ') +
        '<a class="apply-link" href="' + o.apply + '" target="_blank" rel="noopener">Apply for your own →</a></div>' +
        '<div class="offer-meta"><span class="offer-prio">Priority <input type="number" class="prio" value="' +
        o.priority + '" min="0" max="100" /></span>' +
        '<label class="offer-toggle"><input type="checkbox" class="enabled" checked /> Enabled</label></div>';
      list.appendChild(row);
    });
    list.addEventListener("change", function (e) {
      var row = e.target.closest(".offer-row");
      if (e.target.classList.contains("enabled")) row.classList.toggle("off", !e.target.checked);
    });
  }

  // connection succeeded -> go to offers setup (the monetization step)
  function showConnected(conn) {
    storeConnection(conn);
    $("connect-primary").hidden = true;
    $("connect-working").hidden = true;
    $("manual").hidden = true;
    renderOffers();
    $("offers-step").hidden = false;
  }

  // offers saved -> live
  function showLive(enabledCount) {
    $("offers-step").hidden = true;
    var note = $("offers-count-note");
    if (note) note.textContent = enabledCount + " offer" + (enabledCount === 1 ? "" : "s") + " active.";
    $("ostep-done").hidden = false;
  }

  var offersSave = $("offers-save");
  if (offersSave) offersSave.addEventListener("click", function () {
    var rows = document.querySelectorAll("#offers-list .offer-row");
    var offers = [], enabledCount = 0;
    rows.forEach(function (row, i) {
      var cat = CATALOG[i];
      var aff = row.querySelector(".aff-link").value.trim();
      var enabled = row.querySelector(".enabled").checked;
      if (enabled) enabledCount++;
      offers.push({
        id: cat.id, partner: cat.partner, product: cat.product, bands: cat.bands,
        affiliate_link: aff || null,                 // null -> house link used (still attributed)
        priority: parseInt(row.querySelector(".prio").value, 10) || 0,
        enabled: enabled, compliance: cat.respa ? "respa" : "standard"
      });
    });
    if (API_BASE && providerId && apiToken) {
      // Real mode: save offers to this provider's catalog (authed).
      offersSave.disabled = true; offersSave.textContent = "Saving…";
      fetch(API_BASE + "/v1/providers/" + providerId + "/offers", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": "Bearer " + apiToken },
        body: JSON.stringify({ offers: offers })
      }).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        showLive(enabledCount);
      }).catch(function () {
        offersSave.disabled = false; offersSave.textContent = "Save offers & go live";
        alert("Couldn't save offers — please try again.");
      });
    } else {
      try { localStorage.setItem("roodcab_offers", JSON.stringify({ offers: offers })); } catch (e) {}
      showLive(enabledCount);
    }
  });

  // --- PRIMARY: Connect with Zapier (SDK connect-link) ---
  var connectBtn = $("connect-zapier");
  if (connectBtn) connectBtn.addEventListener("click", function () {
    $("connect-primary").hidden = true;
    $("connect-working").hidden = false;

    function finish() { showConnected({ method: "zapier-sdk-connect-link", app: "DisputeFox", company: pendingCompany }); }

    if (CONNECT_LINK_ENDPOINT) {
      fetch(CONNECT_LINK_ENDPOINT, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider_id: providerId, api_token: apiToken, app: "disputefox" })
      })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          var w = window.open(j.connect_url, "zapier-connect", "width=520,height=720");
          // A real flow resolves on the SDK's redirect/postMessage; here we resolve on close.
          var t = setInterval(function () { if (!w || w.closed) { clearInterval(t); finish(); } }, 800);
        })
        .catch(function () {
          $("connect-working").hidden = true; $("connect-primary").hidden = false;
          alert("Couldn't open the Zapier connect window — try manual setup.");
        });
    } else {
      setTimeout(finish, 1600);   // demo: simulate the hosted auth round-trip
    }
  });

  // --- toggle manual fallback (generate webhook creds lazily) ---
  var showManual = $("show-manual"), hideManual = $("hide-manual");
  if (showManual) showManual.addEventListener("click", function () {
    if (!$("hookUrl").value) {
      $("hookUrl").value = WEBHOOK_HOST + "/" + slugify(pendingCompany) + "-" + randHex(4);
      $("hookSecret").value = "rc_sk_" + randHex(18);
    }
    $("connect-primary").hidden = true;
    $("manual").hidden = false;
  });
  if (hideManual) hideManual.addEventListener("click", function () {
    $("manual").hidden = true;
    $("connect-primary").hidden = false;
  });

  // manual step 1 -> step 2
  var step1Next = $("step1-next");
  if (step1Next) step1Next.addEventListener("click", function () {
    $("ostep-1").hidden = true;
    $("ostep-2").hidden = false;
    setDots(2);
  });

  // copy buttons
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-copy]");
    if (!b) return;
    var input = $(b.getAttribute("data-copy"));
    input.select();
    var ok = false;
    if (navigator.clipboard) { navigator.clipboard.writeText(input.value); ok = true; }
    else { try { ok = document.execCommand("copy"); } catch (e2) {} }
    if (ok) {
      var prev = b.textContent; b.textContent = "Copied ✓"; b.classList.add("copied");
      setTimeout(function () { b.textContent = prev; b.classList.remove("copied"); }, 1600);
    }
  });

  // manual step 2 -> done
  var zapForm = $("zap-form");
  if (zapForm) zapForm.addEventListener("submit", function (ev) {
    ev.preventDefault();
    if (!zapForm.checkValidity()) { zapForm.reportValidity(); return; }
    setDots("done");
    showConnected({ method: "manual-webhook", webhook: $("hookUrl").value, zapier_email: $("zapEmail").value.trim() });
  });

  function setDots(step) {
    var d1 = document.querySelector('.dot[data-dot="1"]');
    var d2 = document.querySelector('.dot[data-dot="2"]');
    if (!d1 || !d2) return;
    if (step === 2) { d1.classList.remove("active"); d1.classList.add("done"); d2.classList.add("active"); }
    if (step === "done") { d2.classList.remove("active"); d2.classList.add("done"); }
  }
})();
