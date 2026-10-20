/* JeenyChatbot frontend: chat + map + trip panel. Plain JavaScript, no build step. */
(function () {
  "use strict";

  const I18N = window.JEENY_I18N;
  const API = { chat: "/api/chat", trip: "/api/trip/action", health: "/api/health", places: "/api/places" };
  const CARS = ["economy", "taxi", "family", "vip"];
  const SEATS = { economy: 4, taxi: 4, family: 7, vip: 4 };
  const JORDAN_CENTER = [31.95, 35.93];
  const MAX_HISTORY = 12;

  const $ = (sel, root = document) => root.querySelector(sel);

  // Browser storage can be unavailable (private mode, blocked cookies): never let it break the app.
  function makeStore(kind) {
    return {
      get(key, fallback) {
        try {
          const raw = window[kind].getItem(key);
          return raw === null ? fallback : JSON.parse(raw);
        } catch (e) {
          return fallback;
        }
      },
      set(key, value) {
        try {
          window[kind].setItem(key, JSON.stringify(value));
        } catch (e) {
          /* ignore */
        }
      },
      remove(key) {
        try {
          window[kind].removeItem(key);
        } catch (e) {
          /* ignore */
        }
      },
    };
  }
  const local = makeStore("localStorage");
  const session = makeStore("sessionStorage");

  const state = {
    lang: local.get("jc.lang", "ar") === "en" ? "en" : "ar",
    theme: document.documentElement.getAttribute("data-theme") || "light",
    history: session.get("jc.history", []),
    trip: session.get("jc.trip", null),
    messages: session.get("jc.messages", []).map((m) => ({ role: m.role, text: m.text, error: m.error, pin: m.pin })),
    saved: local.get("jc.saved", null),
    here: null,
    busy: false,
    picking: null,
    speakNext: false,
    retry: null, // a message that waited for the location
  };

  const els = {
    log: $("#log"),
    hero: $("#hero"),
    chips: $("#chips"),
    form: $("#composer"),
    input: $("#input"),
    send: $("#sendBtn"),
    mic: $("#micBtn"),
    loc: $("#locBtn"),
    modeBanner: $("#modeBanner"),
    toast: $("#toast"),
    pickBanner: $("#pickBanner"),
    pickText: $("#pickText"),
    pickConfirm: $("#pickConfirm"),
    placesDialog: $("#placesDialog"),
    aboutDialog: $("#aboutDialog"),
    placeList: $("#placeList"),
    placeName: $("#placeName"),
    placeError: $("#placeError"),
    tripPanel: $("#tripPanel"),
    tripPickup: $("#tripPickup"),
    tripDropoff: $("#tripDropoff"),
    tripStats: $("#tripStats"),
    carRail: $("#carRail"),
    tripFoot: $("#tripFoot"),
  };

  // ------------------------------------------------------------------ i18n
  function t(key, vars) {
    let text = I18N[state.lang][key];
    if (text === undefined) text = I18N.ar[key];
    if (text === undefined) return key;
    if (vars && typeof text === "string") {
      Object.keys(vars).forEach((k) => {
        text = text.split("{" + k + "}").join(String(vars[k]));
      });
    }
    return text;
  }

  function applyLanguage() {
    const html = document.documentElement;
    html.lang = state.lang;
    html.dir = state.lang === "ar" ? "rtl" : "ltr";
    document.title = t("meta.title");
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      el.textContent = t(el.dataset.i18n);
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      el.placeholder = t(el.dataset.i18nPlaceholder);
    });
    document.querySelectorAll("[data-i18n-aria]").forEach((el) => {
      el.setAttribute("aria-label", t(el.dataset.i18nAria));
      if (el.tagName === "BUTTON") el.title = t(el.dataset.i18nAria);
    });
    renderChips();
    renderMessages();
    renderTripPanel();
    renderPlaceList();
    placeZoomControl();
    drawHere();
  }

  // ------------------------------------------------------------------- map
  const map = L.map("map", { zoomControl: false, attributionControl: true }).setView(JORDAN_CENTER, 8);
  let tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  map.attributionControl.setPrefix(false);
  const zoom = L.control.zoom();
  const tripLayer = L.layerGroup().addTo(map);
  const savedLayer = L.layerGroup().addTo(map);
  let hereMarker = null;
  let pickMarker = null;

  function placeZoomControl() {
    zoom.remove();
    zoom.setPosition(state.lang === "ar" ? "topleft" : "topright");
    zoom.addTo(map);
  }

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function pinIcon(className, html, size) {
    return L.divIcon({
      className: "",
      html: '<span class="pin ' + className + '">' + (html || "") + "</span>",
      iconSize: size,
      iconAnchor: [size[0] / 2, size[1] / 2],
    });
  }

  function carSvg(car) {
    return '<svg aria-hidden="true"><use href="#i-car-' + car + '"/></svg>';
  }

  function isMobile() {
    return window.matchMedia("(max-width: 760px)").matches;
  }

  // On desktop the chat panel covers one side of the map; these work on the part you can see.
  const PANEL_SHIFT = 230;

  function focusOn(latlng, zoom) {
    map.setView(latlng, zoom, { animate: false });
    if (!isMobile()) map.panBy([state.lang === "ar" ? PANEL_SHIFT : -PANEL_SHIFT, 0], { animate: false });
  }

  function visibleCenter() {
    const size = map.getSize();
    let x = size.x / 2;
    if (!isMobile()) x += state.lang === "ar" ? -PANEL_SHIFT : PANEL_SHIFT;
    return map.containerPointToLatLng([x, size.y / 2]);
  }

  function drawHere() {
    if (hereMarker) hereMarker.remove();
    hereMarker = null;
    if (!state.here) return;
    // Without a ride, your location is the pickup: say so on the map.
    const asPickup = !state.trip;
    hereMarker = L.marker([state.here.lat, state.here.lng], { icon: pinIcon("pin-here", "", [16, 16]), keyboard: false })
      .bindTooltip(t(asPickup ? "location.pickupLabel" : "location.you"), {
        className: "pin-label",
        direction: "top",
        offset: [0, -10],
        permanent: asPickup,
      })
      .addTo(map);
  }

  function fitPadding() {
    if (isMobile()) return { paddingTopLeft: [30, 30], paddingBottomRight: [30, 40] };
    const panel = 420 + 40;
    return state.lang === "ar"
      ? { paddingTopLeft: [60, 60], paddingBottomRight: [panel, 60] }
      : { paddingTopLeft: [panel, 60], paddingBottomRight: [60, 60] };
  }

  function drawTrip(trip, fit) {
    tripLayer.clearLayers();
    if (!trip) return;
    const points =
      trip.route.geometry && trip.route.geometry.length > 1
        ? trip.route.geometry
        : [[trip.start.lat, trip.start.lng], [trip.end.lat, trip.end.lng]];
    const dashed = trip.route.source === "estimate" ? "2 10" : null;
    L.polyline(points, { color: cssVar("--route-casing"), weight: 9, opacity: 0.9, lineCap: "round" }).addTo(tripLayer);
    L.polyline(points, { color: cssVar("--brand"), weight: 5, dashArray: dashed, lineCap: "round" }).addTo(tripLayer);
    L.marker([trip.start.lat, trip.start.lng], { icon: pinIcon("pin-pickup", "", [20, 20]), keyboard: false, zIndexOffset: 1000 })
      .bindTooltip(trip.start.name, { className: "pin-label", direction: "top", offset: [0, -12] })
      .addTo(tripLayer);
    L.marker([trip.end.lat, trip.end.lng], { icon: pinIcon("pin-dropoff", "", [18, 18]), keyboard: false, zIndexOffset: 900 })
      .bindTooltip(trip.end.name, { className: "pin-label", direction: "top", offset: [0, -12], permanent: true })
      .addTo(tripLayer);
    const bounds = points.slice();
    if (trip.status === "confirmed" && trip.driver) {
      const d = trip.driver;
      L.marker([d.lat, d.lng], { icon: pinIcon("pin-car", carSvg(trip.car_type), [34, 34]), keyboard: false })
        .bindTooltip(driverName(d), { className: "pin-label", direction: "top", offset: [0, -18] })
        .addTo(tripLayer);
      bounds.push([d.lat, d.lng]);
    }
    if (fit !== false) map.fitBounds(L.latLngBounds(bounds), Object.assign({ maxZoom: 15 }, fitPadding()));
  }

  function drawSaved() {
    savedLayer.clearLayers();
    (state.saved || []).forEach((place) => {
      L.marker([place.lat, place.lng], {
        icon: pinIcon("pin-saved", '<svg aria-hidden="true"><use href="#i-places"/></svg>', [24, 24]),
        keyboard: false,
      })
        .bindTooltip(place.name, { className: "pin-label", direction: "top", offset: [0, -14] })
        .on("click", () => {
          if (!state.picking) send(t("places.ride", { name: place.name }));
        })
        .addTo(savedLayer);
    });
  }

  // ------------------------------------------------------------ rendering
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function renderChips() {
    els.chips.replaceChildren();
    t("examples").forEach((example) => {
      const chip = el("button", "chip", example);
      chip.type = "button";
      chip.addEventListener("click", () => send(example));
      els.chips.appendChild(chip);
    });
  }

  function driverName(driver) {
    return state.lang === "en" && driver.name_en ? driver.name_en : driver.name;
  }

  function money(value) {
    return Number(value).toFixed(2);
  }

  // The trip panel: one fixed place for the route, the car choice and the booking state.
  function renderTripPanel() {
    const trip = state.trip;
    els.tripPanel.hidden = !trip;
    if (!trip) return;

    els.tripPickup.textContent = trip.start.name;
    els.tripDropoff.textContent = trip.end.name;
    els.tripStats.replaceChildren();
    const km = el("span", "stat");
    km.append(el("b", null, trip.route.distance_km.toFixed(1)), document.createTextNode(" " + t("trip.km")));
    const min = el("span", "stat");
    min.append(el("b", null, String(Math.round(trip.route.duration_min))), document.createTextNode(" " + t("trip.min")));
    els.tripStats.append(km, min);
    if (trip.route.source === "estimate") {
      const badge = el("span", "est-badge", t("trip.estimated"));
      badge.title = t("trip.estimatedTitle");
      els.tripStats.appendChild(badge);
    }

    els.carRail.replaceChildren();
    CARS.forEach((car) => {
      const selected = car === trip.car_type;
      const btn = el("button", "car-opt");
      btn.type = "button";
      btn.setAttribute("role", "radio");
      btn.setAttribute("aria-checked", String(selected));
      btn.title = t("trip.seats", { n: SEATS[car] });
      btn.innerHTML = carSvg(car);
      btn.appendChild(el("span", "car-name", t("cars." + car)));
      btn.appendChild(el("span", "car-price", money(trip.quotes[car])));
      btn.addEventListener("click", () => tripAction("car", { car_type: car }));
      els.carRail.appendChild(btn);
    });

    els.tripFoot.replaceChildren();
    if (trip.status === "confirmed" && trip.driver) {
      const d = trip.driver;
      const row = el("div", "driver-row");
      row.appendChild(el("span", "driver-avatar", driverName(d).replace(/^(أبو|Abu)\s*/, "").charAt(0)));
      const text = el("div", "driver-text");
      text.appendChild(el("span", "driver-name", driverName(d)));
      text.appendChild(el("span", "driver-car", d.car_model));
      row.appendChild(text);
      row.appendChild(el("span", "driver-eta", t("trip.eta", { n: d.eta_min })));
      const cancel = el("button", "text-btn cancel-btn", t("trip.cancel"));
      cancel.type = "button";
      cancel.addEventListener("click", () => tripAction("cancel"));
      els.tripFoot.append(row, cancel);
    } else {
      const confirm = el("button", "confirm-btn");
      confirm.type = "button";
      confirm.append(el("span", null, t("trip.confirm")), el("span", "confirm-price", money(trip.quotes[trip.car_type]) + " " + t("trip.currency")));
      confirm.addEventListener("click", () => tripAction("confirm"));
      els.tripFoot.appendChild(confirm);
    }
  }

  function messageNode(msg, isLast) {
    const wrap = el("div", "msg " + (msg.role === "user" ? "msg-user" : "msg-bot"));
    if (msg.error) wrap.classList.add("msg-error");
    const bubble = el("div", "bubble", msg.text);
    bubble.dir = "auto";
    wrap.appendChild(bubble);
    if (msg.pin && isLast) {
      // The place isn't on the map: let the user pin it (like Jeeny's "Set on Map").
      const pinBtn = el("button", "pin-btn", msg.pin.adjust ? t("pin.adjust") : t("pin.button", { name: msg.pin.label }));
      pinBtn.type = "button";
      pinBtn.addEventListener("click", () => startPicking({ kind: "trip", pin: msg.pin }));
      wrap.appendChild(pinBtn);
    }
    return wrap;
  }

  function renderMessages() {
    els.log.querySelectorAll(".msg").forEach((n) => n.remove());
    els.hero.hidden = state.messages.length > 0;
    const last = state.messages.length - 1;
    state.messages.forEach((m, i) => els.log.appendChild(messageNode(m, i === last)));
    scrollToEnd();
  }

  function addMessage(msg) {
    state.messages.push(msg);
    renderMessages(); // older "pin on map" buttons disappear once the conversation moves on
    persist();
  }

  function scrollToEnd() {
    requestAnimationFrame(() => {
      els.log.scrollTop = els.log.scrollHeight;
    });
  }

  function showTyping() {
    const wrap = el("div", "msg msg-bot");
    const bubble = el("div", "bubble typing");
    bubble.setAttribute("aria-label", t("thinking"));
    bubble.append(el("span"), el("span"), el("span"));
    wrap.appendChild(bubble);
    els.log.appendChild(wrap);
    scrollToEnd();
    return wrap;
  }

  let toastTimer = null;
  function toast(text) {
    els.toast.textContent = text;
    els.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      els.toast.hidden = true;
    }, 3800);
  }

  function setMode(mode) {
    els.modeBanner.hidden = mode !== "rules";
  }

  function setBusy(busy) {
    state.busy = busy;
    els.send.disabled = busy;
    els.tripPanel.classList.toggle("is-busy", busy);
  }

  function persist() {
    session.set("jc.history", state.history.slice(-MAX_HISTORY));
    session.set("jc.trip", state.trip);
    session.set("jc.messages", state.messages.slice(-40));
  }

  function setTrip(trip, fit) {
    state.trip = trip || null;
    renderTripPanel();
    if (state.trip) drawTrip(state.trip, fit);
    else tripLayer.clearLayers();
    drawHere();
    persist();
  }

  function remember(role, content) {
    state.history.push({ role: role, content: content.slice(0, 2000) });
    state.history = state.history.slice(-MAX_HISTORY);
  }

  // -------------------------------------------------------------- network
  async function postJSON(url, body) {
    const res = await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    if (res.status === 429) throw Object.assign(new Error("rate"), { kind: "error.rate" });
    if (!res.ok) throw Object.assign(new Error("server"), { kind: "error.server" });
    return res.json();
  }

  // The place the bot just couldn't find: the next message may say what's near it.
  function pendingPin() {
    const last = state.messages[state.messages.length - 1];
    return last && last.role === "bot" && last.pin && !last.pin.adjust ? last.pin : null;
  }

  function savedPayload() {
    return (state.saved || []).map((p) => ({ name: p.name, aliases: p.aliases || [], lat: p.lat, lng: p.lng }));
  }

  // opts.silent: send again a message that is already on screen (after the location arrived).
  async function send(text, opts) {
    const silent = !!(opts && opts.silent);
    text = (text || "").trim().slice(0, 300);
    if (!text || state.busy) return;
    const speak = state.speakNext;
    state.speakNext = false;
    const pending = silent ? opts.pending || null : pendingPin(); // read before the user's message becomes the last one
    state.retry = null;
    els.input.value = "";
    if (!silent) addMessage({ role: "user", text: text });
    setBusy(true);
    const typing = showTyping();
    const ask = () =>
      postJSON(API.chat, {
        message: text,
        lang: state.lang,
        history: state.history.slice(-MAX_HISTORY),
        trip: state.trip,
        saved_places: savedPayload(),
        current_location: state.here,
        pending_pin: pending,
      });
    try {
      let data = await ask();
      if (data.need_location && !state.here) {
        // Like the ride apps: ask the browser for your location (a popup the first time), then carry on.
        const here = await locateWithin(LOCATE_WAIT_MS);
        if (here) {
          setHere(here);
          data = await ask();
        } else {
          toast(t("location.denied"));
        }
      }
      typing.remove();
      if (!silent) remember("user", text);
      remember("assistant", data.reply);
      addMessage({ role: "bot", text: data.reply, pin: data.pin || null });
      if (data.need_location && !state.here) state.retry = { text: text, pending: pending }; // 📍 later resumes it
      const routeChanged = data.action === "new_trip" || data.action === "trip_modified";
      setTrip(data.trip, routeChanged || data.action === "trip_confirmed");
      setMode(data.mode);
      if (speak) speakText(data.reply);
    } catch (err) {
      typing.remove();
      addMessage({ role: "bot", text: t(err.kind || "error.network"), error: true });
    } finally {
      setBusy(false);
    }
  }

  // Trip panel buttons and "use my location": instant server actions, no LLM involved.
  async function tripAction(action, extra) {
    if ((!state.trip && action !== "pin") || state.busy) return null;
    if (action === "car" && extra && extra.car_type === state.trip.car_type) return null;
    setBusy(true);
    try {
      const data = await postJSON(
        API.trip,
        Object.assign({ trip: state.trip, action: action, lang: state.lang, current_location: state.here }, extra || {})
      );
      if (data.action === "message") {
        addMessage({ role: "bot", text: data.reply }); // e.g. a pinned point outside Jordan
        return null;
      }
      if (action !== "car") {
        remember("assistant", data.reply);
        addMessage({ role: "bot", text: data.reply });
      }
      setTrip(data.trip, action === "pickup_here" || action === "confirm" || action === "pin");
      return data;
    } catch (err) {
      toast(t(err.kind || "error.network"));
      return null;
    } finally {
      setBusy(false);
    }
  }

  // ----------------------------------------------------------- location
  const LOCATE_WAIT_MS = 20000; // don't wait forever if the permission popup is ignored

  function locateWithin(ms) {
    return Promise.race([locate().catch(() => null), new Promise((resolve) => setTimeout(() => resolve(null), ms))]);
  }

  function setHere(here) {
    state.here = here;
    drawHere();
    els.loc.classList.add("is-active");
  }

  function locate() {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) return reject(new Error("unsupported"));
      navigator.geolocation.getCurrentPosition(
        (pos) => resolve({ lat: +pos.coords.latitude.toFixed(6), lng: +pos.coords.longitude.toFixed(6) }),
        reject,
        { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 }
      );
    });
  }

  async function shareLocation() {
    let here;
    try {
      here = await locate();
    } catch (e) {
      toast(t("location.denied"));
      return;
    }
    setHere(here);
    const trip = state.trip;
    if (!trip && state.retry) {
      // The last request was waiting for your location: carry on with it.
      const retry = state.retry;
      state.retry = null;
      await send(retry.text, { silent: true, pending: retry.pending });
    } else if (!trip) {
      // No ride yet: your location becomes the pickup, and the next destination starts from here.
      focusOn([state.here.lat, state.here.lng], 14);
      say(t("location.pickup"));
    } else if (trip.start.source === "current_location" && near(trip.start, state.here)) {
      say(t("location.same"));
    } else {
      await tripAction("pickup_here"); // start the current ride from here, keep its destination
    }
  }

  // A bot line written by the app itself (it is also added to the AI's history).
  function say(text) {
    remember("assistant", text);
    addMessage({ role: "bot", text: text });
  }

  function near(a, b) {
    return Math.abs(a.lat - b.lat) < 0.0005 && Math.abs(a.lng - b.lng) < 0.0005; // about 50 m
  }

  // --------------------------------------------------------- saved places
  // Bump when the demo places change, so returning visitors get the new ones (their own places stay).
  const DEMO_SEED = 2;

  async function loadSavedPlaces() {
    const saved = Array.isArray(state.saved) ? state.saved : [];
    if (Array.isArray(state.saved) && local.get("jc.seed", 0) >= DEMO_SEED) return;
    try {
      const res = await fetch(API.places);
      const data = await res.json();
      data.demo_saved_places
        .filter((p) => p.lat !== null && p.lng !== null && !saved.some((s) => s.name === p.name))
        .forEach((p) => saved.push({ name: p.name, aliases: p.aliases || [], lat: p.lat, lng: p.lng, demo: true }));
      local.set("jc.seed", DEMO_SEED);
    } catch (e) {
      /* the app works without demo places */
    }
    state.saved = saved;
    local.set("jc.saved", state.saved);
  }

  function renderPlaceList() {
    els.placeList.replaceChildren();
    const places = state.saved || [];
    if (!places.length) {
      els.placeList.appendChild(el("li", "empty", t("places.empty")));
      return;
    }
    places.forEach((place, index) => {
      const li = el("li");
      li.appendChild(el("span", "place-name", place.name));
      if (place.demo) li.appendChild(el("span", "place-tag", t("places.demo")));
      const actions = el("div", "place-actions");
      const ride = el("button", "text-btn", t("places.ride", { name: place.name }));
      ride.type = "button";
      ride.setAttribute("aria-label", t("places.rideAria", { name: place.name }));
      ride.addEventListener("click", () => {
        els.placesDialog.close();
        send(t("places.ride", { name: place.name }));
      });
      const del = el("button", "icon-btn");
      del.type = "button";
      del.innerHTML = '<svg aria-hidden="true"><use href="#i-trash"/></svg>';
      del.setAttribute("aria-label", t("places.delete", { name: place.name }));
      del.title = t("places.delete", { name: place.name });
      del.addEventListener("click", () => {
        state.saved.splice(index, 1);
        local.set("jc.saved", state.saved);
        renderPlaceList();
        drawSaved();
      });
      actions.append(ride, del);
      li.appendChild(actions);
      els.placeList.appendChild(li);
    });
  }

  function validPlaceName() {
    const name = els.placeName.value.trim().slice(0, 40);
    let error = "";
    if (!name) error = t("places.nameFirst");
    else if ((state.saved || []).some((p) => p.name === name)) error = t("places.exists");
    els.placeError.textContent = error;
    els.placeError.hidden = !error;
    return error ? null : name;
  }

  function savePlace(name, latlng) {
    state.saved = (state.saved || []).filter((p) => p.name !== name); // re-pinning replaces it
    state.saved.push({ name: name, aliases: [], lat: +latlng.lat.toFixed(6), lng: +latlng.lng.toFixed(6) });
    local.set("jc.saved", state.saved);
    els.placeName.value = "";
    renderPlaceList();
    drawSaved();
    toast(t("places.saved", { name: name }));
  }

  // "Set on map", like ride apps: a pin you drag (or move with a tap), then an explicit confirm.
  // Outside this mode, clicking or dragging the map never drops a pin.
  function startPicking(target) {
    stopPicking();
    state.picking = target; // { kind: "saved", name } or { kind: "trip", pin }
    if (els.placesDialog.open) els.placesDialog.close();
    const name = target.kind === "trip" ? target.pin.label : target.name;
    els.pickText.textContent = t("places.pickHint", { name: name });
    els.pickBanner.hidden = false;
    $("#map").classList.add("picking");
    $(".app").classList.add("is-picking"); // on phones the map grows while you pick
    map.invalidateSize({ pan: false });

    // Start near what we know (the ride's pickup, or where you are), a little above it so both show.
    let anchor = state.here;
    if (target.kind === "trip") {
      const pin = target.pin;
      if (pin.adjust && state.trip) anchor = pin.role === "pickup" ? state.trip.start : state.trip.end; // start from what we found
      else anchor = pin.start || (state.trip && state.trip.start) || state.here;
    }
    let at = visibleCenter();
    if (anchor) {
      focusOn([anchor.lat, anchor.lng], 15);
      at = map.containerPointToLatLng(map.latLngToContainerPoint([anchor.lat, anchor.lng]).subtract([0, 70]));
    }
    pickMarker = L.marker(at, {
      icon: pinIcon("pin-pick", "", [26, 26]),
      draggable: true,
      autoPan: true,
      zIndexOffset: 2000,
      keyboard: false,
    })
      .bindTooltip(t("pin.drag"), { className: "pin-label", direction: "top", offset: [0, -16], permanent: true })
      .addTo(map);
    els.pickConfirm.focus();
  }

  function stopPicking() {
    const wasPicking = !!state.picking;
    state.picking = null;
    if (pickMarker) pickMarker.remove();
    pickMarker = null;
    els.pickBanner.hidden = true;
    $("#map").classList.remove("picking");
    $(".app").classList.remove("is-picking");
    if (wasPicking) map.invalidateSize({ pan: false });
  }

  async function confirmPick() {
    if (!state.picking || !pickMarker) return;
    const target = state.picking;
    const at = pickMarker.getLatLng();
    const point = { lat: +at.lat.toFixed(6), lng: +at.lng.toFixed(6) };
    stopPicking();
    if (target.kind !== "trip") return savePlace(target.name, point);
    const data = await tripAction("pin", { pin: target.pin, point: point });
    if (data && target.pin.save) savePlace(target.pin.label, point); // "الدار" is remembered for next time
  }

  map.on("click", (e) => {
    if (state.picking && pickMarker) pickMarker.setLatLng(e.latlng);
  });

  // ---------------------------------------------------------------- voice
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognizer = null;

  // Voice: keep listening until you pause for SILENCE_MS (a short breath doesn't send a half
  // sentence). Tap the mic again to send right away.
  const SILENCE_MS = 1500;
  const MAX_LISTEN_MS = 30000;

  // Some phones repeat the whole phrase in each result; keep the longest version of each.
  function joinResults(results) {
    const parts = [];
    for (let i = 0; i < results.length; i++) {
      const piece = results[i][0].transcript.trim();
      if (!piece) continue;
      const prev = parts[parts.length - 1];
      if (prev && piece.startsWith(prev)) parts[parts.length - 1] = piece;
      else if (!prev || !prev.endsWith(piece)) parts.push(piece);
    }
    return parts.join(" ").replace(/\s+/g, " ").trim();
  }

  function toggleMic() {
    if (!Recognition) return toast(t("mic.unsupported"));
    if (recognizer) return recognizer.stop(); // done talking: send now
    const rec = new Recognition();
    recognizer = rec;
    rec.lang = state.lang === "ar" ? "ar-JO" : "en-US";
    rec.interimResults = true;
    rec.continuous = true;
    rec.maxAlternatives = 1;
    let heard = "";
    let silence = null;
    const stop = () => {
      try {
        rec.stop();
      } catch (e) {
        /* already stopped */
      }
    };
    const cap = setTimeout(stop, MAX_LISTEN_MS);
    els.mic.classList.add("is-listening");
    els.mic.setAttribute("aria-label", t("composer.micStop"));
    els.input.placeholder = t("mic.listening");
    rec.onresult = (event) => {
      heard = joinResults(event.results);
      els.input.value = heard;
      clearTimeout(silence);
      silence = setTimeout(stop, SILENCE_MS); // send after a real pause, not between words
    };
    rec.onerror = (event) => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") toast(t("mic.denied"));
    };
    rec.onend = () => {
      clearTimeout(silence);
      clearTimeout(cap);
      els.mic.classList.remove("is-listening");
      els.mic.setAttribute("aria-label", t("composer.mic"));
      els.input.placeholder = t("composer.placeholder");
      recognizer = null;
      if (heard) {
        state.speakNext = true; // spoke to us -> we speak back
        send(heard);
      }
    };
    rec.start();
  }

  function speakText(text) {
    if (!("speechSynthesis" in window)) return;
    const clean = text.replace(/[\u{1F300}-\u{1FAFF}☀-➿]/gu, "").replace(/\n+/g, ". ");
    const utter = new SpeechSynthesisUtterance(clean);
    const arabic = /[؀-ۿ]/.test(clean);
    utter.lang = arabic ? "ar-SA" : "en-US";
    const voice = speechSynthesis.getVoices().find((v) => v.lang && v.lang.toLowerCase().startsWith(arabic ? "ar" : "en"));
    if (voice) utter.voice = voice;
    speechSynthesis.cancel();
    speechSynthesis.speak(utter);
  }

  // --------------------------------------------------------------- events
  els.form.addEventListener("submit", (e) => {
    e.preventDefault();
    send(els.input.value);
  });
  els.mic.addEventListener("click", toggleMic);
  els.loc.addEventListener("click", shareLocation);

  $("#newBtn").addEventListener("click", () => {
    state.history = [];
    state.messages = [];
    session.remove("jc.history");
    session.remove("jc.messages");
    setTrip(null);
    renderMessages();
    map.setView(state.here ? [state.here.lat, state.here.lng] : JORDAN_CENTER, state.here ? 13 : 8);
    els.input.focus();
  });

  $("#langBtn").addEventListener("click", () => {
    state.lang = state.lang === "ar" ? "en" : "ar";
    local.set("jc.lang", state.lang);
    applyLanguage();
    if (state.trip) drawTrip(state.trip);
  });

  $("#themeBtn").addEventListener("click", () => {
    state.theme = state.theme === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", state.theme);
    local.set("jc.theme", state.theme);
    if (state.trip) drawTrip(state.trip, false); // route colours come from CSS variables
  });

  $("#placesBtn").addEventListener("click", () => {
    renderPlaceList();
    els.placeError.hidden = true;
    els.placesDialog.showModal();
  });
  $("#aboutBtn").addEventListener("click", () => els.aboutDialog.showModal());

  document.querySelectorAll("dialog").forEach((dialog) => {
    dialog.addEventListener("click", (e) => {
      if (e.target === dialog || e.target.closest("[data-close]")) dialog.close();
    });
  });

  $("#placeForm").addEventListener("submit", (e) => e.preventDefault());
  $("#pickOnMapBtn").addEventListener("click", () => {
    const name = validPlaceName();
    if (name) startPicking({ kind: "saved", name: name });
  });
  $("#useGpsBtn").addEventListener("click", async () => {
    const name = validPlaceName();
    if (!name) return;
    try {
      savePlace(name, await locate());
    } catch (e) {
      toast(t("location.denied"));
    }
  });
  $("#pickCancel").addEventListener("click", stopPicking);
  els.pickConfirm.addEventListener("click", confirmPick);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.picking) stopPicking();
  });

  // ----------------------------------------------------------------- boot
  async function boot() {
    applyLanguage();
    if (state.trip) drawTrip(state.trip);
    try {
      const health = await (await fetch(API.health)).json();
      setMode(health.mode);
      if (health.tiles && health.tiles.url && health.tiles.url !== tiles._url) {
        tiles.remove();
        tiles = L.tileLayer(health.tiles.url, { maxZoom: 19, attribution: health.tiles.attribution }).addTo(map);
      }
    } catch (e) {
      /* health is informational only */
    }
    await loadSavedPlaces();
    drawSaved();
  }

  boot();
})();
