/* Ofis — izometrik sahna.
 * Haqiqiy 3D emas: har bir buyum uch yuzli quti (tepa, oldi-chap, oldi-o'ng) sifatida SVG'da chiziladi.
 * Shuning uchun videokartasiz, kuchsiz telefonda ham silliq ishlaydi; animatsiyalar faqat transform/opacity.
 */
"use strict";
window.Office = (function () {
  var U = 30;
  var CX = U * Math.cos(Math.PI / 6), CY = U * Math.sin(Math.PI / 6);
  var SW = 2.6, SD = 3.3, WALL = 1.15, GAPX = 3.4, GAPY = 3.8;
  var DEPT_ORDER = ["AI", "Backend", "Frontend", "Fullstack", "DevOps", "Dizayn", "Test (QA)"];
  var SKIN = ["#f1c7a5", "#e0ac86", "#c98e66"];
  var HAIR = ["#2b211c", "#3d2b22", "#5a3b28", "#1c1c22"];

  function P(x, y, z) { return [(x - y) * CX, (x + y) * CY - (z || 0) * U]; }
  function pts(a) { return a.map(function (p) { return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join(" "); }
  function poly(a, attrs) { return '<polygon points="' + pts(a) + '" ' + attrs + "/>"; }
  function fill(c, f) { return typeof c === "string" ? 'class="' + c + "-" + f + '"' : 'fill="' + c[f] + '"'; }
  function box(x, y, z, w, d, h, c) {
    var t = [P(x, y, z + h), P(x + w, y, z + h), P(x + w, y + d, z + h), P(x, y + d, z + h)];
    var l = [P(x, y + d, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x, y + d, z + h)];
    var r = [P(x + w, y, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x + w, y, z + h)];
    return poly(l, fill(c, "l")) + poly(r, fill(c, "r")) + poly(t, fill(c, "t"));
  }
  function shade(hex, k) {
    var n = parseInt(hex.slice(1), 16), rgb = [n >> 16, (n >> 8) & 255, n & 255];
    return "#" + rgb.map(function (v) {
      v = Math.round(k >= 0 ? v + (255 - v) * k : v * (1 + k));
      return Math.max(0, Math.min(255, v)).toString(16).padStart(2, "0");
    }).join("");
  }
  function tone(hex) { return { t: shade(hex, 0.2), l: hex, r: shade(hex, -0.24) }; }
  function hash(s) { var h = 0; for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return Math.abs(h); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function shortName(n) { var p = n.split(" "); return p.length > 1 ? p[0] + " " + p[1][0] + "." : n; }

  function plant(x, y) {
    var s = box(x, y, 0, 0.36, 0.36, 0.34, { t: "#d6b38f", l: "#c49c74", r: "#a9825c" });
    var c = P(x + 0.18, y + 0.18, 0.34);
    var leaves = [[-14, -26, -4, -8], [12, -24, 4, -8], [-4, -34, 0, -8], [-18, -14, -6, -4], [16, -12, 6, -4]];
    leaves.forEach(function (l, i) {
      s += '<path class="' + (i % 2 ? "leaf-d" : "leaf") + '" d="M' + c[0].toFixed(1) + "," + (c[1] - 2).toFixed(1) +
        " Q" + (c[0] + l[0]).toFixed(1) + "," + (c[1] + l[1] + 10).toFixed(1) + " " + (c[0] + l[0]).toFixed(1) + "," + (c[1] + l[1]).toFixed(1) +
        " Q" + (c[0] + l[2]).toFixed(1) + "," + (c[1] + l[3]).toFixed(1) + " " + c[0].toFixed(1) + "," + (c[1] - 2).toFixed(1) + 'Z"/>';
    });
    return s;
  }

  function roomShell(R) {
    var x = R.x, y = R.y, w = R.w, d = R.d, s = "";
    s += box(x, y, -0.4, w, d, 0.4, "slab");
    for (var i = 1; i < w; i += 1) { var a = P(x + i, y, 0), b = P(x + i, y + d, 0); s += '<line class="tile-line" x1="' + a[0].toFixed(1) + '" y1="' + a[1].toFixed(1) + '" x2="' + b[0].toFixed(1) + '" y2="' + b[1].toFixed(1) + '"/>'; }
    for (var j = 1; j < d; j += 1) { var c = P(x, y + j, 0), e = P(x + w, y + j, 0); s += '<line class="tile-line" x1="' + c[0].toFixed(1) + '" y1="' + c[1].toFixed(1) + '" x2="' + e[0].toFixed(1) + '" y2="' + e[1].toFixed(1) + '"/>'; }
    // orqa devorlar (oldi ochiq — ichi ko'rinsin)
    s += box(x, y, 0, w, 0.15, WALL, "wall");
    s += box(x, y + 0.15, 0, 0.15, d - 0.15, WALL, "wall");
    // derazalar chap devorda
    for (var k = 0.6; k + 1.0 < d - 0.3; k += 1.6) {
      s += poly([P(x + 0.151, y + k, 0.45), P(x + 0.151, y + k + 1.0, 0.45), P(x + 0.151, y + k + 1.0, 0.98), P(x + 0.151, y + k, 0.98)], 'class="glass"');
    }
    // bo'lim lavhasi orqa devorda
    var label = R.name + ", " + R.count;
    var sw = Math.min(w - 1.2, 0.6 + label.length * 0.27);
    var sx = x + 0.6;
    s += poly([P(sx, y + 0.151, 0.6), P(sx + sw, y + 0.151, 0.6), P(sx + sw, y + 0.151, 1.02), P(sx, y + 0.151, 1.02)], 'class="room-plate"');
    var o = P(sx + 0.22, y + 0.152, 0.7);
    s += '<text class="room-sign" transform="matrix(0.866 0.5 0 1 ' + o[0].toFixed(1) + " " + o[1].toFixed(1) + ')">' + esc(label) + "</text>";
    // pol yozuvi
    var f = P(x + 0.35, y + d - 0.25, 0);
    s += '<text class="room-sub" transform="matrix(0.866 0.5 -0.866 0.5 ' + f[0].toFixed(1) + " " + f[1].toFixed(1) + ')">' + esc(R.sub) + "</text>";
    s += plant(x + w - 0.6, y + 0.35);
    return s;
  }

  function station(ox, oy, p, idx) {
    var st = p.state, dc = "shirt", h = hash(p.name);
    var skin = SKIN[h % SKIN.length], hair = HAIR[(h >> 3) % HAIR.length], style = (h >> 5) % 3;
    var s = '<g class="ws" data-i="' + idx + '" tabindex="0" role="button" aria-label="' + esc(p.name + ", " + p.state_label) + '">';
    s += poly([P(ox - 0.15, oy - 0.1, 0.002), P(ox + 2.2, oy - 0.1, 0.002), P(ox + 2.2, oy + 2.3, 0.002), P(ox - 0.15, oy + 2.3, 0.002)], 'class="hl"');
    // stol
    s += box(ox + 0.06, oy + 0.06, 0, 0.07, 0.07, 0.72, "dark") + box(ox + 1.85, oy + 0.06, 0, 0.07, 0.07, 0.72, "dark");
    s += box(ox + 0.06, oy + 0.86, 0, 0.07, 0.07, 0.72, "dark") + box(ox + 1.85, oy + 0.86, 0, 0.07, 0.07, 0.72, "dark");
    s += box(ox, oy, 0.72, 2.0, 1.0, 0.07, "desk");
    // qog'oz uyumi = ochiq vazifalar
    var n = Math.min(p.open, 16);
    for (var i = 0; i < n; i++) s += box(ox + 0.1 + (i % 2) * 0.02, oy + 0.3, 0.79 + i * 0.042, 0.32, 0.4, 0.034, "paper");
    // monitor
    s += box(ox + 0.82, oy + 0.16, 0.79, 0.42, 0.24, 0.03, "dark");
    s += box(ox + 0.98, oy + 0.24, 0.82, 0.1, 0.07, 0.16, "dark");
    s += box(ox + 0.48, oy + 0.18, 0.96, 1.08, 0.08, 0.64, "dark");
    var sy = oy + 0.261, on = st !== "idle" && st !== "silent";
    s += poly([P(ox + 0.54, sy, 1.01), P(ox + 1.5, sy, 1.01), P(ox + 1.5, sy, 1.55), P(ox + 0.54, sy, 1.55)], 'class="' + (on ? "scr-on" : "scr-off") + '"');
    if (on) {
      [[1.45, 0.5], [1.37, 0.66], [1.29, 0.36], [1.21, 0.58], [1.13, 0.44]].forEach(function (l, k) {
        var a = P(ox + 0.62 + (k % 2) * 0.08, sy, l[0]), b = P(ox + 0.62 + (k % 2) * 0.08 + l[1] * ((h >> k) % 3 + 4) / 6, sy, l[0]);
        s += '<line class="code-line" x1="' + a[0].toFixed(1) + '" y1="' + a[1].toFixed(1) + '" x2="' + b[0].toFixed(1) + '" y2="' + b[1].toFixed(1) + '"/>';
      });
    }
    s += box(ox + 0.62, oy + 0.52, 0.79, 0.72, 0.2, 0.025, "key");
    if (st === "ok" || st === "idle") s += box(ox + 1.58, oy + 0.56, 0.79, 0.12, 0.12, 0.14, tone("#ffffff"));
    // kreslo
    s += box(ox + 0.72, oy + 1.36, 0.03, 0.52, 0.46, 0.04, "dark");
    s += box(ox + 0.95, oy + 1.55, 0.07, 0.06, 0.06, 0.34, "dark");
    s += box(ox + 0.68, oy + 1.24, 0.41, 0.6, 0.58, 0.09, "chair");
    // odam (orqasi bizga qaragan, monitorga qarab o'tiribdi). Sahna sokin: harakat va effektlar yo'q
    s += box(ox + 0.74, oy + 1.0, 0.5, 0.48, 0.5, 0.14, tone("#4a4a4f"));
    s += box(ox + 0.62, oy + 0.74, 0.86, 0.11, 0.6, 0.12, dc) + box(ox + 0.62, oy + 0.64, 0.84, 0.11, 0.1, 0.08, tone(skin));
    s += box(ox + 1.21, oy + 0.74, 0.86, 0.11, 0.6, 0.12, dc) + box(ox + 1.21, oy + 0.64, 0.84, 0.11, 0.1, 0.08, tone(skin));
    s += box(ox + 0.72, oy + 1.24, 0.5, 0.5, 0.36, 0.62, dc);
    s += box(ox + 0.68, oy + 1.74, 0.5, 0.6, 0.08, 0.4, "chair");
    s += box(ox + 0.91, oy + 1.37, 1.12, 0.12, 0.12, 0.05, tone(skin));
    s += box(ox + 0.78, oy + 1.26, 1.16, 0.38, 0.34, 0.36, { t: shade(hair, 0.12), l: hair, r: skin });
    s += box(ox + 0.76, oy + 1.24, 1.5, 0.42, 0.38, 0.07, tone(hair));
    if (style === 1) s += box(ox + 0.78, oy + 1.6, 0.9, 0.38, 0.06, 0.36, tone(hair));
    if (style === 2) s += box(ox + 0.9, oy + 1.38, 1.57, 0.15, 0.15, 0.12, tone(hair));
    s += "</g>";

    // ustki qatlam: ism va (faqat istisnoda) holat yorlig'i — oq yorliq, rangli nuqta
    var o = '<g class="ov" data-i="' + idx + '">', nm = P(ox + 1.05, oy + 2.4, 0);
    o += '<text class="nm" x="' + nm[0].toFixed(1) + '" y="' + nm[1].toFixed(1) + '">' + esc(shortName(p.name)) + "</text>";
    var hp = P(ox + 0.97, oy + 1.43, 1.98);
    var txt = st === "overloaded" ? p.open + " ta vazifa" : st === "silent" ? p.silent_days + " kun jim" : st === "idle" ? "Bo'sh" : "";
    if (txt) {
      var bw = 24 + txt.length * 5.3, x0 = hp[0] - bw / 2, y0 = hp[1] - 21;
      o += '<g class="pin ' + st + '"><rect x="' + x0.toFixed(1) + '" y="' + y0.toFixed(1) + '" width="' + bw.toFixed(1) + '" height="17" rx="3"/>' +
        '<circle cx="' + (x0 + 9).toFixed(1) + '" cy="' + (y0 + 8.5).toFixed(1) + '" r="3.2"/>' +
        '<text x="' + (x0 + 16).toFixed(1) + '" y="' + (y0 + 12.2).toFixed(1) + '">' + esc(txt) + "</text></g>";
    }
    o += "</g>";
    return { body: s, over: o, center: P(ox + 1.0, oy + 1.2, 1) };
  }

  function layout(people) {
    var groups = {};
    people.forEach(function (p) { (groups[p.department] = groups[p.department] || []).push(p); });
    var names = Object.keys(groups).sort(function (a, b) {
      var ia = DEPT_ORDER.indexOf(a), ib = DEPT_ORDER.indexOf(b);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b);
    });
    var rooms = [], gx = 0, gy = 0, rowD = 0, maxW = names.length > 3 ? 40 : 44;
    names.forEach(function (n) {
      var list = groups[n], cols = list.length <= 3 ? list.length : list.length <= 6 ? 3 : 4, rows = Math.ceil(list.length / cols);
      var w = 0.9 + cols * SW + 0.2, d = 1.0 + rows * SD + 0.3;
      if (gx > 0 && gx + w > maxW) { gx = 0; gy += rowD + GAPY; rowD = 0; }
      var open = list.reduce(function (a, p) { return a + p.open; }, 0);
      var done = list.reduce(function (a, p) { return a + p.done; }, 0);
      rooms.push({ name: n, x: gx, y: gy, w: w, d: d, cols: cols, people: list, count: list.length, color: list[0].color,
        sub: open + " ochiq vazifa, " + done + " bajarildi" });
      gx += w + GAPX; rowD = Math.max(rowD, d);
    });
    return rooms;
  }

  function create(el, opts) {
    var svgNS = "http://www.w3.org/2000/svg";
    var state = { vb: null, base: null, people: [], centers: [], drag: null, pointers: new Map(), anim: 0 };
    el.innerHTML = "";
    var svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("class", "scene");
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    el.appendChild(svg);

    function setVB(v) { state.vb = v; svg.setAttribute("viewBox", v.x.toFixed(1) + " " + v.y.toFixed(1) + " " + v.w.toFixed(1) + " " + v.h.toFixed(1)); }
    function toWorld(cx, cy, m) { var pt = svg.createSVGPoint(); pt.x = cx; pt.y = cy; return pt.matrixTransform(m || svg.getScreenCTM().inverse()); }
    function zoom(f, cx, cy) {
      var v = state.vb, b = state.base, p = toWorld(cx, cy);
      var w = Math.max(b.w * 0.22, Math.min(b.w * 1.6, v.w * f)), k = w / v.w;
      setVB({ x: p.x - (p.x - v.x) * k, y: p.y - (p.y - v.y) * k, w: w, h: v.h * k });
    }
    function animateTo(t, ms) {
      cancelAnimationFrame(state.anim);
      var s = Object.assign({}, state.vb), t0 = performance.now();
      (function step(now) {
        var k = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - k, 3);
        setVB({ x: s.x + (t.x - s.x) * e, y: s.y + (t.y - s.y) * e, w: s.w + (t.w - s.w) * e, h: s.h + (t.h - s.h) * e });
        if (k < 1) state.anim = requestAnimationFrame(step);
      })(t0);
    }

    function draw(people, dept) {
      state.people = people;
      var rooms = layout(people), body = "", over = "", idx = 0;
      state.centers = [];
      var xs = [], ys = [];
      rooms.forEach(function (R) {
        body += roomShell(R);
        [P(R.x, R.y, WALL + 0.6), P(R.x + R.w, R.y, 0), P(R.x, R.y + R.d, -0.4), P(R.x + R.w, R.y + R.d, -0.4)].forEach(function (p) { xs.push(p[0]); ys.push(p[1]); });
        R.people.forEach(function (p, k) {
          var c = k % R.cols, r = Math.floor(k / R.cols);
          var w = station(R.x + 0.8 + c * SW, R.y + 0.95 + r * SD, p, idx);
          body += w.body; over += w.over;
          state.centers[idx] = { name: p.name, c: w.center };
          idx++;
        });
      });
      svg.innerHTML = '<g class="world">' + body + '</g><g class="overlay">' + over + "</g>";
      var pad = 30, minX = Math.min.apply(null, xs) - pad, maxX = Math.max.apply(null, xs) + pad;
      var minY = Math.min.apply(null, ys) - pad - 20, maxY = Math.max.apply(null, ys) + pad;
      var base = { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
      var keep = state.base && state.vb && Math.abs(state.base.w - base.w) < 1 && Math.abs(state.base.h - base.h) < 1;
      state.base = base;
      if (!keep) setVB(Object.assign({}, base)); else setVB(state.vb);
      filter(dept);
      select(state.sel);
    }

    // filtr: bo'lim nomi yoki (xodim) => true/false funksiyasi; mos kelmaganlar xiralashadi
    function filter(f) {
      svg.querySelectorAll(".ws").forEach(function (g) {
        var p = state.people[+g.dataset.i];
        var keep = !f || (typeof f === "function" ? f(p) : p.department === f);
        g.classList.toggle("dim", !keep);
        var ov = svg.querySelector('.ov[data-i="' + g.dataset.i + '"]');
        if (ov) ov.classList.toggle("dim", !keep);
      });
    }

    function indexOf(name) {
      for (var i = 0; i < state.centers.length; i++) if (state.centers[i] && state.centers[i].name === name) return i;
      return -1;
    }

    // Tanlangan xodim: boshqalar xiralashadi, uning stoli va ismi ajralib turadi (yon oyna yopilguncha)
    function select(name) {
      state.sel = name || null;
      svg.querySelectorAll(".sel").forEach(function (g) { g.classList.remove("sel"); });
      var i = name ? indexOf(name) : -1;
      svg.classList.toggle("has-sel", i >= 0);
      if (i >= 0) svg.querySelectorAll('[data-i="' + i + '"]').forEach(function (g) { g.classList.add("sel"); });
    }

    // opt.right: o'ngdan yopib turgan yon oyna eni — xodim sahnaning ko'rinadigan qismi markaziga keltiriladi
    function focus(name, opt) {
      opt = opt || {};
      var i = indexOf(name), r = svg.getBoundingClientRect();
      if (i < 0 || !r.width || !r.height) return;
      var c = state.centers[i].c, w = state.base.w * (opt.zoom || 0.34), h = w * r.height / r.width;
      var visRight = Math.min(r.right, innerWidth - (opt.right || 0));
      var fx = Math.max(0.2, ((r.left + visRight) / 2 - r.left) / r.width);
      animateTo({ x: c[0] - w * fx, y: c[1] - h / 2, w: w, h: h }, 650);
      var g = svg.querySelector('.ws[data-i="' + i + '"]');
      if (g) { g.classList.add("focus"); setTimeout(function () { g.classList.remove("focus"); }, 2600); }
    }

    // sichqoncha / barmoq bilan boshqarish
    svg.addEventListener("wheel", function (e) { e.preventDefault(); zoom(e.deltaY > 0 ? 1.12 : 1 / 1.12, e.clientX, e.clientY); }, { passive: false });
    svg.addEventListener("pointerdown", function (e) {
      svg.setPointerCapture(e.pointerId);
      state.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (state.pointers.size === 1) {
        state.drag = { x: e.clientX, y: e.clientY, vb: Object.assign({}, state.vb), m: svg.getScreenCTM().inverse(), moved: false };
      } else if (state.pointers.size === 2) {
        var a = Array.from(state.pointers.values());
        state.pinch = { d: Math.hypot(a[0].x - a[1].x, a[0].y - a[1].y) };
        state.drag = null;
      }
    });
    svg.addEventListener("pointermove", function (e) {
      if (!state.pointers.has(e.pointerId)) {
        var g = e.target.closest && e.target.closest(".ws");
        if (opts.onHover) opts.onHover(g ? state.people[+g.dataset.i] : null, e);
        return;
      }
      state.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (state.pinch && state.pointers.size === 2) {
        var a = Array.from(state.pointers.values()), d = Math.hypot(a[0].x - a[1].x, a[0].y - a[1].y);
        zoom(state.pinch.d / d, (a[0].x + a[1].x) / 2, (a[0].y + a[1].y) / 2);
        state.pinch.d = d;
        return;
      }
      var s = state.drag;
      if (!s) return;
      if (Math.abs(e.clientX - s.x) + Math.abs(e.clientY - s.y) > 5) { s.moved = true; el.classList.add("grabbing"); if (opts.onHover) opts.onHover(null, e); }
      if (!s.moved) return;
      var p0 = toWorld(s.x, s.y, s.m), p1 = toWorld(e.clientX, e.clientY, s.m);
      setVB({ x: s.vb.x - (p1.x - p0.x), y: s.vb.y - (p1.y - p0.y), w: s.vb.w, h: s.vb.h });
    });
    function end(e) {
      var s = state.drag;
      state.pointers.delete(e.pointerId);
      if (state.pointers.size < 2) state.pinch = null;
      el.classList.remove("grabbing");
      if (s && !s.moved && e.type === "pointerup") {
        var g = e.target.closest && e.target.closest(".ws");
        if (g && opts.onPick) opts.onPick(state.people[+g.dataset.i]);
      }
      state.drag = null;
    }
    svg.addEventListener("pointerup", end);
    svg.addEventListener("pointercancel", end);
    svg.addEventListener("pointerleave", function (e) { if (opts.onHover && !state.drag) opts.onHover(null, e); });
    svg.addEventListener("keydown", function (e) {
      var g = e.target.closest && e.target.closest(".ws");
      if (g && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); opts.onPick(state.people[+g.dataset.i]); }
    });

    return {
      draw: draw, filter: filter, focus: focus, select: select,
      zoomIn: function () { var r = svg.getBoundingClientRect(); zoom(1 / 1.3, r.left + r.width / 2, r.top + r.height / 2); },
      zoomOut: function () { var r = svg.getBoundingClientRect(); zoom(1.3, r.left + r.width / 2, r.top + r.height / 2); },
      fit: function () { animateTo(Object.assign({}, state.base), 450); },
    };
  }

  return { create: create };
})();
