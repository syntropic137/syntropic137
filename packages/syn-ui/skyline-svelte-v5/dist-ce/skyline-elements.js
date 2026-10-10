typeof window < "u" && ((window.__svelte ??= {}).v ??= /* @__PURE__ */ new Set()).add("5");
const Eo = 1, To = 2, Gs = 4, zo = 8, Ao = 16, Mo = 1, Co = 4, $o = 8, No = 16, Xs = 1, Ro = 2, Js = "[", Wn = "[!", _s = "[?", Kn = "]", rr = {}, ue = /* @__PURE__ */ Symbol("uninitialized"), Lo = /* @__PURE__ */ Symbol("filename"), Zs = "http://www.w3.org/1999/xhtml", Oo = "http://www.w3.org/2000/svg", Qs = "@attach", ys = globalThis.process?.env?.NODE_ENV, m = ys && !ys.toLowerCase().startsWith("prod");
var Qr = Array.isArray, Do = Array.prototype.indexOf, kr = Array.prototype.includes, en = Array.from, Ur = Object.keys, ft = Object.defineProperty, zt = Object.getOwnPropertyDescriptor, Io = Object.getOwnPropertyDescriptors, Po = Object.prototype, Fo = Array.prototype, ea = Object.getPrototypeOf, gs = Object.isExtensible;
const We = () => {
};
function Ho(e) {
  for (var t = 0; t < e.length; t++)
    e[t]();
}
function ta() {
  var e, t, r = new Promise((n, s) => {
    e = n, t = s;
  });
  return { promise: r, resolve: e, reject: t };
}
const Ee = 2, nr = 4, tn = 8, Gn = 1 << 24, Qe = 16, st = 32, vt = 64, zn = 128, Xn = 256, rt = 512, he = 1024, oe = 2048, Ye = 4096, ze = 8192, Ae = 16384, Kt = 32768, Yr = 1 << 25, Mt = 65536, mr = 1 << 17, jo = 1 << 18, Gt = 1 << 19, Bo = 1 << 20, dt = 1 << 25, wr = 1 << 21, Bt = 1 << 22, At = 1 << 23, Ut = /* @__PURE__ */ Symbol("$state"), ra = /* @__PURE__ */ Symbol("component"), na = /* @__PURE__ */ Symbol("legacy props"), Uo = /* @__PURE__ */ Symbol(""), sa = /* @__PURE__ */ Symbol("proxy path"), aa = /* @__PURE__ */ Symbol("attributes"), An = /* @__PURE__ */ Symbol("class"), Mn = /* @__PURE__ */ Symbol("style"), Cn = /* @__PURE__ */ Symbol("text"), oa = /* @__PURE__ */ Symbol("form reset"), Yo = /* @__PURE__ */ Symbol("hmr anchor"), Tr = new class extends Error {
  name = "StaleReactionError";
  message = "The reaction that called `getAbortSignal()` was re-run or destroyed";
}(), rn = (
  // We gotta write it like this because after downleveling the pure comment may end up in the wrong location
  !!globalThis.document?.contentType && /* @__PURE__ */ globalThis.document.contentType.includes("xml")
), Vo = 1, zr = 3, Ar = 8;
var $t = "font-weight: bold", Nt = "font-weight: normal";
function qo(e) {
  m ? console.warn(`%c[svelte] await_reactivity_loss
%cDetected reactivity loss when reading \`${e}\`. This happens when state is read in an async function after an earlier \`await\`
https://svelte.dev/e/await_reactivity_loss`, $t, Nt) : console.warn("https://svelte.dev/e/await_reactivity_loss");
}
function Wo() {
  m ? console.warn(`%c[svelte] derived_inert
%cReading a derived belonging to a now-destroyed effect may result in stale values
https://svelte.dev/e/derived_inert`, $t, Nt) : console.warn("https://svelte.dev/e/derived_inert");
}
function Ko(e, t, r) {
  m ? console.warn(`%c[svelte] hydration_attribute_changed
%cThe \`${e}\` attribute on \`${t}\` changed its value between server and client renders. The client value, \`${r}\`, will be ignored in favour of the server value
https://svelte.dev/e/hydration_attribute_changed`, $t, Nt) : console.warn("https://svelte.dev/e/hydration_attribute_changed");
}
function nn(e) {
  m ? console.warn(
    `%c[svelte] hydration_mismatch
%cHydration failed because the initial UI does not match what was rendered on the server
https://svelte.dev/e/hydration_mismatch`,
    $t,
    Nt
  ) : console.warn("https://svelte.dev/e/hydration_mismatch");
}
function Go() {
  m ? console.warn(`%c[svelte] lifecycle_double_unmount
%cTried to unmount a component that was not mounted
https://svelte.dev/e/lifecycle_double_unmount`, $t, Nt) : console.warn("https://svelte.dev/e/lifecycle_double_unmount");
}
function Xo() {
  m ? console.warn("%c[svelte] select_multiple_invalid_value\n%cThe `value` property of a `<select multiple>` element should be an array, but it received a non-array value. The selection will be kept as is.\nhttps://svelte.dev/e/select_multiple_invalid_value", $t, Nt) : console.warn("https://svelte.dev/e/select_multiple_invalid_value");
}
function hn(e) {
  m ? console.warn(`%c[svelte] state_proxy_equality_mismatch
%cReactive \`$state(...)\` proxies and the values they proxy have different identities. Because of this, comparisons with \`${e}\` will produce unexpected results
https://svelte.dev/e/state_proxy_equality_mismatch`, $t, Nt) : console.warn("https://svelte.dev/e/state_proxy_equality_mismatch");
}
function Jo() {
  m ? console.warn("%c[svelte] svelte_boundary_reset_noop\n%cA `<svelte:boundary>` `reset` function only resets the boundary the first time it is called\nhttps://svelte.dev/e/svelte_boundary_reset_noop", $t, Nt) : console.warn("https://svelte.dev/e/svelte_boundary_reset_noop");
}
let D = !1;
function Fe(e) {
  D = e;
}
let j;
function pe(e) {
  if (e === null)
    throw nn(), rr;
  return j = e;
}
function sr() {
  return pe(/* @__PURE__ */ ht(j));
}
function S(e) {
  if (D) {
    if (/* @__PURE__ */ ht(j) !== null)
      throw nn(), rr;
    j = e;
  }
}
function Zo(e = 1) {
  if (D) {
    for (var t = e, r = j; t--; )
      r = /** @type {TemplateNode} */
      /* @__PURE__ */ ht(r);
    j = r;
  }
}
function Vr(e = !0) {
  for (var t = 0, r = j; ; ) {
    if (r.nodeType === Ar) {
      var n = (
        /** @type {Comment} */
        r.data
      );
      if (n === Kn) {
        if (t === 0) return r;
        t -= 1;
      } else (n === Js || n === Wn || // "[1", "[2", etc. for if blocks
      n[0] === "[" && !isNaN(Number(n.slice(1)))) && (t += 1);
    }
    var s = (
      /** @type {TemplateNode} */
      /* @__PURE__ */ ht(r)
    );
    e && r.remove(), r = s;
  }
}
function ia(e) {
  if (!e || e.nodeType !== Ar)
    throw nn(), rr;
  return (
    /** @type {Comment} */
    e.data
  );
}
function la(e) {
  return e === this.v;
}
function Qo(e, t) {
  return e != e ? t == t : e !== t || e !== null && typeof e == "object" || typeof e == "function";
}
function da(e) {
  return !Qo(e, this.v);
}
function ei(e) {
  if (m) {
    const t = new Error(`invariant_violation
An invariant violation occurred, meaning Svelte's internal assumptions were flawed. This is a bug in Svelte, not your app — please open an issue at https://github.com/sveltejs/svelte, citing the following message: "${e}"
https://svelte.dev/e/invariant_violation`);
    throw t.name = "Svelte error", t;
  } else
    throw new Error("https://svelte.dev/e/invariant_violation");
}
function ti() {
  if (m) {
    const e = new Error("async_derived_orphan\nCannot create a `$derived(...)` with an `await` expression outside of an effect tree\nhttps://svelte.dev/e/async_derived_orphan");
    throw e.name = "Svelte error", e;
  } else
    throw new Error("https://svelte.dev/e/async_derived_orphan");
}
function ri() {
  if (m) {
    const e = new Error(`derived_references_self
A derived value cannot reference itself recursively
https://svelte.dev/e/derived_references_self`);
    throw e.name = "Svelte error", e;
  } else
    throw new Error("https://svelte.dev/e/derived_references_self");
}
function ca(e, t, r) {
  if (m) {
    const n = new Error(`each_key_duplicate
${r ? `Keyed each block has duplicate key \`${r}\` at indexes ${e} and ${t}` : `Keyed each block has duplicate key at indexes ${e} and ${t}`}
https://svelte.dev/e/each_key_duplicate`);
    throw n.name = "Svelte error", n;
  } else
    throw new Error("https://svelte.dev/e/each_key_duplicate");
}
function ni(e, t, r) {
  if (m) {
    const n = new Error(`each_key_volatile
Keyed each block has key that is not idempotent — the key for item at index ${e} was \`${t}\` but is now \`${r}\`. Keys must be the same each time for a given item
https://svelte.dev/e/each_key_volatile`);
    throw n.name = "Svelte error", n;
  } else
    throw new Error("https://svelte.dev/e/each_key_volatile");
}
function si() {
  if (m) {
    const e = new Error(`effect_update_depth_exceeded
Maximum update depth exceeded. This typically indicates that an effect reads and writes the same piece of state
https://svelte.dev/e/effect_update_depth_exceeded`);
    throw e.name = "Svelte error", e;
  } else
    throw new Error("https://svelte.dev/e/effect_update_depth_exceeded");
}
function ai() {
  if (m) {
    const e = new Error(`hydration_failed
Failed to hydrate the application
https://svelte.dev/e/hydration_failed`);
    throw e.name = "Svelte error", e;
  } else
    throw new Error("https://svelte.dev/e/hydration_failed");
}
function oi() {
  if (m) {
    const e = new Error("invalid_snippet\nCould not `{@render}` snippet due to the expression being `null` or `undefined`. Consider using optional chaining `{@render snippet?.()}`\nhttps://svelte.dev/e/invalid_snippet");
    throw e.name = "Svelte error", e;
  } else
    throw new Error("https://svelte.dev/e/invalid_snippet");
}
function ii(e) {
  if (m) {
    const t = new Error(`props_invalid_value
Cannot do \`bind:${e}={undefined}\` when \`${e}\` has a fallback value
https://svelte.dev/e/props_invalid_value`);
    throw t.name = "Svelte error", t;
  } else
    throw new Error("https://svelte.dev/e/props_invalid_value");
}
function li(e) {
  if (m) {
    const t = new Error(`props_rest_readonly
Rest element properties of \`$props()\` such as \`${e}\` are readonly
https://svelte.dev/e/props_rest_readonly`);
    throw t.name = "Svelte error", t;
  } else
    throw new Error("https://svelte.dev/e/props_rest_readonly");
}
function di(e) {
  if (m) {
    const t = new Error(`rune_outside_svelte
The \`${e}\` rune is only available inside \`.svelte\` and \`.svelte.js/ts\` files
https://svelte.dev/e/rune_outside_svelte`);
    throw t.name = "Svelte error", t;
  } else
    throw new Error("https://svelte.dev/e/rune_outside_svelte");
}
function ci() {
  if (m) {
    const e = new Error("state_descriptors_fixed\nProperty descriptors defined on `$state` objects must contain `value` and always be `enumerable`, `configurable` and `writable`.\nhttps://svelte.dev/e/state_descriptors_fixed");
    throw e.name = "Svelte error", e;
  } else
    throw new Error("https://svelte.dev/e/state_descriptors_fixed");
}
function ui() {
  if (m) {
    const e = new Error("state_prototype_fixed\nCannot set prototype of `$state` object\nhttps://svelte.dev/e/state_prototype_fixed");
    throw e.name = "Svelte error", e;
  } else
    throw new Error("https://svelte.dev/e/state_prototype_fixed");
}
function fi() {
  if (m) {
    const e = new Error("state_unsafe_mutation\nUpdating state inside `$derived(...)`, `$inspect(...)` or a template expression is forbidden. If the value should not be reactive, declare it without `$state`\nhttps://svelte.dev/e/state_unsafe_mutation");
    throw e.name = "Svelte error", e;
  } else
    throw new Error("https://svelte.dev/e/state_unsafe_mutation");
}
function vi() {
  if (m) {
    const e = new Error("svelte_boundary_reset_onerror\nA `<svelte:boundary>` `reset` function cannot be called while an error is still being handled\nhttps://svelte.dev/e/svelte_boundary_reset_onerror");
    throw e.name = "Svelte error", e;
  } else
    throw new Error("https://svelte.dev/e/svelte_boundary_reset_onerror");
}
let hi = !1;
function Ze(e, t) {
  return e.label = t, ua(e.v, t), e;
}
function ua(e, t) {
  return e?.[sa]?.(t), e;
}
function fa(e) {
  const t = new Error(), r = _i();
  return r.length === 0 ? null : (r.unshift(`
`), ft(t, "stack", {
    value: r.join(`
`)
  }), ft(t, "name", {
    value: e
  }), /** @type {Error & { stack: string }} */
  t);
}
function _i() {
  const e = Error.stackTraceLimit;
  Error.stackTraceLimit = 1 / 0;
  const t = new Error().stack;
  if (Error.stackTraceLimit = e, !t) return [];
  const r = t.split(`
`), n = [];
  for (let s = 0; s < r.length; s++) {
    const a = r[s], o = a.replaceAll("\\", "/");
    if (a.trim() !== "Error") {
      if (a.includes("validate_each_keys"))
        return [];
      o.includes("svelte/src/internal") || o.includes("node_modules/.vite") || n.push(a);
    }
  }
  return n;
}
function yi(e, t) {
  if (!m)
    throw new Error("invariant(...) was not guarded by if (DEV)");
  e || ei(t);
}
let De = null;
function ar(e) {
  De = e;
}
let or = null;
function qr(e) {
  or = e;
}
let Mr = null;
function ps(e) {
  Mr = e;
}
function Ce(e, t = !1, r) {
  De = {
    p: De,
    i: !1,
    c: null,
    e: null,
    s: e,
    x: null,
    r: (
      /** @type {Effect} */
      Y
    ),
    l: null
  }, m && (De.function = r, Mr = r);
}
function $e(e) {
  var t = (
    /** @type {ComponentContext} */
    De
  ), r = t.e;
  if (r !== null) {
    t.e = null;
    for (var n of r)
      Oi(n);
  }
  return e !== void 0 && (t.x = e), t.i = !0, De = t.p, m && (Mr = De?.function ?? null), Jn(e);
}
function Jn(e = {}) {
  return ft(e, ra, { value: !0 }), e;
}
function va() {
  return !0;
}
let Ht = [];
function ha() {
  var e = Ht;
  Ht = [], Ho(e);
}
function et(e) {
  if (Ht.length === 0 && !yr) {
    var t = Ht;
    queueMicrotask(() => {
      t === Ht && ha();
    });
  }
  Ht.push(e);
}
function gi() {
  for (; Ht.length > 0; )
    ha();
}
const pi = -7169;
function ae(e, t) {
  e.f = e.f & pi | t;
}
function Zn(e) {
  (e.f & rt) !== 0 || e.deps === null ? ae(e, he) : ae(e, Ye);
}
function _a(e, t, r) {
  (e.f & oe) !== 0 ? t.add(e) : (e.f & Ye) !== 0 && r.add(e), ae(e, he);
}
function bi(e, t) {
  if (t) {
    const r = document.body;
    e.autofocus = !0, et(() => {
      document.activeElement === r && e.focus();
    });
  }
}
let bs = !1;
function ki() {
  bs || (bs = !0, document.addEventListener(
    "reset",
    (e) => {
      Promise.resolve().then(() => {
        if (!e.defaultPrevented)
          for (
            const t of
            /**@type {HTMLFormElement} */
            e.target.elements
          )
            t[oa]?.();
      });
    },
    // In the capture phase to guarantee we get noticed of it (no possibility of stopPropagation)
    { capture: !0 }
  ));
}
function Cr(e) {
  var t = Z, r = Y;
  Ke(null), nt(null);
  try {
    return e();
  } finally {
    Ke(t), nt(r);
  }
}
function ya(e, t, r, n) {
  const s = xr;
  var a = e.filter((_) => !_.settled), o = t.map(s);
  if (m && o.forEach((_, u) => {
    _.label = t[u].toString().replace("() => ", "").replaceAll("$.eager(() => ", "$state.eager(").replace(/\$\.get\((.+?)\)/g, (y, g) => g);
  }), r.length === 0 && a.length === 0) {
    n(o);
    return;
  }
  var i = (
    /** @type {Effect} */
    Y
  ), l = mi(), f = a.length === 1 ? a[0].promise : a.length > 1 ? Promise.all(a.map((_) => _.promise)) : null;
  function d(_) {
    if ((i.f & Ae) === 0) {
      l();
      try {
        n([...o, ..._]);
      } catch (u) {
        lt(u, i);
      }
      Wr();
    }
  }
  var v = ga();
  if (r.length === 0) {
    f.then(() => d([])).finally(v);
    return;
  }
  function h() {
    Promise.all(r.map((_) => /* @__PURE__ */ xi(_))).then(d).catch((_) => lt(_, i)).finally(v);
  }
  f ? f.then(() => {
    l(), h(), Wr();
  }) : h();
}
function mi() {
  var e = (
    /** @type {Effect} */
    Y
  ), t = Z, r = De, n = (
    /** @type {Batch} */
    V
  );
  if (m)
    var s = or;
  return function(o = !0) {
    nt(e), Ke(t), ar(r), o && (e.f & Ae) === 0 && (n?.activate(), n?.apply()), m && (pa(null), qr(s));
  };
}
function Wr(e = !0) {
  nt(null), Ke(null), ar(null), e && V?.deactivate(), m && (pa(null), qr(null));
}
function ga() {
  var e = (
    /** @type {Effect} */
    Y
  ), t = e.b, r = (
    /** @type {Batch} */
    V
  ), n = !!t?.is_rendered();
  return t?.update_pending_count(1, r), r.increment(n, e), () => {
    t?.update_pending_count(-1, r), r.decrement(n, e);
  };
}
let Ue = null;
function pa(e) {
  Ue = e;
}
const wi = /* @__PURE__ */ new Set();
// @__NO_SIDE_EFFECTS__
function xr(e) {
  var t = Ee | oe;
  return Y !== null && (Y.f |= Gt), {
    ctx: De,
    deps: null,
    effects: null,
    equals: la,
    f: t,
    fn: e,
    reactions: null,
    rv: 0,
    v: (
      /** @type {V} */
      ue
    ),
    wv: 0,
    parent: Y,
    ac: null
  };
}
const vr = /* @__PURE__ */ Symbol("obsolete");
// @__NO_SIDE_EFFECTS__
function xi(e, t, r) {
  let n = (
    /** @type {Effect | null} */
    Y
  );
  n === null && ti();
  var s = (
    /** @type {Promise<V>} */
    /** @type {unknown} */
    void 0
  ), a = qt(
    /** @type {V} */
    ue
  );
  m && (a.label = e.toString());
  var o = !Z, i = /* @__PURE__ */ new Set();
  return Pi(() => {
    var l = (
      /** @type {Effect} */
      Y
    );
    m && (Ue = { effect: l, effect_deps: /* @__PURE__ */ new Set(), warned: !1 });
    var f = ta();
    s = f.promise;
    try {
      Promise.resolve(e()).then(f.resolve, (_) => {
        _ !== Tr && f.reject(_);
      }).finally(Wr);
    } catch (_) {
      f.reject(_), Wr();
    }
    if (m) {
      if (Ue) {
        if (l.deps !== null)
          for (let _ = 0; _ < Ne; _ += 1)
            Ue.effect_deps.add(l.deps[_]);
        if (Se !== null)
          for (let _ = 0; _ < Se.length; _ += 1)
            Ue.effect_deps.add(Se[_]);
      }
      Ue = null;
    }
    var d = (
      /** @type {Batch} */
      V
    );
    if (o) {
      if ((l.f & Kt) !== 0)
        var v = ga();
      if (
        // boundary can be null if the async derived is inside an $effect.root not connected to the component render tree
        n.b?.is_rendered()
      )
        d.async_deriveds.get(l)?.reject(vr);
      else
        for (const _ of i.values())
          _.reject(vr);
      i.add(f), d.async_deriveds.set(l, f);
    }
    const h = (_, u = void 0) => {
      m && (Ue = null), v?.(), i.delete(f), u !== vr && (d.activate(), u ? (a.f |= At, lr(a, u)) : ((a.f & At) !== 0 && (a.f ^= At), lr(a, _)), d.deactivate());
    };
    f.promise.then(h, (_) => h(null, _ || "unknown"));
  }), on(() => {
    for (const l of i)
      l.reject(vr);
  }), m && (a.f |= Bt), new Promise((l) => {
    function f(d) {
      function v() {
        d === s ? l(a) : f(s);
      }
      d.then(v, v);
    }
    f(s);
  });
}
// @__NO_SIDE_EFFECTS__
function F(e) {
  const t = /* @__PURE__ */ xr(e);
  return Fa(t), t;
}
// @__NO_SIDE_EFFECTS__
function ba(e) {
  const t = /* @__PURE__ */ xr(e);
  return t.equals = da, t;
}
function ks(e) {
  var t = e.effects;
  if (t !== null) {
    e.effects = null;
    for (var r = 0; r < t.length; r += 1)
      be(
        /** @type {Effect} */
        t[r]
      );
  }
}
let _n = [];
function Qn(e) {
  var t, r = Y, n = e.parent;
  if (!Ct && n !== null && e.v !== ue && // if it was never evaluated before, it's guaranteed to fail downstream, so we try to execute instead
  (n.f & (Ae | ze)) !== 0)
    return Wo(), e.v;
  if (nt(n), m) {
    let s = ir;
    xs(/* @__PURE__ */ new Set());
    try {
      kr.call(_n, e) && ri(), _n.push(e), ks(e), t = On(e);
    } finally {
      nt(r), xs(s), _n.pop();
    }
  } else
    try {
      ks(e), t = On(e);
    } finally {
      nt(r);
    }
  return t;
}
function ka(e) {
  var t = Qn(e);
  if (!e.equals(t) && (e.wv = ja(), (!V?.is_fork || e.deps === null) && (V !== null ? (V.capture(e, t, !0), Kr?.capture(e, t, !0)) : e.v = t, e.deps === null))) {
    ae(e, he);
    return;
  }
  Ct || (tt !== null ? (ss() || V?.is_fork) && tt.set(e, t) : Zn(e));
}
function Si(e) {
  if (e.effects !== null)
    for (const t of e.effects)
      (t.teardown || t.ac) && (t.teardown?.(), t.ac !== null && Cr(() => {
        t.ac.abort(Tr), t.ac = null;
      }), t.fn !== null && (t.teardown = We), Sr(t, 0), os(t));
}
function ma(e) {
  if (e.effects !== null)
    for (const t of e.effects)
      t.teardown && t.fn !== null && dr(t);
}
let yn = null, tr = null, V = null, Kr = null, tt = null, $n = null, yr = !1, gn = !1, gr = null, Hr = null;
var ms = 0, pn = /* @__PURE__ */ new Set();
let Ei = 1;
class mt {
  id = Ei++;
  /** True as soon as `#process` was called */
  #e = !1;
  linked = !0;
  /** @type {Batch | null} */
  #t = null;
  /** @type {Batch | null} */
  #r = null;
  /** @type {Map<Effect, ReturnType<typeof deferred<any>>>} */
  async_deriveds = /* @__PURE__ */ new Map();
  /**
   * The current values of any signals that are updated in this batch.
   * Tuple format: [value, is_derived] (note: is_derived is false for deriveds, too, if they were overridden via assignment)
   * They keys of this map are identical to `this.#previous`
   * @type {Map<Value, [any, boolean]>}
   */
  current = /* @__PURE__ */ new Map();
  /**
   * The values of any signals (sources and deriveds) that are updated in this batch _before_ those updates took place.
   * They keys of this map are identical to `this.#current`
   * @type {Map<Value, any>}
   */
  previous = /* @__PURE__ */ new Map();
  /**
   * When the batch is committed (and the DOM is updated), we need to remove old branches
   * and append new ones by calling the functions added inside (if/each/key/etc) blocks
   * @type {Set<(batch: Batch) => void>}
   */
  #i = /* @__PURE__ */ new Set();
  /**
   * If a fork is discarded, we need to destroy any effects that are no longer needed
   * @type {Set<(batch: Batch) => void>}
   */
  #s = /* @__PURE__ */ new Set();
  /**
   * The number of async effects that are currently in flight
   */
  #o = 0;
  /**
   * Async effects that are currently in flight, _not_ inside a pending boundary
   * @type {Map<Effect, number>}
   */
  #n = /* @__PURE__ */ new Map();
  /**
   * A deferred that resolves when the batch is committed, used with `settled()`
   * TODO replace with Promise.withResolvers once supported widely enough
   * @type {{ promise: Promise<void>, resolve: (value?: any) => void, reject: (reason: unknown) => void } | null}
   */
  #l = null;
  /**
   * Effects that were scheduled in this batch but not yet 'resolved' into the
   * root effects that need to be flushed. Resolving — the upwards traversal that
   * marks the path to each effect on the shared effect tree (see #resolve) — is
   * deferred until the batch is processed, so that the markers are created and
   * consumed within a single traversal. Scheduling into other batches (which can
   * happen concurrently, e.g. while a batch is committed) can therefore never
   * observe (and be confused by) this batch's markers.
   * May contain duplicates — deduplication happens during resolving
   * @type {Effect[]}
   */
  #a = [];
  /**
   * Effects created while this batch was active.
   * @type {Effect[]}
   */
  #h = [];
  /**
   * Deferred effects (which run after async work has completed) that are DIRTY
   * @type {Set<Effect>}
   */
  #c = /* @__PURE__ */ new Set();
  /**
   * Deferred effects that are MAYBE_DIRTY
   * @type {Set<Effect>}
   */
  #u = /* @__PURE__ */ new Set();
  /**
   * A map of branches that still exist, but will be destroyed when this batch
   * is committed — we skip over these during `process`.
   * The value contains child effects that were dirty/maybe_dirty before being reset,
   * so they can be rescheduled if the branch survives.
   * @type {Map<Effect, { d: Effect[], m: Effect[] }>}
   */
  #f = /* @__PURE__ */ new Map();
  /**
   * Inverse of #skipped_branches which we need to tell prior batches to unskip them when committing
   * @type {Set<Effect>}
   */
  #y = /* @__PURE__ */ new Set();
  is_fork = !1;
  #d = !1;
  constructor() {
    tr === null ? yn = tr = this : (tr.#r = this, this.#t = tr), tr = this;
  }
  #b() {
    if (this.is_fork) return !0;
    for (const n of this.#n.keys()) {
      for (var t = n, r = !1; t.parent !== null; ) {
        if (this.#f.has(t)) {
          r = !0;
          break;
        }
        t = t.parent;
      }
      if (!r)
        return !0;
    }
    return !1;
  }
  /**
   * Add an effect to the #skipped_branches map and reset its children
   * @param {Effect} effect
   */
  skip_effect(t) {
    this.#f.has(t) || this.#f.set(t, { d: [], m: [] }), this.#y.delete(t);
  }
  /**
   * Remove an effect from the #skipped_branches map and reschedule
   * any tracked dirty/maybe_dirty child effects
   * @param {Effect} effect
   * @param {(e: Effect) => void} callback
   */
  unskip_effect(t, r = (n) => this.schedule(n)) {
    var n = this.#f.get(t);
    if (n) {
      this.#f.delete(t);
      for (var s of n.d)
        ae(s, oe), r(s);
      for (s of n.m)
        ae(s, Ye), r(s);
    }
    this.#y.add(t);
  }
  /**
   * Convert the effects that were scheduled in this batch into the root effects
   * that need to be traversed, marking the path to each effect (by clearing the
   * `CLEAN` flag on ancestor branches) so that the traversal can find them.
   * This happens right before traversal rather than at scheduling time, so that
   * the markers left on the (shared) effect tree are created and consumed within
   * a single traversal — scheduling into other batches can never observe them
   * @returns {Effect[]}
   */
  #k() {
    var t = [];
    for (const a of this.#a)
      if (!((a.f & Ae) !== 0 || (a.f & (oe | Ye)) === 0)) {
        for (var r = a, n = !1; r.parent !== null; ) {
          r = r.parent;
          var s = r.f;
          if ((s & (vt | st)) !== 0) {
            if ((s & he) === 0) {
              n = !0;
              break;
            }
            r.f ^= he;
          }
        }
        n || t.push(r);
      }
    return this.#a = [], t;
  }
  #g() {
    if (this.#e = !0, m)
      for (const i of this.current.keys())
        pn.add(i);
    for (const i of this.#c)
      this.#u.delete(i), ae(i, oe), this.schedule(i);
    for (const i of this.#u)
      ae(i, Ye), this.schedule(i);
    this.apply();
    for (var t = gr = [], r = [], n = Hr = []; this.#a.length > 0; ) {
      ms++ > 1e3 && (this.#_(), Ti());
      for (const i of this.#k())
        try {
          this.#p(i, t, r);
        } catch (l) {
          throw Sa(i), this.#b() || this.discard(), l;
        }
    }
    if (V = null, n.length > 0) {
      var s = mt.ensure();
      for (const i of n)
        s.schedule(i);
    }
    if (gr = null, Hr = null, this.#b()) {
      this.#v(r), this.#v(t);
      for (const [i, l] of this.#f)
        xa(i, l);
      n.length > 0 && /** @type {unknown} */
      V.#g();
      return;
    }
    const a = this.#x();
    if (a) {
      this.#v(r), this.#v(t), a.#m(this);
      return;
    }
    this.#c.clear(), this.#u.clear();
    for (const i of this.#i) i(this);
    this.#i.clear(), Kr = this, ws(r), ws(t), Kr = null, this.#l?.resolve();
    var o = (
      /** @type {Batch | null} */
      /** @type {unknown} */
      V
    );
    if (this.#o === 0 && (this.#a.length === 0 || o !== null) && this.#_(), this.#a.length > 0)
      if (o !== null) {
        for (const i of this.#a)
          o.#a.push(i);
        this.#a = [];
      } else
        o = this;
    o !== null && (ct.clear(), o.#g());
  }
  /**
   * Traverse the effect tree, executing effects or stashing
   * them for later execution as appropriate
   * @param {Effect} root
   * @param {Effect[]} effects
   * @param {Effect[]} render_effects
   */
  #p(t, r, n) {
    t.f ^= he;
    for (var s = t.first; s !== null; ) {
      var a = s.f, o = (a & (st | vt)) !== 0, i = o && (a & he) !== 0, l = i || (a & ze) !== 0 || this.#f.has(s);
      if (!l && s.fn !== null) {
        o ? s.f ^= he : (a & nr) !== 0 ? r.push(s) : Rr(s) && ((a & Qe) !== 0 && this.#u.add(s), dr(s));
        var f = s.first;
        if (f !== null) {
          s = f;
          continue;
        }
      }
      for (; s !== null; ) {
        var d = s.next;
        if (d !== null) {
          s = d;
          break;
        }
        s = s.parent;
      }
    }
  }
  #x() {
    for (var t = this.#t; t !== null; ) {
      if (!t.is_fork) {
        for (const [r, [, n]] of this.current)
          if (t.current.has(r) && !n)
            return t;
      }
      t = t.#t;
    }
    return null;
  }
  /**
   * @param {Batch} batch
   */
  #m(t) {
    for (const [n, s] of t.current)
      !this.previous.has(n) && t.previous.has(n) && this.previous.set(n, t.previous.get(n)), this.current.set(n, s);
    for (const [n, s] of t.async_deriveds) {
      const a = this.async_deriveds.get(n);
      a && s.promise.then(a.resolve).catch(a.reject);
    }
    t.async_deriveds.clear(), this.transfer_effects(t.#c, t.#u);
    const r = (n) => {
      var s = n.reactions;
      if (s !== null && !((n.f & Ee) !== 0 && (n.f & (oe | Ye)) === 0))
        for (const i of s) {
          var a = i.f;
          if ((a & Ee) !== 0)
            r(
              /** @type {Derived} */
              i
            );
          else {
            var o = (
              /** @type {Effect} */
              i
            );
            a & (Bt | Qe) && !this.async_deriveds.has(o) && (this.#u.delete(o), ae(o, oe), this.schedule(o));
          }
        }
    };
    for (const n of this.current.keys())
      r(n);
    this.oncommit(() => t.discard()), t.#_(), V = this, this.#g();
  }
  /**
   * @param {Effect[]} effects
   */
  #v(t) {
    for (var r = 0; r < t.length; r += 1)
      _a(t[r], this.#c, this.#u);
  }
  /**
   * Associate a change to a given source with the current
   * batch, noting its previous and current values
   * @param {Value} source
   * @param {any} value
   * @param {boolean} [is_derived]
   */
  capture(t, r, n = !1) {
    t.v !== ue && !this.previous.has(t) && this.previous.set(t, t.v), (t.f & At) === 0 && (this.current.set(t, [r, n]), tt?.set(t, r)), this.is_fork || (t.v = r);
  }
  activate() {
    V = this;
  }
  deactivate() {
    V = null, tt = null;
  }
  flush() {
    try {
      m && pn.clear(), gn = !0, V = this, this.#g();
    } finally {
      if (ms = 0, $n = null, gr = null, Hr = null, gn = !1, V = null, tt = null, ct.clear(), m)
        for (const t of pn)
          t.updated = null;
    }
  }
  discard() {
    for (const t of this.#s) t(this);
    this.#s.clear();
    for (const t of this.async_deriveds.values())
      t.reject(vr);
    this.#_(), this.#l?.resolve();
  }
  /**
   * @param {Effect} effect
   */
  register_created_effect(t) {
    this.#h.push(t);
  }
  #w() {
    for (let v = yn; v !== null; v = v.#r) {
      var t = v.id < this.id, r = [];
      for (const [h, [_, u]] of this.current) {
        if (v.current.has(h)) {
          var n = (
            /** @type {[any, boolean]} */
            v.current.get(h)[0]
          );
          if (t && _ !== n)
            v.current.set(h, [_, u]);
          else
            continue;
        }
        r.push(h);
      }
      if (t)
        for (const [h, _] of this.async_deriveds) {
          const u = v.async_deriveds.get(h);
          u && _.promise.then(u.resolve).catch(u.reject);
        }
      var s = [...v.current.keys()].filter(
        (h) => !/** @type {[any, boolean]} */
        v.current.get(h)[1]
      );
      if (!(!v.#e || s.length === 0)) {
        var a = s.filter((h) => !this.current.has(h));
        if (a.length === 0)
          t && v.discard();
        else if (r.length > 0) {
          if (m && !v.#d && yi(v.#a.length === 0, "Batch has scheduled effects"), t)
            for (const h of this.#y)
              v.unskip_effect(h, (_) => {
                (_.f & (Qe | Bt)) !== 0 ? v.schedule(_) : v.#v([_]);
              });
          v.activate();
          var o = /* @__PURE__ */ new Set(), i = /* @__PURE__ */ new Map();
          for (var l of r)
            wa(l, a, o, i);
          i = /* @__PURE__ */ new Map();
          var f = [...v.current].filter(([h, _]) => {
            const u = this.current.get(h);
            return u ? u[0] !== _[0] || u[1] !== _[1] : !0;
          }).map(([h]) => h);
          if (f.length > 0)
            for (const h of this.#h)
              (h.f & (Ae | ze | mr)) === 0 && es(h, f, i) && ((h.f & (Bt | Qe)) !== 0 ? (ae(h, oe), v.schedule(h)) : v.#c.add(h));
          if (v.#a.length > 0 && !v.#d) {
            v.apply();
            for (var d of v.#k())
              v.#p(d, [], []);
          }
          v.deactivate();
        }
      }
    }
  }
  /**
   * @param {boolean} blocking
   * @param {Effect} effect
   */
  increment(t, r) {
    if (this.#o += 1, t) {
      let n = this.#n.get(r) ?? 0;
      this.#n.set(r, n + 1);
    }
  }
  /**
   * @param {boolean} blocking
   * @param {Effect} effect
   */
  decrement(t, r) {
    if (this.#o -= 1, t) {
      let n = this.#n.get(r) ?? 0;
      n === 1 ? this.#n.delete(r) : this.#n.set(r, n - 1);
    }
    this.#d || (this.#d = !0, et(() => {
      this.#d = !1, this.linked && this.flush();
    }));
  }
  /**
   * @param {Set<Effect>} dirty_effects
   * @param {Set<Effect>} maybe_dirty_effects
   */
  transfer_effects(t, r) {
    for (const n of t)
      this.#c.add(n);
    for (const n of r)
      this.#u.add(n);
    t.clear(), r.clear();
  }
  /** @param {(batch: Batch) => void} fn */
  oncommit(t) {
    this.#i.add(t);
  }
  /** @param {(batch: Batch) => void} fn */
  ondiscard(t) {
    this.#s.add(t);
  }
  settled() {
    return (this.#l ??= ta()).promise;
  }
  static ensure() {
    if (V === null) {
      const t = V = new mt();
      !gn && !yr && et(() => {
        t.#e || t.flush();
      });
    }
    return V;
  }
  apply() {
    {
      tt = null;
      return;
    }
  }
  /**
   *
   * @param {Effect} effect
   */
  schedule(t) {
    if ($n = t, t.b?.is_pending && (t.f & (nr | tn | Gn)) !== 0 && (t.f & Kt) === 0) {
      t.b.defer_effect(t);
      return;
    }
    this.#a.push(t);
  }
  #_() {
    if (this.linked) {
      var t = this.#t, r = this.#r;
      t === null ? yn = r : t.#r = r, r === null ? tr = t : r.#t = t, this.linked = !1;
    }
  }
}
function I(e) {
  var t = yr;
  yr = !0;
  try {
    for (var r; ; ) {
      if (gi(), V === null)
        return (
          /** @type {T} */
          r
        );
      V.flush();
    }
  } finally {
    yr = t;
  }
}
function Ti() {
  if (m) {
    var e = /* @__PURE__ */ new Map();
    for (
      const r of
      /** @type {Batch} */
      V.current.keys()
    )
      for (const [n, s] of r.updated ?? []) {
        var t = e.get(n);
        t || (t = { error: s.error, count: 0 }, e.set(n, t)), t.count += s.count;
      }
    for (const r of e.values())
      r.error && console.error(r.error);
  }
  try {
    si();
  } catch (r) {
    m && ft(r, "stack", { value: "" }), lt(r, $n);
  }
}
let pt = null;
function ws(e) {
  var t = e.length;
  if (t !== 0) {
    for (var r = 0; r < t; ) {
      var n = e[r++];
      if ((n.f & (Ae | ze)) === 0 && Rr(n) && (pt = /* @__PURE__ */ new Set(), dr(n), n.deps === null && n.first === null && n.nodes === null && n.teardown === null && n.ac === null && Da(n), pt?.size > 0)) {
        ct.clear();
        for (const s of pt) {
          if ((s.f & (Ae | ze)) !== 0) continue;
          const a = [s];
          let o = s.parent;
          for (; o !== null; )
            pt.has(o) && (pt.delete(o), a.push(o)), o = o.parent;
          for (let i = a.length - 1; i >= 0; i--) {
            const l = a[i];
            (l.f & (Ae | ze)) === 0 && dr(l);
          }
        }
        pt.clear();
      }
    }
    pt = null;
  }
}
function wa(e, t, r, n) {
  if (!r.has(e) && (r.add(e), e.reactions !== null))
    for (const s of e.reactions) {
      const a = s.f;
      (a & Ee) !== 0 ? wa(
        /** @type {Derived} */
        s,
        t,
        r,
        n
      ) : (a & (Bt | Qe)) !== 0 && (a & oe) === 0 && es(s, t, n) && (ae(s, oe), ts(
        /** @type {Effect} */
        s
      ));
    }
}
function es(e, t, r) {
  const n = r.get(e);
  if (n !== void 0) return n;
  if (e.deps !== null)
    for (const s of e.deps) {
      if (kr.call(t, s))
        return !0;
      if ((s.f & Ee) !== 0 && es(
        /** @type {Derived} */
        s,
        t,
        r
      ))
        return r.set(
          /** @type {Derived} */
          s,
          !0
        ), !0;
    }
  return r.set(e, !1), !1;
}
function ts(e) {
  V.schedule(e);
}
function xa(e, t) {
  if (!((e.f & st) !== 0 && (e.f & he) !== 0)) {
    (e.f & oe) !== 0 ? t.d.push(e) : (e.f & Ye) !== 0 && t.m.push(e), ae(e, he);
    for (var r = e.first; r !== null; )
      xa(r, t), r = r.next;
  }
}
function Sa(e) {
  ae(e, he);
  for (var t = e.first; t !== null; )
    Sa(t), t = t.next;
}
let ir = /* @__PURE__ */ new Set();
const ct = /* @__PURE__ */ new Map();
function xs(e) {
  ir = e;
}
let rs = !1;
function zi() {
  rs = !0;
}
function qt(e, t) {
  var r = {
    f: 0,
    // TODO ideally we could skip this altogether, but it causes type errors
    v: e,
    reactions: null,
    equals: la,
    rv: 0,
    wv: 0
  };
  return r;
}
// @__NO_SIDE_EFFECTS__
function xe(e, t) {
  const r = qt(e);
  return Fa(r), r;
}
// @__NO_SIDE_EFFECTS__
function Ea(e, t = !1, r = !0) {
  const n = qt(e);
  return t || (n.equals = da), n;
}
function ve(e, t, r = !1) {
  Z !== null && // since we are untracking the function inside `$inspect.with` we need to add this check
  // to ensure we error if state is set inside an inspect effect
  (!Ve || (Z.f & mr) !== 0) && va() && (Z.f & (Ee | Qe | Bt | mr)) !== 0 && (ut === null || !ut.has(e)) && fi();
  let n = r ? Et(t) : t;
  return m && ua(
    n,
    /** @type {string} */
    e.label
  ), lr(e, n, Hr);
}
var Ft = null, Nn = 0;
function lr(e, t, r = null) {
  if (!e.equals(t)) {
    Ct ? ct.set(e, t) : ct.has(e) || ct.set(e, e.v);
    var n = mt.ensure();
    if (n.capture(e, t), m) {
      if (Y !== null) {
        e.updated ??= /* @__PURE__ */ new Map();
        const s = (e.updated.get("")?.count ?? 0) + 1;
        if (e.updated.set("", { error: (
          /** @type {any} */
          null
        ), count: s }), s > 5) {
          const a = fa("updated at");
          if (a !== null) {
            let o = e.updated.get(a.stack);
            o || (o = { error: a, count: 0 }, e.updated.set(a.stack, o)), o.count++;
          }
        }
      }
      Y !== null && (e.set_during_effect = !0);
    }
    if ((e.f & Ee) !== 0) {
      const s = (
        /** @type {Derived} */
        e
      );
      (e.f & oe) !== 0 && Qn(s), tt === null && Zn(s);
    }
    e.wv = ja(), Ft = null, Nn = 0, za(e, oe, r), Ft = null, Y !== null && (Y.f & he) !== 0 && (Y.f & (st | vt)) === 0 && (Be === null ? ji([e]) : Be.push(e)), !n.is_fork && ir.size > 0 && !rs && Ta();
  }
  return t;
}
function Ta() {
  rs = !1;
  for (const e of ir) {
    (e.f & he) !== 0 && ae(e, Ye);
    let t;
    try {
      t = Rr(e);
    } catch {
      t = !0;
    }
    t && dr(e);
  }
  ir.clear();
}
function pr(e) {
  ve(e, e.v + 1);
}
function za(e, t, r) {
  var n = e.reactions;
  if (n !== null) {
    var s = n.length;
    if (Nn += s, Nn > 1e5 && Ft === null && (Ft = /* @__PURE__ */ new Set()), Ft !== null) {
      if (Ft.has(e)) return;
      Ft.add(e);
    }
    for (var a = 0; a < s; a++) {
      var o = n[a], i = o.f, l = (i & oe) === 0;
      if (l && ae(o, t), (i & mr) !== 0)
        ir.add(
          /** @type {Effect} */
          o
        );
      else if ((i & Ee) !== 0) {
        var f = (
          /** @type {Derived} */
          o
        );
        tt?.delete(f), za(f, Ye, r);
      } else if (l) {
        var d = (
          /** @type {Effect} */
          o
        );
        (i & Qe) !== 0 && pt !== null && pt.add(d), r !== null ? r.push(d) : ts(d);
      }
    }
  }
}
const Ai = /^[a-zA-Z_$][a-zA-Z_$0-9]*$/;
function Et(e) {
  if (typeof e != "object" || e === null || Ut in e || ra in e)
    return e;
  const t = ea(e);
  if (t !== Po && t !== Fo)
    return e;
  var r = /* @__PURE__ */ new Map(), n = Qr(e), s = /* @__PURE__ */ xe(0), a = Vt, o = (d) => {
    if (Vt === a)
      return d();
    var v = Z, h = Vt;
    Ke(null), Ts(a);
    var _ = d();
    return Ke(v), Ts(h), _;
  };
  n && (r.set("length", /* @__PURE__ */ xe(
    /** @type {any[]} */
    e.length
  )), m && (e = /** @type {any} */
  Ci(
    /** @type {any[]} */
    e
  )));
  var i = "";
  let l = !1;
  function f(d) {
    if (!l) {
      l = !0, i = d, Ze(s, `${i} version`);
      for (const [v, h] of r)
        Ze(h, Pt(i, v));
      l = !1;
    }
  }
  return new Proxy(
    /** @type {any} */
    e,
    {
      defineProperty(d, v, h) {
        (!("value" in h) || h.configurable === !1 || h.enumerable === !1 || h.writable === !1) && ci();
        var _ = r.get(v);
        return _ === void 0 ? o(() => {
          var u = /* @__PURE__ */ xe(h.value);
          return r.set(v, u), m && typeof v == "string" && Ze(u, Pt(i, v)), u;
        }) : ve(_, h.value, !0), !0;
      },
      deleteProperty(d, v) {
        var h = r.get(v);
        if (h === void 0) {
          if (v in d) {
            const _ = o(() => /* @__PURE__ */ xe(ue));
            r.set(v, _), pr(s), m && Ze(_, Pt(i, v));
          }
        } else
          ve(h, ue), pr(s);
        return !0;
      },
      get(d, v, h) {
        if (v === Ut)
          return e;
        if (m && v === sa)
          return f;
        var _ = r.get(v), u = v in d;
        if (_ === void 0 && (!u || zt(d, v)?.writable) && (_ = o(() => {
          var g = Et(u ? d[v] : ue), b = /* @__PURE__ */ xe(g);
          return m && Ze(b, Pt(i, v)), b;
        }), r.set(v, _)), _ !== void 0) {
          var y = c(_);
          return y === ue ? void 0 : y;
        }
        return Reflect.get(d, v, h);
      },
      getOwnPropertyDescriptor(d, v) {
        this.has?.(d, v);
        var h = Reflect.getOwnPropertyDescriptor(d, v), _ = r.get(v);
        if (_ !== void 0) {
          var u = c(_);
          if (u === ue)
            return;
          if (h && "value" in h)
            h.value = u;
          else
            return {
              enumerable: !0,
              configurable: !0,
              value: u,
              writable: !0
            };
        }
        return h;
      },
      has(d, v) {
        if (v === Ut)
          return !0;
        var h = r.get(v), _ = h !== void 0 && h.v !== ue || Reflect.has(d, v);
        if (h !== void 0 || Y !== null && (!_ || zt(d, v)?.writable)) {
          h === void 0 && (h = o(() => {
            var y = _ ? Et(d[v]) : ue, g = /* @__PURE__ */ xe(y);
            return m && Ze(g, Pt(i, v)), g;
          }), r.set(v, h));
          var u = c(h);
          if (u === ue)
            return !1;
        }
        return _;
      },
      set(d, v, h, _) {
        var u = r.get(v), y = v in d;
        if (n && v === "length")
          for (var g = h; g < /** @type {Source<number>} */
          u.v; g += 1) {
            var b = r.get(g + "");
            b !== void 0 ? ve(b, ue) : g in d && (b = o(() => /* @__PURE__ */ xe(ue)), r.set(g + "", b), m && Ze(b, Pt(i, g)));
          }
        if (u === void 0)
          (!y || zt(d, v)?.writable) && (u = o(() => /* @__PURE__ */ xe(void 0)), m && Ze(u, Pt(i, v)), ve(u, Et(h)), r.set(v, u));
        else {
          y = u.v !== ue;
          var A = o(() => Et(h));
          ve(u, A);
        }
        var R = Reflect.getOwnPropertyDescriptor(d, v);
        if (R?.set && R.set.call(_, h), !y) {
          if (n && typeof v == "string") {
            var w = (
              /** @type {Source<number>} */
              r.get("length")
            ), q = Number(v);
            Number.isInteger(q) && q >= w.v && ve(w, q + 1);
          }
          pr(s);
        }
        return !0;
      },
      ownKeys(d) {
        c(s);
        var v = Reflect.ownKeys(d).filter((u) => {
          var y = r.get(u);
          return y === void 0 || y.v !== ue;
        });
        for (var [h, _] of r)
          _.v !== ue && !(h in d) && v.push(h);
        return v;
      },
      setPrototypeOf() {
        ui();
      }
    }
  );
}
function Pt(e, t) {
  return typeof t == "symbol" ? `${e}[Symbol(${t.description ?? ""})]` : Ai.test(t) ? `${e}.${t}` : /^\d+$/.test(t) ? `${e}[${t}]` : `${e}['${t}']`;
}
function br(e) {
  try {
    if (e !== null && typeof e == "object" && Ut in e)
      return e[Ut];
  } catch {
  }
  return e;
}
function Aa(e, t) {
  return Object.is(br(e), br(t));
}
const Mi = /* @__PURE__ */ new Set([
  "copyWithin",
  "fill",
  "pop",
  "push",
  "reverse",
  "shift",
  "sort",
  "splice",
  "unshift"
]);
function Ci(e) {
  return new Proxy(e, {
    get(t, r, n) {
      var s = Reflect.get(t, r, n);
      return Mi.has(
        /** @type {string} */
        r
      ) ? function(...a) {
        zi();
        var o = s.apply(this, a);
        return Ta(), o;
      } : s;
    }
  });
}
function $i() {
  const e = Array.prototype, t = Array.__svelte_cleanup;
  t && t();
  const { indexOf: r, lastIndexOf: n, includes: s } = e;
  e.indexOf = function(a, o) {
    const i = r.call(this, a, o);
    if (i === -1) {
      for (let l = o ?? 0; l < this.length; l += 1)
        if (br(this[l]) === a) {
          hn("array.indexOf(...)");
          break;
        }
    }
    return i;
  }, e.lastIndexOf = function(a, o) {
    const i = n.call(this, a, o ?? this.length - 1);
    if (i === -1) {
      for (let l = 0; l <= (o ?? this.length - 1); l += 1)
        if (br(this[l]) === a) {
          hn("array.lastIndexOf(...)");
          break;
        }
    }
    return i;
  }, e.includes = function(a, o) {
    const i = s.call(this, a, o);
    if (!i) {
      for (let l = 0; l < this.length; l += 1)
        if (br(this[l]) === a) {
          hn("array.includes(...)");
          break;
        }
    }
    return i;
  }, Array.__svelte_cleanup = () => {
    e.indexOf = r, e.lastIndexOf = n, e.includes = s;
  };
}
var Ss, ns, Ma, Ca;
function Rn() {
  if (Ss === void 0) {
    Ss = window, ns = /Firefox/.test(navigator.userAgent);
    var e = Element.prototype, t = Node.prototype, r = Text.prototype;
    Ma = zt(t, "firstChild").get, Ca = zt(t, "nextSibling").get, gs(e) && (e[An] = void 0, e[aa] = null, e[Mn] = void 0, e.__e = void 0), gs(r) && (r[Cn] = void 0), m && (e.__svelte_meta = null, $i());
  }
}
function Me(e = "") {
  return document.createTextNode(e);
}
// @__NO_SIDE_EFFECTS__
function Oe(e) {
  return (
    /** @type {TemplateNode | null} */
    Ma.call(e)
  );
}
// @__NO_SIDE_EFFECTS__
function ht(e) {
  return (
    /** @type {TemplateNode | null} */
    Ca.call(e)
  );
}
function z(e, t) {
  if (!D)
    return /* @__PURE__ */ Oe(e);
  var r = /* @__PURE__ */ Oe(j);
  if (r === null)
    r = j.appendChild(Me());
  else if (t && r.nodeType !== zr) {
    var n = Me();
    return r?.before(n), pe(n), n;
  }
  return t && an(
    /** @type {Text} */
    r
  ), pe(r), r;
}
function re(e, t = !1) {
  if (!D) {
    var r = /* @__PURE__ */ Oe(e);
    return r instanceof Comment && r.data === "" ? /* @__PURE__ */ ht(r) : r;
  }
  if (t) {
    if (j?.nodeType !== zr) {
      var n = Me();
      return j?.before(n), pe(n), n;
    }
    an(
      /** @type {Text} */
      j
    );
  }
  return j;
}
function ne(e, t = !1) {
  if (!D)
    return /* @__PURE__ */ Oe(e);
  var r = z(e, t);
  return S(e), r;
}
function E(e, t = 1, r = !1) {
  let n = D ? j : e;
  for (var s; t--; )
    s = n, n = /** @type {TemplateNode} */
    /* @__PURE__ */ ht(n);
  if (!D)
    return n;
  if (r) {
    if (n?.nodeType !== zr) {
      var a = Me();
      return n === null ? s?.after(a) : n.before(a), pe(a), a;
    }
    an(
      /** @type {Text} */
      n
    );
  }
  return pe(n), n;
}
function $a(e) {
  e.textContent = "";
}
function Na() {
  return !1;
}
function sn(e, t, r) {
  return t == null || t === Zs ? (
    /** @type {T extends keyof HTMLElementTagNameMap ? HTMLElementTagNameMap[T] : Element} */
    r ? document.createElement(e, { is: r }) : document.createElement(e)
  ) : (
    /** @type {T extends keyof HTMLElementTagNameMap ? HTMLElementTagNameMap[T] : Element} */
    r ? document.createElementNS(t, e, { is: r }) : document.createElementNS(t, e)
  );
}
function an(e) {
  if (
    /** @type {string} */
    e.nodeValue.length < 65536
  )
    return;
  let t = e.nextSibling;
  for (; t !== null && t.nodeType === zr; )
    t.remove(), e.nodeValue += /** @type {string} */
    t.nodeValue, t = e.nextSibling;
}
const Ln = /* @__PURE__ */ new WeakMap();
function Ni(e) {
  var t = Y;
  if (t === null)
    return Z.f |= At, e;
  if (m && e instanceof Error && !Ln.has(e) && Ln.set(e, Ri(e, t)), (t.f & Kt) === 0 && (t.f & nr) === 0)
    throw m && !t.parent && e instanceof Error && Ra(e), e;
  lt(e, t);
}
function lt(e, t) {
  if (!(t !== null && (t.f & Ae) !== 0)) {
    for (; t !== null; ) {
      if ((t.f & zn) !== 0 && (t.f & (Ae | Yr)) === 0) {
        if ((t.f & Kt) === 0)
          throw e;
        try {
          t.b.error(e);
          return;
        } catch (r) {
          e = r;
        }
      }
      t = t.parent;
    }
    throw m && e instanceof Error && Ra(e), e;
  }
}
function Ri(e, t) {
  const r = zt(e, "message");
  if (!(r && !r.configurable)) {
    for (var n = ns ? "  " : "	", s = `
${n}in ${t.fn?.name || "<unknown>"}`, a = t.ctx; a !== null; )
      s += `
${n}in ${a.function?.[Lo].split("/").pop()}`, a = a.p;
    return {
      message: e.message + `
${s}
`,
      stack: e.stack?.split(`
`).filter((o) => !o.includes("svelte/src/internal")).join(`
`)
    };
  }
}
function Ra(e) {
  const t = Ln.get(e);
  t && (ft(e, "message", {
    value: t.message
  }), ft(e, "stack", {
    value: t.stack
  }));
}
function Li(e, t) {
  var r = t.last;
  r === null ? t.last = t.first = e : (r.next = e, e.prev = r, t.last = e);
}
function at(e, t) {
  var r = Y;
  if (m)
    for (; r !== null && (r.f & mr) !== 0; )
      r = r.parent;
  r !== null && (r.f & ze) !== 0 && (e |= ze);
  var n = {
    ctx: De,
    deps: null,
    nodes: null,
    f: e | oe | rt,
    first: null,
    fn: t,
    last: null,
    next: null,
    parent: r,
    b: r && r.b,
    prev: null,
    teardown: null,
    wv: 0,
    ac: null
  };
  m && (n.component_function = Mr), V?.register_created_effect(n);
  var s = n;
  if ((e & nr) !== 0)
    gr !== null ? gr.push(n) : mt.ensure().schedule(n);
  else if (t !== null) {
    try {
      dr(n);
    } catch (o) {
      throw be(n), o;
    }
    s.deps === null && s.teardown === null && s.nodes === null && s.first === s.last && // either `null`, or a singular child
    (s.f & Gt) === 0 && (s = s.first, (e & Qe) !== 0 && (e & Mt) !== 0 && s !== null && (s.f |= Mt));
  }
  if (s !== null && (s.parent = r, r !== null && Li(s, r), Z !== null && (Z.f & Ee) !== 0 && (e & vt) === 0)) {
    var a = (
      /** @type {Derived} */
      Z
    );
    (a.effects ??= []).push(s);
  }
  return n;
}
function ss() {
  return Z !== null && !Ve;
}
function on(e) {
  const t = at(tn, null);
  return ae(t, he), t.teardown = e, t;
}
function Oi(e) {
  return at(nr | Bo, e);
}
function Di(e) {
  mt.ensure();
  const t = at(vt | Gt, e);
  return () => {
    be(t);
  };
}
function Ii(e) {
  mt.ensure();
  const t = at(vt | Gt, e);
  return (r = {}) => new Promise((n) => {
    r.outro ? Yt(t, () => {
      be(t), n(void 0);
    }) : (be(t), n(void 0));
  });
}
function $r(e) {
  return at(nr, e);
}
function Pi(e) {
  return at(Bt | Gt, e);
}
function as(e, t = 0) {
  return at(tn | t, e);
}
function W(e, t = [], r = [], n = []) {
  ya(n, t, r, (s) => {
    at(tn, () => {
      e(...s.map(c));
    });
  });
}
function Nr(e, t = 0) {
  var r = at(Qe | t, e);
  return m && (r.dev_stack = or), r;
}
function La(e, t = 0) {
  var r = at(Gn | t, e);
  return m && (r.dev_stack = or), r;
}
function Re(e) {
  return at(st | Gt, e);
}
function Oa(e) {
  var t = e.teardown;
  if (t !== null) {
    const r = Ct, n = Z;
    Es(!0), Ke(null);
    try {
      t.call(null);
    } catch (s) {
      lt(s, e.parent);
    } finally {
      Es(r), Ke(n);
    }
  }
}
function os(e, t = !1) {
  var r = e.first;
  for (e.first = e.last = null; r !== null; ) {
    const s = r.ac;
    s !== null && Cr(() => {
      s.abort(Tr);
    });
    var n = r.next;
    (r.f & vt) !== 0 ? r.parent = null : be(r, t), r = n;
  }
}
function Fi(e) {
  for (var t = e.first; t !== null; ) {
    var r = t.next;
    (t.f & st) === 0 && be(t), t = r;
  }
}
function be(e, t = !0) {
  var r = !1;
  (t || (e.f & jo) !== 0) && e.nodes !== null && e.nodes.end !== null && (Hi(
    e.nodes.start,
    /** @type {TemplateNode} */
    e.nodes.end
  ), r = !0), e.f |= Yr, os(e, t && !r), Sr(e, 0);
  var n = e.nodes && e.nodes.t;
  if (n !== null)
    for (const a of n)
      a.stop();
  Oa(e), e.f ^= Yr, e.f |= Ae;
  var s = e.parent;
  s !== null && s.first !== null && Da(e), m && (e.component_function = null), e.next = e.prev = e.teardown = e.ctx = e.deps = e.fn = e.nodes = e.ac = e.b = null;
}
function Hi(e, t) {
  for (; e !== null; ) {
    var r = e === t ? null : /* @__PURE__ */ ht(e);
    e.remove(), e = r;
  }
}
function Da(e) {
  var t = e.parent, r = e.prev, n = e.next;
  r !== null && (r.next = n), n !== null && (n.prev = r), t !== null && (t.first === e && (t.first = n), t.last === e && (t.last = r));
}
function Yt(e, t, r = !0) {
  var n = [];
  e.f |= Xn, Ia(e, n, !0);
  var s = () => {
    r && be(e), t && t();
  }, a = n.length;
  if (a > 0) {
    var o = () => --a || s();
    for (var i of n)
      i.out(o);
  } else
    s();
}
function Ia(e, t, r) {
  if ((e.f & ze) === 0) {
    e.f ^= ze;
    var n = e.nodes && e.nodes.t;
    if (n !== null)
      for (const i of n)
        (i.is_global || r) && t.push(i);
    for (var s = e.first; s !== null; ) {
      var a = s.next;
      if ((s.f & vt) === 0) {
        var o = (s.f & Mt) !== 0 || // If this is a branch effect without a block effect parent,
        // it means the parent block effect was pruned. In that case,
        // transparency information was transferred to the branch effect.
        (s.f & st) !== 0 && (e.f & Qe) !== 0;
        Ia(s, t, o ? r : !1);
      }
      s = a;
    }
  }
}
function Gr(e) {
  e.f &= ~Xn, Pa(e, !0);
}
function Pa(e, t) {
  if ((e.f & Xn) === 0 && (e.f & ze) !== 0) {
    e.f ^= ze, (e.f & he) === 0 && (ae(e, oe), mt.ensure().schedule(e));
    for (var r = e.first; r !== null; ) {
      var n = r.next, s = (r.f & Mt) !== 0 || (r.f & st) !== 0;
      Pa(r, s ? t : !1), r = n;
    }
    var a = e.nodes && e.nodes.t;
    if (a !== null)
      for (const o of a)
        (o.is_global || t) && o.in();
  }
}
function is(e, t) {
  if (e.nodes)
    for (var r = e.nodes.start, n = e.nodes.end; r !== null; ) {
      var s = r === n ? null : /* @__PURE__ */ ht(r);
      t.append(r), r = s;
    }
}
let jr = !1, Ct = !1;
function Es(e) {
  Ct = e;
}
let Z = null, Ve = !1;
function Ke(e) {
  Z = e;
}
let Y = null;
function nt(e) {
  Y = e;
}
let ut = null;
function Fa(e) {
  Z !== null && ((Z.f & wr) !== 0 || (Z.f & Ee) !== 0) && (ut ??= /* @__PURE__ */ new Set()).add(e);
}
let Se = null, Ne = 0, Be = null;
function ji(e) {
  Be = e;
}
let Ha = 1, jt = 0, Vt = jt;
function Ts(e) {
  Vt = e;
}
function ja() {
  return ++Ha;
}
function Rr(e) {
  var t = e.f;
  if ((t & oe) !== 0)
    return !0;
  if ((t & Ye) !== 0) {
    for (var r = (
      /** @type {Value[]} */
      e.deps
    ), n = r.length, s = 0; s < n; s++) {
      var a = r[s];
      if (Rr(
        /** @type {Derived} */
        a
      ) && ka(
        /** @type {Derived} */
        a
      ), a.wv > e.wv)
        return !0;
    }
    (t & rt) !== 0 && // During time traveling we don't want to reset the status so that
    // traversal of the graph in the other batches still happens
    tt === null && ae(e, he);
  }
  return !1;
}
function Ba(e, t, r = !0) {
  var n = e.reactions;
  if (n !== null && !(ut !== null && ut.has(e)))
    for (var s = 0; s < n.length; s++) {
      var a = n[s];
      (a.f & Ee) !== 0 ? Ba(
        /** @type {Derived} */
        a,
        t,
        !1
      ) : t === a && (r ? ae(a, oe) : (a.f & he) !== 0 && ae(a, Ye), ts(
        /** @type {Effect} */
        a
      ));
    }
}
function On(e) {
  var t = Se, r = Ne, n = Be, s = Z, a = ut, o = De, i = Ve, l = Vt, f = e.f;
  Se = /** @type {null | Value[]} */
  null, Ne = 0, Be = null, Z = (f & (st | vt)) === 0 ? e : null, ut = null, ar(e.ctx), Ve = !1, Vt = ++jt, e.ac !== null && (Cr(() => {
    e.ac.abort(Tr);
  }), e.ac = null);
  try {
    e.f |= wr;
    var d = (
      /** @type {Function} */
      e.fn
    ), v = d();
    e.f |= Kt;
    var h = zs(e);
    if (va() && Be !== null && !Ve && h !== null && (e.f & (Ee | Ye | oe)) === 0)
      for (var _ = 0; _ < /** @type {Source[]} */
      Be.length; _++)
        Ba(
          Be[_],
          /** @type {Effect} */
          e
        );
    if (s !== null && s !== e) {
      if (jt++, s.deps !== null)
        for (let u = 0; u < r; u += 1)
          s.deps[u].rv = jt;
      if (t !== null)
        for (const u of t)
          u.rv = jt;
      Be !== null && (n === null ? n = Be : n.push(.../** @type {Source[]} */
      Be));
    }
    return (e.f & At) !== 0 && (e.f ^= At), v;
  } catch (u) {
    return zs(e), Ni(u);
  } finally {
    e.f ^= wr, Se = t, Ne = r, Be = n, Z = s, ut = a, ar(o), Ve = i, Vt = l;
  }
}
function zs(e) {
  var t = e.deps, r = V?.is_fork;
  if (Se !== null) {
    var n;
    if (r || Sr(e, Ne), t !== null && Ne > 0)
      for (t.length = Ne + Se.length, n = 0; n < Se.length; n++)
        t[Ne + n] = Se[n];
    else
      e.deps = t = Se;
    if (ss() && (e.f & rt) !== 0)
      for (n = Ne; n < t.length; n++)
        (t[n].reactions ??= []).push(e);
  } else !r && t !== null && Ne < t.length && (Sr(e, Ne), t.length = Ne);
  return t;
}
function Bi(e, t) {
  let r = t.reactions;
  if (r !== null) {
    var n = Do.call(r, e);
    if (n !== -1) {
      var s = r.length - 1;
      s === 0 ? r = t.reactions = null : (r[n] = r[s], r.pop());
    }
  }
  if (r === null && (t.f & Ee) !== 0 && // Destroying a child effect while updating a parent effect can cause a dependency to appear
  // to be unused, when in fact it is used by the currently-updating parent. Checking `new_deps`
  // allows us to skip the expensive work of disconnecting and immediately reconnecting it
  (Se === null || !kr.call(Se, t))) {
    var a = (
      /** @type {Derived} */
      t
    );
    (a.f & rt) !== 0 && (a.f ^= rt), a.v !== ue && Zn(a), a.ac !== null && Cr(() => {
      a.ac.abort(Tr), a.ac = null, ae(a, oe);
    }), Si(a), Sr(a, 0);
  }
}
function Sr(e, t) {
  var r = e.deps;
  if (r !== null)
    for (var n = t; n < r.length; n++)
      Bi(e, r[n]);
}
function dr(e) {
  var t = e.f;
  if ((t & Ae) === 0) {
    ae(e, he);
    var r = Y, n = jr;
    if (Y = e, jr = (t & (st | vt)) === 0, m) {
      var s = Mr;
      ps(e.component_function);
      var a = (
        /** @type {any} */
        or
      );
      qr(e.dev_stack ?? or);
    }
    try {
      (t & (Qe | Gn)) !== 0 ? Fi(e) : os(e), Oa(e);
      var o = On(e);
      e.teardown = typeof o == "function" ? o : null, e.wv = Ha;
      var i;
      m && hi && (e.f & oe) !== 0 && e.deps;
    } finally {
      jr = n, Y = r, m && (ps(s), qr(a));
    }
  }
}
async function Ui() {
  await Promise.resolve(), I();
}
function c(e) {
  var t = e.f, r = (t & Ee) !== 0;
  if (Z !== null && !Ve) {
    var n = Y !== null && (Y.f & Ae) !== 0;
    if (!n && (ut === null || !ut.has(e))) {
      var s = Z.deps;
      if ((Z.f & wr) !== 0)
        e.rv < jt && (e.rv = jt, Se === null && s !== null && s[Ne] === e ? Ne++ : Se === null ? Se = [e] : Se.push(e));
      else {
        Z.deps ??= [], kr.call(Z.deps, e) || Z.deps.push(e);
        var a = e.reactions;
        a === null ? e.reactions = [Z] : kr.call(a, Z) || a.push(Z);
      }
    }
  }
  if (m) {
    if (!Ve && Ue && // By checking that current/previous batch are null we filter out false positives.
    // reactivity_loss_tracker is only reset after a microtask, so if a flush happens
    // before that, we get warnings for things we shouldn't warn on.
    V === null && Kr === null && !Ue.warned && (Ue.effect.f & wr) === 0 && !Ue.effect_deps.has(e)) {
      Ue.warned = !0, qo(
        /** @type {string} */
        e.label
      );
      var o = fa("traced at");
      o && console.warn(o);
    }
    wi.delete(e);
  }
  if (Ct && ct.has(e))
    return ct.get(e);
  if (r) {
    var i = (
      /** @type {Derived} */
      e
    );
    if (Ct) {
      var l = i.v;
      return ((i.f & he) === 0 && i.reactions !== null || Ya(i)) && (l = Qn(i)), ct.set(i, l), l;
    }
    var f = (i.f & rt) === 0 && !Ve && Z !== null && (jr || (Z.f & rt) !== 0), d = (i.f & Kt) === 0;
    Rr(i) && (f && (i.f |= rt), ka(i)), f && !d && (ma(i), Ua(i));
  }
  if (tt?.has(e))
    return tt.get(e);
  if ((e.f & At) !== 0)
    throw e.v;
  return e.v;
}
function Ua(e) {
  if (e.f |= rt, e.deps !== null)
    for (const t of e.deps)
      (t.reactions ??= []).push(e), (t.f & Ee) !== 0 && (t.f & rt) === 0 && (ma(
        /** @type {Derived} */
        t
      ), Ua(
        /** @type {Derived} */
        t
      ));
}
function Ya(e) {
  if (e.v === ue) return !0;
  if (e.deps === null) return !1;
  for (const t of e.deps)
    if (ct.has(t) || (t.f & Ee) !== 0 && Ya(
      /** @type {Derived} */
      t
    ))
      return !0;
  return !1;
}
function ln(e) {
  var t = Ve;
  try {
    return Ve = !0, e();
  } finally {
    Ve = t;
  }
}
const hr = /* @__PURE__ */ Symbol("events"), Va = /* @__PURE__ */ new Set(), Dn = /* @__PURE__ */ new Set();
function qa(e, t, r, n = {}) {
  function s(a) {
    if (n.capture || In.call(t, a), !a.cancelBubble)
      return Cr(() => r?.call(this, a));
  }
  return e.startsWith("pointer") || e.startsWith("touch") || e === "wheel" ? (s.__removed = !1, et(() => {
    s.__removed || t.addEventListener(e, s, n);
  })) : t.addEventListener(e, s, n), s;
}
function As(e, t, r, n, s) {
  var a = { capture: n, passive: s }, o = qa(e, t, r, a);
  (t === document.body || // @ts-ignore
  t === window || // @ts-ignore
  t === document || // Firefox has quirky behavior, it can happen that we still get "canplay" events when the element is already removed
  t instanceof HTMLMediaElement) && on(() => {
    o.__removed = !0, t.removeEventListener(e, o, a);
  });
}
function it(e, t, r) {
  (t[hr] ??= {})[e] = r;
}
function ls(e) {
  for (var t = 0; t < e.length; t++)
    Va.add(e[t]);
  for (var r of Dn)
    r(e);
}
let bn = null, kn = !1;
function In(e) {
  var t = this, r = (
    /** @type {Node} */
    t.ownerDocument
  ), n = e.type, s = e.composedPath?.() || [], a = (
    /** @type {null | Element} */
    s[0] || e.target
  );
  bn = e, kn || (kn = !0, setTimeout(() => {
    kn = !1, bn = null;
  }));
  var o = 0, i = bn === e && e[hr];
  if (i) {
    var l = s.indexOf(i);
    if (l !== -1 && (t === document || t === /** @type {any} */
    window)) {
      e[hr] = t;
      return;
    }
    var f = s.indexOf(t);
    if (f === -1)
      return;
    l <= f && (o = l);
  }
  if (a = /** @type {Element} */
  s[o] || e.target, a !== t) {
    ft(e, "currentTarget", {
      configurable: !0,
      get() {
        return a || r;
      }
    });
    var d = Z, v = Y;
    Ke(null), nt(null);
    try {
      for (var h, _ = []; a !== null && a !== t; ) {
        try {
          var u = a[hr]?.[n];
          u != null && (!/** @type {any} */
          a.disabled || // DOM could've been updated already by the time this is reached, so we check this as well
          // -> the target could not have been disabled because it emits the event in the first place
          e.target === a) && u.call(a, e);
        } catch (y) {
          h ? _.push(y) : h = y;
        }
        if (e.cancelBubble) break;
        o++, a = o < s.length ? (
          /** @type {Element} */
          s[o]
        ) : null;
      }
      if (h) {
        for (let y of _)
          queueMicrotask(() => {
            throw y;
          });
        throw h;
      }
    } finally {
      e[hr] = t, delete e.currentTarget, Ke(d), nt(v);
    }
  }
}
const Yi = (
  // We gotta write it like this because after downleveling the pure comment may end up in the wrong location
  globalThis?.window?.trustedTypes && /* @__PURE__ */ globalThis.window.trustedTypes.createPolicy("svelte-trusted-html", {
    /** @param {string} html */
    createHTML: (e) => e
  })
);
function Vi(e) {
  return (
    /** @type {string} */
    Yi?.createHTML(e) ?? e
  );
}
function Wa(e) {
  var t = sn("template");
  return t.innerHTML = Vi(e.replaceAll("<!>", "<!---->")), t.content;
}
function qe(e, t) {
  var r = (
    /** @type {Effect} */
    Y
  );
  r.nodes === null && (r.nodes = { start: e, end: t, a: null, t: null });
}
// @__NO_SIDE_EFFECTS__
function O(e, t) {
  var r = (t & Xs) !== 0, n = (t & Ro) !== 0, s, a = !e.startsWith("<!>");
  return () => {
    if (D)
      return qe(j, null), j;
    s === void 0 && (s = Wa(a ? e : "<!>" + e), r || (s = /** @type {TemplateNode} */
    /* @__PURE__ */ Oe(s)));
    var o = (
      /** @type {TemplateNode} */
      n || ns ? document.importNode(s, !0) : s.cloneNode(!0)
    );
    if (r) {
      var i = (
        /** @type {TemplateNode} */
        /* @__PURE__ */ Oe(o)
      ), l = (
        /** @type {TemplateNode} */
        o.lastChild
      );
      qe(i, l);
    } else
      qe(o, o);
    return o;
  };
}
// @__NO_SIDE_EFFECTS__
function qi(e, t, r = "svg") {
  var n = !e.startsWith("<!>"), s = (t & Xs) !== 0, a = `<${r}>${n ? e : "<!>" + e}</${r}>`, o;
  return () => {
    if (D)
      return qe(j, null), j;
    if (!o) {
      var i = (
        /** @type {DocumentFragment} */
        Wa(a)
      ), l = (
        /** @type {Element} */
        /* @__PURE__ */ Oe(i)
      );
      if (s)
        for (o = document.createDocumentFragment(); /* @__PURE__ */ Oe(l); )
          o.appendChild(
            /** @type {TemplateNode} */
            /* @__PURE__ */ Oe(l)
          );
      else
        o = /** @type {Element} */
        /* @__PURE__ */ Oe(l);
    }
    var f = (
      /** @type {TemplateNode} */
      o.cloneNode(!0)
    );
    if (s) {
      var d = (
        /** @type {TemplateNode} */
        /* @__PURE__ */ Oe(f)
      ), v = (
        /** @type {TemplateNode} */
        f.lastChild
      );
      qe(d, v);
    } else
      qe(f, f);
    return f;
  };
}
// @__NO_SIDE_EFFECTS__
function _t(e, t) {
  return /* @__PURE__ */ qi(e, t, "svg");
}
function Xr(e = "") {
  if (!D) {
    var t = Me(e + "");
    return qe(t, t), t;
  }
  var r = j;
  return r.nodeType !== zr ? (r.before(r = Me()), pe(r)) : an(
    /** @type {Text} */
    r
  ), qe(r, r), r;
}
function ke() {
  if (D)
    return qe(j, null), j;
  var e = document.createDocumentFragment(), t = document.createComment(""), r = Me();
  return e.append(t, r), qe(t, r), e;
}
function k(e, t) {
  if (D) {
    var r = (
      /** @type {Effect & { nodes: EffectNodes }} */
      Y
    );
    ((r.f & Kt) === 0 || r.nodes.end === null) && (r.nodes.end = j), sr();
    return;
  }
  e !== null && e.before(
    /** @type {Node} */
    t
  );
}
function Wi(e) {
  return e.endsWith("capture") && e !== "gotpointercapture" && e !== "lostpointercapture";
}
const Ki = [
  "beforeinput",
  "click",
  "change",
  "dblclick",
  "contextmenu",
  "focusin",
  "focusout",
  "input",
  "keydown",
  "keyup",
  "mousedown",
  "mousemove",
  "mouseout",
  "mouseover",
  "mouseup",
  "pointerdown",
  "pointermove",
  "pointerout",
  "pointerover",
  "pointerup",
  "touchend",
  "touchmove",
  "touchstart"
];
function Gi(e) {
  return Ki.includes(e);
}
const Xi = {
  // no `class: 'className'` because we handle that separately
  formnovalidate: "formNoValidate",
  ismap: "isMap",
  nomodule: "noModule",
  playsinline: "playsInline",
  readonly: "readOnly",
  defaultvalue: "defaultValue",
  defaultchecked: "defaultChecked",
  srcobject: "srcObject",
  novalidate: "noValidate",
  allowfullscreen: "allowFullscreen",
  disablepictureinpicture: "disablePictureInPicture",
  disableremoteplayback: "disableRemotePlayback"
};
function Ji(e) {
  return e = e.toLowerCase(), Xi[e] ?? e;
}
const Zi = ["touchstart", "touchmove"];
function Qi(e) {
  return Zi.includes(e);
}
const el = (
  /** @type {const} */
  ["textarea", "script", "style", "title"]
);
function tl(e) {
  return el.includes(
    /** @type {typeof RAW_TEXT_ELEMENTS[number]} */
    e
  );
}
function rl(e) {
  let t = 0, r = qt(0), n;
  return m && Ze(r, "createSubscriber version"), () => {
    ss() && (c(r), as(() => (t === 0 && (n = ln(() => e(() => pr(r)))), t += 1, () => {
      et(() => {
        t -= 1, t === 0 && (n?.(), n = void 0, pr(r));
      });
    })));
  };
}
var nl = Mt | Gt;
function sl(e, t, r, n) {
  new al(e, t, r, n);
}
class al {
  /** @type {Boundary | null} */
  parent;
  is_pending = !1;
  /**
   * API-level transformError transform function. Transforms errors before they reach the `failed` snippet.
   * Inherited from parent boundary, or defaults to identity.
   * @type {(error: unknown) => unknown}
   */
  transform_error;
  /** @type {TemplateNode} */
  #e;
  /** @type {TemplateNode | null} */
  #t = D ? j : null;
  /** @type {BoundaryProps} */
  #r;
  /** @type {((anchor: Node) => void)} */
  #i;
  /** @type {Effect} */
  #s;
  /** @type {Effect | null} */
  #o = null;
  /** @type {Effect | null} */
  #n = null;
  /** @type {Effect | null} */
  #l = null;
  /** @type {DocumentFragment | null} */
  #a = null;
  #h = 0;
  #c = 0;
  #u = !1;
  /** @type {Set<Effect>} */
  #f = /* @__PURE__ */ new Set();
  /** @type {Set<Effect>} */
  #y = /* @__PURE__ */ new Set();
  /**
   * A source containing the number of pending async deriveds/expressions.
   * Only created if `$effect.pending()` is used inside the boundary,
   * otherwise updating the source results in needless `Batch.ensure()`
   * calls followed by no-op flushes
   * @type {Source<number> | null}
   */
  #d = null;
  #b = rl(() => (this.#d = qt(this.#h), m && Ze(this.#d, "$effect.pending()"), () => {
    this.#d = null;
  }));
  /**
   * @param {TemplateNode} node
   * @param {BoundaryProps} props
   * @param {((anchor: Node) => void)} children
   * @param {((error: unknown) => unknown) | undefined} [transform_error]
   */
  constructor(t, r, n, s) {
    this.#e = t, this.#r = r, this.#i = (a) => {
      var o = (
        /** @type {Effect} */
        Y
      );
      o.b = this, o.f |= zn, n(a);
    }, this.parent = /** @type {Effect} */
    Y.b, this.transform_error = s ?? this.parent?.transform_error ?? ((a) => a), this.#s = Nr(() => {
      if (D) {
        const a = (
          /** @type {Comment} */
          this.#t
        );
        sr();
        const o = a.data === Wn;
        if (a.data.startsWith(_s)) {
          const l = JSON.parse(a.data.slice(_s.length));
          this.#g(l);
        } else o ? this.#x() : this.#k();
      } else
        this.#m();
    }, nl), D && (this.#e = j);
  }
  #k() {
    try {
      this.#o = Re(() => this.#i(this.#e));
    } catch (t) {
      this.error(t);
    }
  }
  /**
   * @param {unknown} error The deserialized error from the server's hydration comment
   */
  #g(t) {
    const r = this.#r.failed, { reset: n, invoke_onerror: s } = this.#p(t);
    et(s), r && (this.#l = Re(() => {
      r(
        this.#e,
        () => t,
        () => n
      );
    }));
  }
  /**
   * Creates the `reset` function for a failed boundary, along with a function
   * that invokes `onerror` with it (if provided)
   * @param {unknown} error
   * @returns {{ reset: () => void, invoke_onerror: () => void }}
   */
  #p(t) {
    var r = !1, n = !1;
    const s = () => {
      if (r) {
        Jo();
        return;
      }
      r = !0, n && vi(), this.#l !== null && Yt(this.#l, () => {
        this.#l = null;
      }), this.#w(() => {
        this.#m();
      });
    };
    return { reset: s, invoke_onerror: () => {
      try {
        n = !0, this.#r.onerror?.(t, s), n = !1;
      } catch (o) {
        lt(o, this.#s && this.#s.parent);
      }
    } };
  }
  #x() {
    const t = this.#r.pending;
    t && (this.is_pending = !0, this.#n = Re(() => t(this.#e)), et(() => {
      var r = this.#a = document.createDocumentFragment(), n = Me(), s = !1;
      if (r.append(n), this.#o = this.#w(() => {
        try {
          return Re(() => this.#i(n));
        } catch (a) {
          try {
            this.error(a), s = !0;
          } catch (o) {
            lt(o, this.#s.parent);
          }
          return null;
        }
      }), this.#o === null) {
        this.#a = null, s && this.#v(
          /** @type {Batch} */
          V
        );
        return;
      }
      this.#c === 0 && (this.#e.before(r), this.#a = null, Yt(
        /** @type {Effect} */
        this.#n,
        () => {
          this.#n = null;
        }
      ), this.#v(
        /** @type {Batch} */
        V
      ));
    }));
  }
  #m() {
    try {
      if (this.is_pending = this.has_pending_snippet(), this.#c = 0, this.#h = 0, this.#o = Re(() => {
        this.#i(this.#e);
      }), this.#c > 0) {
        var t = this.#a = document.createDocumentFragment();
        is(this.#o, t);
        const r = (
          /** @type {(anchor: Node) => void} */
          this.#r.pending
        );
        this.#n = Re(() => r(this.#e));
      } else
        this.#v(
          /** @type {Batch} */
          V
        );
    } catch (r) {
      this.error(r);
    }
  }
  /**
   * @param {Batch} batch
   */
  #v(t) {
    this.is_pending = !1, t.transfer_effects(this.#f, this.#y);
  }
  /**
   * Defer an effect inside a pending boundary until the boundary resolves
   * @param {Effect} effect
   */
  defer_effect(t) {
    _a(t, this.#f, this.#y);
  }
  /**
   * Returns `false` if the effect exists inside a boundary whose pending snippet is shown
   * @returns {boolean}
   */
  is_rendered() {
    return !this.is_pending && (!this.parent || this.parent.is_rendered());
  }
  has_pending_snippet() {
    return !!this.#r.pending;
  }
  /**
   * @template T
   * @param {() => T} fn
   */
  #w(t) {
    var r = Y, n = Z, s = De;
    nt(this.#s), Ke(this.#s), ar(this.#s.ctx);
    try {
      return mt.ensure(), t();
    } finally {
      nt(r), Ke(n), ar(s);
    }
  }
  /**
   * Updates the pending count associated with the currently visible pending snippet,
   * if any, such that we can replace the snippet with content once work is done
   * @param {1 | -1} d
   * @param {Batch} batch
   */
  #_(t, r) {
    if (!this.has_pending_snippet()) {
      this.parent && this.parent.#_(t, r);
      return;
    }
    this.#c += t, this.#c === 0 && (this.#v(r), this.#n && Yt(this.#n, () => {
      this.#n = null;
    }), this.#a && (this.#e.before(this.#a), this.#a = null));
  }
  /**
   * Update the source that powers `$effect.pending()` inside this boundary,
   * and controls when the current `pending` snippet (if any) is removed.
   * Do not call from inside the class
   * @param {1 | -1} d
   * @param {Batch} batch
   */
  update_pending_count(t, r) {
    this.#_(t, r), this.#h += t, !(!this.#d || this.#u) && (this.#u = !0, et(() => {
      this.#u = !1, this.#d && lr(this.#d, this.#h);
    }));
  }
  get_effect_pending() {
    return this.#b(), c(
      /** @type {Source<number>} */
      this.#d
    );
  }
  /** @param {unknown} error */
  error(t) {
    if (!this.#r.onerror && !this.#r.failed)
      throw t;
    V?.is_fork ? (this.#o && V.skip_effect(this.#o), this.#n && V.skip_effect(this.#n), this.#l && V.skip_effect(this.#l), V.oncommit(() => {
      this.#S(t);
    })) : this.#S(t);
  }
  /**
   * @param {unknown} error
   */
  #S(t) {
    this.#o && (be(this.#o), this.#o = null), this.#n && (be(this.#n), this.#n = null), this.#l && (be(this.#l), this.#l = null), D && (pe(
      /** @type {TemplateNode} */
      this.#t
    ), Zo(), pe(Vr()));
    let r = this.#r.failed;
    const n = (s) => {
      const { reset: a, invoke_onerror: o } = this.#p(s);
      o(), r && (this.#l = this.#w(() => {
        try {
          return Re(() => {
            var i = (
              /** @type {Effect} */
              Y
            );
            i.b = this, i.f |= zn, r(
              this.#e,
              () => s,
              () => a
            );
          });
        } catch (i) {
          return lt(
            i,
            /** @type {Effect} */
            this.#s.parent
          ), null;
        }
      }));
    };
    et(() => {
      var s;
      try {
        s = this.transform_error(t);
      } catch (a) {
        lt(a, this.#s && this.#s.parent);
        return;
      }
      s !== null && typeof s == "object" && typeof /** @type {any} */
      s.then == "function" ? s.then(
        n,
        /** @param {unknown} e */
        (a) => lt(a, this.#s && this.#s.parent)
      ) : n(s);
    });
  }
}
function J(e, t) {
  var r = t == null ? "" : typeof t == "object" ? `${t}` : t;
  r !== /** @type {any} */
  (e[Cn] ??= e.nodeValue) && (e[Cn] = r, e.nodeValue = `${r}`);
}
function Ka(e, t) {
  return Ga(e, t);
}
function ol(e, t) {
  Rn(), t.intro = t.intro ?? !1;
  const r = t.target, n = D, s = j;
  try {
    for (var a = /* @__PURE__ */ Oe(r); a && (a.nodeType !== Ar || /** @type {Comment} */
    a.data !== Js); )
      a = /* @__PURE__ */ ht(a);
    if (!a)
      throw rr;
    Fe(!0), pe(
      /** @type {Comment} */
      a
    );
    const o = Ga(e, { ...t, anchor: a });
    return Fe(!1), /**  @type {Exports} */
    o;
  } catch (o) {
    if (o instanceof Error && o.message.split(`
`).some((i) => i.startsWith("https://svelte.dev/e/")))
      throw o;
    return o !== rr && console.warn("Failed to hydrate: ", o), t.recover === !1 && ai(), Rn(), $a(r), Fe(!1), Ka(e, t);
  } finally {
    Fe(n), pe(s);
  }
}
const Ir = /* @__PURE__ */ new Map();
function Ga(e, { target: t, anchor: r, props: n = {}, events: s, context: a, intro: o = !0, transformError: i }) {
  Rn();
  var l = void 0, f = Ii(() => {
    var d = r ?? t.appendChild(Me());
    sl(
      /** @type {TemplateNode} */
      d,
      {
        pending: () => {
        }
      },
      (_) => {
        Ce({});
        var u = (
          /** @type {ComponentContext} */
          De
        );
        if (a && (u.c = a), s && (n.$$events = s), D && qe(
          /** @type {TemplateNode} */
          _,
          null
        ), l = e(_, n) || Jn(), D && (Y.nodes.end = j, j === null || j.nodeType !== Ar || /** @type {Comment} */
        j.data !== Kn))
          throw nn(), rr;
        $e();
      },
      i
    );
    var v = /* @__PURE__ */ new Set(), h = (_) => {
      for (var u = 0; u < _.length; u++) {
        var y = _[u];
        if (!v.has(y)) {
          v.add(y);
          var g = Qi(y);
          for (const R of [t, document]) {
            var b = Ir.get(R);
            b === void 0 && (b = /* @__PURE__ */ new Map(), Ir.set(R, b));
            var A = b.get(y);
            A === void 0 ? (R.addEventListener(y, In, { passive: g }), b.set(y, 1)) : b.set(y, A + 1);
          }
        }
      }
    };
    return h(en(Va)), Dn.add(h), () => {
      for (var _ of v)
        for (const g of [t, document]) {
          var u = (
            /** @type {Map<string, number>} */
            Ir.get(g)
          ), y = (
            /** @type {number} */
            u.get(_)
          );
          --y == 0 ? (g.removeEventListener(_, In), u.delete(_), u.size === 0 && Ir.delete(g)) : u.set(_, y);
        }
      Dn.delete(h), d !== r && d.parentNode?.removeChild(d);
    };
  });
  return Pn.set(l, f), l;
}
let Pn = /* @__PURE__ */ new WeakMap();
function il(e, t) {
  const r = Pn.get(e);
  return r ? (Pn.delete(e), r(t)) : (m && Go(), Promise.resolve());
}
class ds {
  /** @type {TemplateNode} */
  anchor;
  /** @type {Map<Batch, Key>} */
  #e = /* @__PURE__ */ new Map();
  /**
   * Map of keys to effects that are currently rendered in the DOM.
   * These effects are visible and actively part of the document tree.
   * Example:
   * ```
   * {#if condition}
   * 	foo
   * {:else}
   * 	bar
   * {/if}
   * ```
   * Can result in the entries `true->Effect` and `false->Effect`
   * @type {Map<Key, Effect>}
   */
  #t = /* @__PURE__ */ new Map();
  /**
   * Similar to #onscreen with respect to the keys, but contains branches that are not yet
   * in the DOM, because their insertion is deferred.
   * @type {Map<Key, Branch>}
   */
  #r = /* @__PURE__ */ new Map();
  /**
   * Keys of effects that are currently outroing
   * @type {Set<Key>}
   */
  #i = /* @__PURE__ */ new Set();
  /**
   * Whether to pause (i.e. outro) on change, or destroy immediately.
   * This is necessary for `<svelte:element>`
   */
  #s = !0;
  /**
   * @param {TemplateNode} anchor
   * @param {boolean} transition
   */
  constructor(t, r = !0) {
    this.anchor = t, this.#s = r;
  }
  /**
   * @param {Batch} batch
   */
  #o = (t) => {
    if (this.#e.has(t)) {
      var r = (
        /** @type {Key} */
        this.#e.get(t)
      ), n = this.#t.get(r);
      if (n)
        Gr(n), this.#i.delete(r);
      else {
        var s = this.#r.get(r);
        s && (Gr(s.effect), this.#t.set(r, s.effect), this.#r.delete(r), m && (s.fragment.lastChild[Yo] = this.anchor), s.fragment.lastChild.remove(), this.anchor.before(s.fragment), n = s.effect);
      }
      for (const [a, o] of this.#e) {
        if (this.#e.delete(a), a === t)
          break;
        const i = this.#r.get(o);
        i && (be(i.effect), this.#r.delete(o));
      }
      for (const [a, o] of this.#t) {
        if (a === r || this.#i.has(a)) continue;
        const i = () => {
          if (Array.from(this.#e.values()).includes(a)) {
            var f = document.createDocumentFragment();
            is(o, f), f.append(Me()), this.#r.set(a, { effect: o, fragment: f });
          } else
            be(o);
          this.#i.delete(a), this.#t.delete(a);
        };
        this.#s || !n ? (this.#i.add(a), Yt(o, i, !1)) : i();
      }
    }
  };
  /**
   * @param {Batch} batch
   */
  #n = (t) => {
    this.#e.delete(t);
    const r = Array.from(this.#e.values());
    for (const [n, s] of this.#r)
      r.includes(n) || (be(s.effect), this.#r.delete(n));
  };
  /**
   *
   * @param {any} key
   * @param {null | ((target: TemplateNode) => void)} fn
   */
  ensure(t, r) {
    var n = (
      /** @type {Batch} */
      V
    ), s = Na();
    if (r && !this.#t.has(t) && !this.#r.has(t))
      if (s) {
        var a = document.createDocumentFragment(), o = Me();
        a.append(o), this.#r.set(t, {
          effect: Re(() => r(o)),
          fragment: a
        });
      } else
        this.#t.set(
          t,
          Re(() => r(this.anchor))
        );
    if (this.#e.set(n, t), s) {
      for (const [i, l] of this.#t)
        i === t ? n.unskip_effect(l) : n.skip_effect(l);
      for (const [i, l] of this.#r)
        i === t ? n.unskip_effect(l.effect) : n.skip_effect(l.effect);
      n.oncommit(this.#o), n.ondiscard(this.#n);
    } else
      D && (this.anchor = j), this.#o(n);
  }
}
function Le(e, t, ...r) {
  var n = new ds(e);
  Nr(() => {
    const s = t() ?? null;
    m && s == null && oi(), n.ensure(s, s && ((a) => s(a, ...r)));
  }, Mt);
}
if (m) {
  let e = function(t) {
    if (!(t in globalThis)) {
      let r;
      Object.defineProperty(globalThis, t, {
        configurable: !0,
        // eslint-disable-next-line getter-return
        get: () => {
          if (r !== void 0)
            return r;
          di(t);
        },
        set: (n) => {
          r = n;
        }
      });
    }
  };
  e("$state"), e("$effect"), e("$derived"), e("$inspect"), e("$props"), e("$bindable");
}
function Rt() {
  return Symbol(Qs);
}
var Ms = /* @__PURE__ */ new Map();
function ll(e, t) {
  var r = Ms.get(e);
  r || (r = /* @__PURE__ */ new Set(), Ms.set(e, r)), r.add(t);
}
function U(e, t, r = !1) {
  var n;
  D && (n = j, sr());
  var s = new ds(e), a = r ? Mt : 0;
  function o(i, l) {
    if (D) {
      var f = ia(
        /** @type {TemplateNode} */
        n
      );
      if (i !== parseInt(f.substring(1))) {
        var d = Vr();
        pe(d), s.anchor = d, Fe(!1), s.ensure(i, l), Fe(!0);
        return;
      }
    }
    s.ensure(i, l);
  }
  Nr(() => {
    var i = !1;
    t((l, f = 0) => {
      i = !0, o(f, l);
    }), i || o(-1, null);
  }, a);
}
function dl(e, t) {
  return t;
}
function cl(e, t, r) {
  for (var n = [], s = t.length, a, o = t.length, i = 0; i < s; i++) {
    let v = t[i];
    Yt(
      v,
      () => {
        if (a) {
          if (a.pending.delete(v), a.done.add(v), a.pending.size === 0) {
            var h = (
              /** @type {Set<EachOutroGroup>} */
              e.outrogroups
            );
            Fn(e, en(a.done)), h.delete(a), h.size === 0 && (e.outrogroups = null);
          }
        } else
          o -= 1;
      },
      !1
    );
  }
  if (o === 0) {
    var l = n.length === 0 && r !== null && e.pending.size === 0;
    if (l) {
      var f = (
        /** @type {Element} */
        r
      ), d = (
        /** @type {Element} */
        f.parentNode
      );
      $a(d), d.append(f), e.items.clear();
    }
    Fn(e, t, !l);
  } else
    a = {
      pending: new Set(t),
      done: /* @__PURE__ */ new Set()
    }, (e.outrogroups ??= /* @__PURE__ */ new Set()).add(a);
}
function Fn(e, t, r = !0) {
  var n;
  if (e.pending.size > 0) {
    n = /* @__PURE__ */ new Set();
    for (const o of e.pending.values())
      for (const i of o)
        n.add(
          /** @type {EachItem} */
          e.items.get(i).e
        );
  }
  for (var s = 0; s < t.length; s++) {
    var a = t[s];
    if (n?.has(a)) {
      a.f |= dt;
      const o = document.createDocumentFragment();
      is(a, o);
    } else
      be(t[s], r);
  }
}
var Cs;
function kt(e, t, r, n, s, a = null) {
  var o = e, i = /* @__PURE__ */ new Map(), l = (t & Gs) !== 0;
  if (l) {
    var f = (
      /** @type {Element} */
      e
    );
    o = D ? pe(/* @__PURE__ */ Oe(f)) : f.appendChild(Me());
  }
  D && sr();
  var d = null, v = /* @__PURE__ */ ba(() => {
    var R = r();
    return (
      /** @type {V[]} */
      Qr(R) ? R : R == null ? [] : en(R)
    );
  });
  m && Ze(v, "{#each ...}");
  var h, _ = /* @__PURE__ */ new Map(), u = !0;
  function y(R) {
    (A.effect.f & Ae) === 0 && (A.pending.delete(R), A.fallback = d, ul(A, h, o, t, n), d !== null && (h.length === 0 ? (d.f & dt) === 0 ? Gr(d) : (d.f ^= dt, _r(d, null, o)) : Yt(d, () => {
      d = null;
    })));
  }
  function g(R) {
    A.pending.delete(R);
  }
  var b = Nr(() => {
    h = /** @type {V[]} */
    c(v);
    var R = h.length;
    let w = !1;
    if (D) {
      var q = ia(o) === Wn;
      q !== (R === 0) && (o = Vr(), pe(o), Fe(!1), w = !0);
    }
    for (var N = /* @__PURE__ */ new Set(), M = (
      /** @type {Batch} */
      V
    ), H = Na(), T = 0; T < R; T += 1) {
      D && j.nodeType === Ar && /** @type {Comment} */
      j.data === Kn && (o = /** @type {Comment} */
      j, w = !0, Fe(!1));
      var p = h[T], C = n(p, T);
      if (m) {
        var K = n(p, T);
        C !== K && ni(String(T), String(C), String(K));
      }
      var Q = u ? null : i.get(C);
      Q ? (Q.v && lr(Q.v, p), Q.i && lr(Q.i, T), H && M.unskip_effect(Q.e)) : (Q = fl(
        i,
        u ? o : Cs ??= Me(),
        p,
        C,
        T,
        s,
        t,
        r
      ), u || (Q.e.f |= dt), i.set(C, Q)), N.add(C);
    }
    if (R === 0 && a && !d && (u ? d = Re(() => a(o)) : (d = Re(() => a(Cs ??= Me())), d.f |= dt)), R > N.size && (m ? vl(h, n) : ca("", "", "")), D && R > 0 && pe(Vr()), !u)
      if (_.set(M, N), H) {
        for (const [G, ie] of i)
          N.has(G) || M.skip_effect(ie.e);
        M.oncommit(y), M.ondiscard(g);
      } else
        y(M);
    w && Fe(!0), c(v);
  }), A = { effect: b, items: i, pending: _, outrogroups: null, fallback: d };
  u = !1, D && (o = j);
}
function cr(e) {
  for (; e !== null && (e.f & st) === 0; )
    e = e.next;
  return e;
}
function ul(e, t, r, n, s) {
  var a = (n & zo) !== 0, o = t.length, i = e.items, l = cr(e.effect.first), f, d = null, v, h = [], _ = [], u, y, g, b;
  if (a)
    for (b = 0; b < o; b += 1)
      u = t[b], y = s(u, b), g = /** @type {EachItem} */
      i.get(y).e, (g.f & dt) === 0 && (g.nodes?.a?.measure(), (v ??= /* @__PURE__ */ new Set()).add(g));
  for (b = 0; b < o; b += 1) {
    if (u = t[b], y = s(u, b), g = /** @type {EachItem} */
    i.get(y).e, e.outrogroups !== null)
      for (const p of e.outrogroups)
        p.pending.delete(g), p.done.delete(g);
    if ((g.f & ze) !== 0 && (Gr(g), a && (g.nodes?.a?.unfix(), (v ??= /* @__PURE__ */ new Set()).delete(g))), (g.f & dt) !== 0)
      if (g.f ^= dt, g === l)
        _r(g, null, r);
      else {
        var A = d ? d.next : l;
        g === e.effect.last && (e.effect.last = g.prev), g.prev && (g.prev.next = g.next), g.next && (g.next.prev = g.prev), St(e, d, g), St(e, g, A), _r(g, A, r), d = g, h = [], _ = [], l = cr(d.next);
        continue;
      }
    if (g !== l) {
      if (f !== void 0 && f.has(g)) {
        if (h.length < _.length) {
          var R = _[0], w;
          d = R.prev;
          var q = h[0], N = h[h.length - 1];
          for (w = 0; w < h.length; w += 1)
            _r(h[w], R, r);
          for (w = 0; w < _.length; w += 1)
            f.delete(_[w]);
          St(e, q.prev, N.next), St(e, d, q), St(e, N, R), l = R, d = N, b -= 1, h = [], _ = [];
        } else
          f.delete(g), _r(g, l, r), St(e, g.prev, g.next), St(e, g, d === null ? e.effect.first : d.next), St(e, d, g), d = g;
        continue;
      }
      for (h = [], _ = []; l !== null && l !== g; )
        (f ??= /* @__PURE__ */ new Set()).add(l), _.push(l), l = cr(l.next);
      if (l === null)
        continue;
    }
    (g.f & dt) === 0 && h.push(g), d = g, l = cr(g.next);
  }
  if (e.outrogroups !== null) {
    for (const p of e.outrogroups)
      p.pending.size === 0 && (Fn(e, en(p.done)), e.outrogroups?.delete(p));
    e.outrogroups.size === 0 && (e.outrogroups = null);
  }
  if (l !== null || f !== void 0) {
    var M = [];
    if (f !== void 0)
      for (g of f)
        (g.f & ze) === 0 && M.push(g);
    for (; l !== null; )
      (l.f & ze) === 0 && l !== e.fallback && M.push(l), l = cr(l.next);
    var H = M.length;
    if (H > 0) {
      var T = (n & Gs) !== 0 && o === 0 ? r : null;
      if (a) {
        for (b = 0; b < H; b += 1)
          M[b].nodes?.a?.measure();
        for (b = 0; b < H; b += 1)
          M[b].nodes?.a?.fix();
      }
      cl(e, M, T);
    }
  }
  a && et(() => {
    if (v !== void 0)
      for (g of v)
        g.nodes?.a?.apply();
  });
}
function fl(e, t, r, n, s, a, o, i) {
  var l = (o & Eo) !== 0 ? (o & Ao) === 0 ? /* @__PURE__ */ Ea(r, !1, !1) : qt(r) : null, f = (o & To) !== 0 ? qt(s) : null;
  return m && l && (l.trace = () => {
    i()[f?.v ?? s];
  }), {
    v: l,
    i: f,
    e: Re(() => (a(t, l ?? r, f ?? s, i), () => {
      e.delete(n);
    }))
  };
}
function _r(e, t, r) {
  if (e.nodes)
    for (var n = e.nodes.start, s = e.nodes.end, a = t && (t.f & dt) === 0 ? (
      /** @type {EffectNodes} */
      t.nodes.start
    ) : r; n !== null; ) {
      var o = (
        /** @type {TemplateNode} */
        /* @__PURE__ */ ht(n)
      );
      if (a.before(n), n === s)
        return;
      n = o;
    }
}
function St(e, t, r) {
  t === null ? e.effect.first = r : t.next = r, r === null ? e.effect.last = t : r.prev = t;
}
function vl(e, t) {
  const r = /* @__PURE__ */ new Map(), n = e.length;
  for (let s = 0; s < n; s++) {
    const a = t(e[s], s);
    if (r.has(a)) {
      const o = String(r.get(a)), i = String(s);
      let l = String(a);
      l.startsWith("[object ") && (l = null), ca(o, i, l);
    }
    r.set(a, s);
  }
}
function ot(e, t, r, n, s, a) {
  let o = D;
  D && sr();
  var i = null;
  D && j.nodeType === Vo && (i = /** @type {Element} */
  j, sr());
  var l = (
    /** @type {TemplateNode} */
    D ? j : e
  ), f = new ds(l, !1);
  Nr(() => {
    const d = t() || null;
    var v = d === "svg" ? Oo : void 0;
    if (d === null) {
      f.ensure(null, null);
      return;
    }
    return f.ensure(d, (h) => {
      if (d) {
        if (i = D ? (
          /** @type {Element} */
          i
        ) : sn(d, v), qe(i, i), n) {
          var _ = null;
          D && tl(d) && i.append(_ = document.createComment(""));
          var u = D ? /* @__PURE__ */ Oe(i) : i.appendChild(Me());
          D && (u === null ? Fe(!1) : pe(u)), n(i, u), _?.remove();
        }
        Y.nodes.end = i, h.before(i);
      }
      D && pe(h);
    }), () => {
    };
  }, Mt), on(() => {
  }), o && (Fe(!0), pe(l));
}
function Ge(e, t) {
  $r(() => {
    e = Y?.parent?.nodes?.start ?? e;
    var r = e.getRootNode(), n = (
      /** @type {ShadowRoot} */
      r.host ? (
        /** @type {ShadowRoot} */
        r
      ) : (
        /** @type {Document} */
        r.head ?? /** @type {Document} */
        r.ownerDocument.head
      )
    );
    if (!n.querySelector("#" + t.hash)) {
      const s = sn("style");
      s.id = t.hash, s.textContent = t.code, n.appendChild(s), m && ll(t.hash, s);
    }
  });
}
function hl(e, t) {
  var r = void 0, n;
  La(() => {
    r !== (r = t()) && (n && (be(n), n = null), r && (n = Re(() => {
      $r(() => (
        /** @type {(node: Element) => void} */
        r(e)
      ));
    })));
  });
}
function Xa(e) {
  var t, r, n = "";
  if (typeof e == "string" || typeof e == "number") n += e;
  else if (typeof e == "object") if (Array.isArray(e)) {
    var s = e.length;
    for (t = 0; t < s; t++) e[t] && (r = Xa(e[t])) && (n && (n += " "), n += r);
  } else for (r in e) e[r] && (n && (n += " "), n += r);
  return n;
}
function _l() {
  for (var e, t, r = 0, n = "", s = arguments.length; r < s; r++) (e = arguments[r]) && (t = Xa(e)) && (n && (n += " "), n += t);
  return n;
}
function Ja(e) {
  return typeof e == "object" ? _l(e) : e ?? "";
}
const $s = [...` 	
\r\f \v\uFEFF`];
function yl(e, t, r) {
  var n = e == null ? "" : "" + e;
  if (t && (n = n ? n + " " + t : t), r) {
    for (var s of Object.keys(r))
      if (r[s])
        n = n ? n + " " + s : s;
      else if (n.length)
        for (var a = s.length, o = 0; (o = n.indexOf(s, o)) >= 0; ) {
          var i = o + a;
          (o === 0 || $s.includes(n[o - 1])) && (i === n.length || $s.includes(n[i])) ? n = (o === 0 ? "" : n.substring(0, o)) + n.substring(i + 1) : o = i;
        }
  }
  return n === "" ? null : n;
}
function Ns(e, t = !1) {
  var r = t ? " !important;" : ";", n = "";
  for (var s of Object.keys(e)) {
    var a = e[s];
    a != null && a !== "" && (n += " " + s + ": " + a + r);
  }
  return n;
}
function mn(e) {
  return e[0] !== "-" || e[1] !== "-" ? e.toLowerCase() : e;
}
function gl(e, t) {
  if (t) {
    var r = "", n, s;
    if (Array.isArray(t) ? (n = t[0], s = t[1]) : n = t, e) {
      e = String(e).replaceAll(/\/\*.*?\*\//g, "").trim();
      var a = !1, o = 0, i = !1, l = [];
      n && l.push(...Object.keys(n).map(mn)), s && l.push(...Object.keys(s).map(mn));
      var f = 0, d = -1;
      const y = e.length;
      for (var v = 0; v < y; v++) {
        var h = e[v];
        if (i ? h === "/" && e[v - 1] === "*" && (i = !1) : a ? a === h && (a = !1) : h === "/" && e[v + 1] === "*" ? i = !0 : h === '"' || h === "'" ? a = h : h === "(" ? o++ : h === ")" && o--, !i && a === !1 && o === 0) {
          if (h === ":" && d === -1)
            d = v;
          else if (h === ";" || v === y - 1) {
            if (d !== -1) {
              var _ = mn(e.substring(f, d).trim());
              if (!l.includes(_)) {
                h !== ";" && v++;
                var u = e.substring(f, v).trim();
                r += " " + u + ";";
              }
            }
            f = v + 1, d = -1;
          }
        }
      }
    }
    return n && (r += Ns(n)), s && (r += Ns(s, !0)), r = r.trim(), r === "" ? null : r;
  }
  return e == null ? null : String(e);
}
function Za(e, t, r, n, s, a) {
  var o = (
    /** @type {any} */
    e[An]
  );
  if (D || o !== r || o === void 0) {
    var i = yl(r, n, a);
    (!D || i !== e.getAttribute("class")) && (i == null ? e.removeAttribute("class") : t ? e.className = i : e.setAttribute("class", i)), e[An] = r;
  } else if (a && s !== a)
    for (var l in a) {
      var f = !!a[l];
      (s == null || f !== !!s[l]) && e.classList.toggle(l, f);
    }
  return a;
}
function wn(e, t = {}, r, n) {
  for (var s in r) {
    var a = r[s];
    t[s] !== a && (r[s] == null ? e.style.removeProperty(s) : e.style.setProperty(s, a, n));
  }
}
function bt(e, t, r, n) {
  var s = (
    /** @type {any} */
    e[Mn]
  );
  if (D || s !== t) {
    var a = gl(t, n);
    (!D || a !== e.getAttribute("style")) && (a == null ? e.removeAttribute("style") : e.style.cssText = a), e[Mn] = t;
  } else n && (Array.isArray(n) ? (wn(e, r?.[0], n[0]), wn(e, r?.[1], n[1], "important")) : wn(e, r, n));
  return n;
}
function Qa(e, t) {
  t ? e.hasAttribute("selected") || e.setAttribute("selected", "") : e.removeAttribute("selected");
}
function Rs(e, t) {
  var r = !("__defaultValue" in e);
  !r && e.__defaultValue === t || (e.__defaultValue = t, eo(e, !r || "__value" in e));
}
function eo(e, t) {
  var r = e.__defaultValue, n = e.multiple, s = n ? r ?? [] : null;
  if (!(n && !Qr(s))) {
    var a = e.selectedIndex, o = t && n ? new Set(e.selectedOptions) : null;
    for (var i of e.options) {
      var l = jn(i);
      Qa(
        i,
        n ? (
          /** @type {any[]} */
          s.includes(l)
        ) : Aa(l, r)
      );
    }
    if (t)
      if (o !== null)
        for (i of e.options) {
          var f = o.has(i);
          i.selected !== f && (i.selected = f);
        }
      else e.selectedIndex !== a && (e.selectedIndex = a);
  }
}
function Hn(e, t, r = !1) {
  if (e.multiple) {
    if (t == null)
      return;
    if (!Qr(t))
      return Xo();
    for (var n of e.options)
      n.selected = t.includes(jn(n));
    return;
  }
  for (n of e.options) {
    var s = jn(n);
    if (Aa(s, t)) {
      n.selected = !0;
      return;
    }
  }
  (!r || t !== void 0) && (e.selectedIndex = -1);
}
function pl(e) {
  var t = new MutationObserver((r) => {
    r.every(bl) || ("__defaultValue" in e && eo(e, !1), "__value" in e && Hn(e, e.__value));
  });
  t.observe(e, {
    // Listen to option element changes
    childList: !0,
    subtree: !0,
    // because of <optgroup>
    // Listen to option element value attribute changes
    // (doesn't get notified of select value changes,
    // because that property is not reflected as an attribute)
    attributes: !0,
    attributeFilter: ["value"]
  }), on(() => {
    t.disconnect();
  });
}
function jn(e) {
  return "__value" in e ? e.__value : e.value;
}
function bl(e) {
  if (
    /** @type {Element} */
    e.target.closest("selectedcontent") !== null
  )
    return !0;
  if (e.type === "childList") {
    var t = [...e.addedNodes, ...e.removedNodes];
    return t.length > 0 && t.every((r) => r.nodeName === "SELECTEDCONTENT");
  }
  return !1;
}
const ur = /* @__PURE__ */ Symbol("class"), fr = /* @__PURE__ */ Symbol("style"), to = /* @__PURE__ */ Symbol("is custom element"), ro = /* @__PURE__ */ Symbol("is html"), kl = rn ? "link" : "LINK", Ls = rn ? "input" : "INPUT", ml = rn ? "option" : "OPTION", no = rn ? "select" : "SELECT";
function wl(e) {
  if (D) {
    var t = !1, r = () => {
      if (!t) {
        if (t = !0, e.hasAttribute("value")) {
          var n = e.value;
          L(e, "value", null), e.value = n;
        }
        if (e.hasAttribute("checked")) {
          var s = e.checked;
          L(e, "checked", null), e.checked = s;
        }
      }
    };
    e[oa] = r, et(r), ki();
  }
}
function L(e, t, r, n) {
  var s = so(e);
  if (D && (s[t] = e.getAttribute(t), t === "src" || t === "srcset" || t === "href" && e.nodeName === kl)) {
    n || Sl(e, t, r ?? "");
    return;
  }
  s[t] !== (s[t] = r) && (t === "loading" && (e[Uo] = r), r == null ? e.removeAttribute(t) : typeof r != "string" && ao(e).has(t) ? e[t] = r : e.setAttribute(t, r));
}
function xl(e, t, r, n, s = !1, a = !1) {
  D && s && e.nodeName === Ls && ("defaultValue" in r || "defaultChecked" in r || wl(
    /** @type {HTMLInputElement} */
    e
  ));
  var o = so(e), i = o[to], l = !o[ro];
  let f = D && i;
  f && Fe(!1);
  var d = t || {}, v = e.nodeName === ml, h = e.nodeName === no;
  for (var _ in t)
    !(_ in r) && _[0] + _[1] !== "$$" && (r[_] = null);
  r.class ? r.class = Ja(r.class) : (n || r[ur]) && (r.class = null), r[fr] && (r.style ??= null);
  var u = ao(e);
  if (e.nodeName === Ls && "type" in r && ("value" in r || "__value" in r)) {
    var y = r.type;
    (y !== d.type || y === void 0 && e.hasAttribute("type")) && (d.type = y, L(e, "type", y, a));
  }
  for (const N in r) {
    let M = r[N];
    if (v && N === "value" && M == null) {
      e.value = e.__value = "", d[N] = M;
      continue;
    }
    if (N === "class") {
      var g = e.namespaceURI === "http://www.w3.org/1999/xhtml";
      Za(e, g, M, n, t?.[ur], r[ur]), d[N] = M, d[ur] = r[ur];
      continue;
    }
    if (N === "style") {
      bt(e, M, t?.[fr], r[fr]), d[N] = M, d[fr] = r[fr];
      continue;
    }
    var b = d[N];
    if (!(M === b && !(M === void 0 && e.hasAttribute(N)))) {
      d[N] = M;
      var A = N[0] + N[1];
      if (A !== "$$")
        if (A === "on") {
          const H = {}, T = "$$" + N;
          let p = N.slice(2);
          var R = Gi(p);
          if (Wi(p) && (p = p.slice(0, -7), H.capture = !0), !R && b) {
            if (M != null) continue;
            e.removeEventListener(p, d[T], H), d[T] = null;
          }
          if (R)
            it(p, e, M), ls([p]);
          else if (M != null) {
            let C = function(K) {
              d[N].call(this, K);
            };
            d[T] = qa(p, e, C, H);
          }
        } else if (N === "style")
          L(e, N, M);
        else if (N === "autofocus")
          bi(
            /** @type {HTMLElement} */
            e,
            !!M
          );
        else if (!i && (N === "__value" || N === "value" && M != null))
          e.value = e.__value = M;
        else if (N === "selected" && v)
          Qa(
            /** @type {HTMLOptionElement} */
            e,
            M
          );
        else {
          var w = N;
          l || (w = Ji(w));
          var q = w === "defaultValue" || w === "defaultChecked";
          if (h && w === "defaultValue") continue;
          if (M == null && !i && !q)
            if (o[N] = null, w === "value" || w === "checked") {
              let H = (
                /** @type {HTMLInputElement} */
                e
              );
              const T = t === void 0;
              if (w === "value") {
                let p = H.defaultValue;
                H.removeAttribute(w), H.defaultValue = p, H.value = H.__value = T ? p : null;
              } else {
                let p = H.defaultChecked;
                H.removeAttribute(w), H.defaultChecked = p, H.checked = T ? p : !1;
              }
            } else
              e.removeAttribute(N);
          else q || (i || typeof M != "string") && u.has(w) ? (e[w] = M, w in o && (o[w] = ue)) : typeof M != "function" && L(e, w, M, a);
        }
    }
  }
  return f && Fe(!0), d;
}
function _e(e, t, r = [], n = [], s = [], a, o = !1, i = !1) {
  ya(s, r, n, (l) => {
    var f = void 0, d = {}, v = e.nodeName === no, h = !1;
    if (La(() => {
      var u = t(...l.map(c)), y = xl(
        e,
        f,
        u,
        a,
        o,
        i
      );
      if (h && v) {
        var g = (
          /** @type {HTMLSelectElement} */
          e
        );
        "defaultValue" in u && Rs(g, u.defaultValue), "value" in u && Hn(g, u.value);
      }
      for (let A of Object.getOwnPropertySymbols(d))
        u[A] || be(d[A]);
      for (let A of Object.getOwnPropertySymbols(u)) {
        var b = u[A];
        A.description === Qs && (!f || b !== f[A]) && (d[A] && be(d[A]), d[A] = Re(() => hl(e, () => b))), y[A] = b;
      }
      f = y;
    }), v) {
      var _ = (
        /** @type {HTMLSelectElement} */
        e
      );
      $r(() => {
        var u = (
          /** @type {Record<string | symbol, any>} */
          f
        );
        "defaultValue" in u && Rs(_, u.defaultValue), Hn(_, u.value, !0), pl(_);
      });
    }
    h = !0;
  });
}
function so(e) {
  return (
    /** @type {Record<string | symbol, unknown>} **/
    /** @type {any} */
    e[aa] ??= {
      [to]: e.nodeName.includes("-"),
      [ro]: e.namespaceURI === Zs
    }
  );
}
var Os = /* @__PURE__ */ new Map();
function ao(e) {
  var t = e.getAttribute("is") || e.nodeName, r = Os.get(t);
  if (r) return r;
  Os.set(t, r = /* @__PURE__ */ new Set());
  for (var n, s = e, a = Element.prototype; a !== s; ) {
    n = Io(s);
    for (var o in n)
      n[o].set && // better safe than sorry, we don't want spread attributes to mess with HTML content
      o !== "innerHTML" && o !== "textContent" && o !== "innerText" && r.add(o);
    s = ea(s);
  }
  return r;
}
function Sl(e, t, r) {
  m && (t === "srcset" && El(e, r) || Bn(e.getAttribute(t) ?? "", r) || Ko(
    t,
    e.outerHTML.replace(e.innerHTML, e.innerHTML && "..."),
    String(r)
  ));
}
function Bn(e, t) {
  return e === t ? !0 : new URL(e, document.baseURI).href === new URL(t, document.baseURI).href;
}
function Ds(e) {
  return e.split(",").map((t) => t.trim().split(" ").filter(Boolean));
}
function El(e, t) {
  var r = Ds(e.srcset), n = Ds(t);
  return n.length === r.length && n.every(
    ([s, a], o) => a === r[o][1] && // We need to test both ways because Vite will create an a full URL with
    // `new URL(asset, import.meta.url).href` for the client when `base: './'`, and the
    // relative URLs inside srcset are not automatically resolved to absolute URLs by
    // browsers (in contrast to img.src). This means both SSR and DOM code could
    // contain relative or absolute URLs.
    (Bn(r[o][0], s) || Bn(s, r[o][0]))
  );
}
class cs {
  /** */
  #e = /* @__PURE__ */ new WeakMap();
  /** @type {ResizeObserver | undefined} */
  #t;
  /** @type {ResizeObserverOptions} */
  #r;
  /** @static */
  static entries = /* @__PURE__ */ new WeakMap();
  /** @param {ResizeObserverOptions} options */
  constructor(t) {
    this.#r = t;
  }
  /**
   * @param {Element} element
   * @param {(entry: ResizeObserverEntry) => any} listener
   */
  observe(t, r) {
    var n = this.#e.get(t) || /* @__PURE__ */ new Set();
    return n.add(r), this.#e.set(t, n), this.#i().observe(t, this.#r), () => {
      var s = this.#e.get(t);
      s.delete(r), s.size === 0 && (this.#e.delete(t), this.#t.unobserve(t));
    };
  }
  #i() {
    return this.#t ?? (this.#t = new ResizeObserver(
      /** @param {any} entries */
      (t) => {
        for (var r of t) {
          cs.entries.set(r.target, r);
          for (var n of this.#e.get(r.target) || [])
            n(r);
        }
      }
    ));
  }
}
var Tl = /* @__PURE__ */ new cs({
  box: "border-box"
});
function xn(e, t, r) {
  var n = Tl.observe(e, () => r(e[t]));
  $r(() => (ln(() => r(e[t])), n));
}
function Sn(e, t) {
  return e === t || e?.[Ut] === t;
}
function zl(e = Jn(), t, r, n) {
  var s = (
    /** @type {ComponentContext} */
    De.r
  ), a = (
    /** @type {Effect} */
    Y
  );
  return $r(() => {
    var o, i;
    return as(() => {
      o = i, i = [], ln(() => {
        Sn(r(...i), e) || (t(e, ...i), o && Sn(r(...o), e) && t(null, ...o));
      });
    }), () => {
      let l = a;
      for (; l !== s && l.parent !== null && l.parent.f & Yr; )
        l = l.parent;
      const f = () => {
        i && Sn(r(...i), e) && t(null, ...i);
      }, d = l.teardown;
      l.teardown = () => {
        f(), d?.();
      };
    };
  }), e;
}
let Pr = !1;
function Al(e) {
  var t = Pr;
  try {
    return Pr = !1, [e(), Pr];
  } finally {
    Pr = t;
  }
}
const Ml = {
  get(e, t) {
    if (!e.exclude.has(t))
      return e.props[t];
  },
  set(e, t) {
    return m && li(`${e.name}.${String(t)}`), !1;
  },
  getOwnPropertyDescriptor(e, t) {
    if (!e.exclude.has(t) && t in e.props)
      return {
        enumerable: !0,
        configurable: !0,
        value: e.props[t]
      };
  },
  has(e, t) {
    return e.exclude.has(t) ? !1 : t in e.props;
  },
  ownKeys(e) {
    return Reflect.ownKeys(e.props).filter((t) => !e.exclude.has(t));
  }
};
// @__NO_SIDE_EFFECTS__
function wt(e, t, r) {
  return new Proxy(m ? { props: e, exclude: t, name: r } : { props: e, exclude: t }, Ml);
}
function x(e, t, r, n) {
  var s = !0, a = (r & $o) !== 0, o = (r & No) !== 0, i = (
    /** @type {V} */
    n
  ), l = !0, f = (
    /** @type {Derived<V> | undefined} */
    void 0
  ), d = () => o && s ? (f ??= /* @__PURE__ */ xr(
    /** @type {() => V} */
    n
  ), c(f)) : (l && (l = !1, i = o ? ln(
    /** @type {() => V} */
    n
  ) : (
    /** @type {V} */
    n
  )), i);
  let v;
  if (a) {
    var h = Ut in e || na in e;
    v = zt(e, t)?.set ?? (h && t in e ? (w) => e[t] = w : void 0);
  }
  var _, u = !1;
  a ? [_, u] = Al(() => (
    /** @type {V} */
    e[t]
  )) : _ = /** @type {V} */
  e[t], _ === void 0 && n !== void 0 && (_ = d(), v && (ii(t), v(_)));
  var y;
  if (y = () => {
    var w = (
      /** @type {V} */
      e[t]
    );
    return w === void 0 ? d() : (l = !0, w);
  }, (r & Co) === 0)
    return y;
  if (v) {
    var g = e.$$legacy;
    return (
      /** @type {() => V} */
      (function(w, q) {
        return arguments.length > 0 ? ((!q || g || u) && v(q ? y() : w), w) : y();
      })
    );
  }
  var b = !1, A = ((r & Mo) !== 0 ? xr : ba)(() => (b = !1, y()));
  m && (A.label = t), a && c(A);
  var R = (
    /** @type {Effect} */
    Y
  );
  return (
    /** @type {() => V} */
    (function(w, q) {
      if (arguments.length > 0) {
        const N = q ? c(A) : a ? Et(w) : w;
        return ve(A, N), b = !0, i !== void 0 && (i = N), w;
      }
      return Ct && b || (R.f & Ae) !== 0 ? A.v : c(A);
    })
  );
}
function Cl(e) {
  return new $l(e);
}
class $l {
  /** @type {any} */
  #e;
  /** @type {Record<string, any>} */
  #t;
  /**
   * @param {ComponentConstructorOptions & {
   *  component: any;
   * }} options
   */
  constructor(t) {
    var r = /* @__PURE__ */ new Map(), n = (a, o) => {
      var i = /* @__PURE__ */ Ea(o, !1, !1);
      return r.set(a, i), i;
    };
    const s = new Proxy(
      { ...t.props || {}, $$events: {} },
      {
        get(a, o) {
          return c(r.get(o) ?? n(o, Reflect.get(a, o)));
        },
        has(a, o) {
          return o === na ? !0 : (c(r.get(o) ?? n(o, Reflect.get(a, o))), Reflect.has(a, o));
        },
        set(a, o, i) {
          return ve(r.get(o) ?? n(o, i), i), Reflect.set(a, o, i);
        }
      }
    );
    this.#t = (t.hydrate ? ol : Ka)(t.component, {
      target: t.target,
      anchor: t.anchor,
      props: s,
      context: t.context,
      intro: t.intro ?? !1,
      recover: t.recover,
      transformError: t.transformError
    }), (!t?.props?.$$host || t.sync === !1) && I(), this.#e = s.$$events;
    for (const a of Object.keys(this.#t))
      a === "$set" || a === "$destroy" || a === "$on" || ft(this, a, {
        get() {
          return this.#t[a];
        },
        /** @param {any} value */
        set(o) {
          this.#t[a] = o;
        },
        enumerable: !0
      });
    this.#t.$set = /** @param {Record<string, any>} next */
    (a) => {
      Object.assign(s, a);
    }, this.#t.$destroy = () => {
      il(this.#t);
    };
  }
  /** @param {Record<string, any>} props */
  $set(t) {
    this.#t.$set(t);
  }
  /**
   * @param {string} event
   * @param {(...args: any[]) => any} callback
   * @returns {any}
   */
  $on(t, r) {
    this.#e[t] = this.#e[t] || [];
    const n = (...s) => r.call(this, ...s);
    return this.#e[t].push(n), () => {
      this.#e[t] = this.#e[t].filter(
        /** @param {any} fn */
        (s) => s !== n
      );
    };
  }
  $destroy() {
    this.#t.$destroy();
  }
}
let oo;
typeof HTMLElement == "function" && (oo = class extends HTMLElement {
  /** The Svelte component constructor */
  $$ctor;
  /** Slots */
  $$s;
  /** @type {any} The Svelte component instance */
  $$c;
  /** Whether or not the custom element is connected */
  $$cn = !1;
  /** @type {Record<string, any>} Component props data */
  $$d = {};
  /** `true` if currently in the process of reflecting component props back to attributes */
  $$r = !1;
  /** @type {Record<string, CustomElementPropDefinition>} Props definition (name, reflected, type etc) */
  $$p_d = {};
  /** @type {Record<string, EventListenerOrEventListenerObject[]>} Event listeners */
  $$l = {};
  /** @type {Map<EventListenerOrEventListenerObject, Function>} Event listener unsubscribe functions */
  $$l_u = /* @__PURE__ */ new Map();
  /** @type {any} The managed render effect for reflecting attributes */
  $$me;
  /** @type {ShadowRoot | null} The ShadowRoot of the custom element */
  $$shadowRoot = null;
  /**
   * @param {*} $$componentCtor
   * @param {*} $$slots
   * @param {ShadowRootInit | undefined} shadow_root_init
   */
  constructor(e, t, r) {
    super(), this.$$ctor = e, this.$$s = t, r && (this.$$shadowRoot = this.attachShadow(r));
  }
  /**
   * @param {string} type
   * @param {EventListenerOrEventListenerObject} listener
   * @param {boolean | AddEventListenerOptions} [options]
   */
  addEventListener(e, t, r) {
    if (this.$$l[e] = this.$$l[e] || [], this.$$l[e].push(t), this.$$c) {
      const n = this.$$c.$on(e, t);
      this.$$l_u.set(t, n);
    }
    super.addEventListener(e, t, r);
  }
  /**
   * @param {string} type
   * @param {EventListenerOrEventListenerObject} listener
   * @param {boolean | AddEventListenerOptions} [options]
   */
  removeEventListener(e, t, r) {
    if (super.removeEventListener(e, t, r), this.$$c) {
      const n = this.$$l_u.get(t);
      n && (n(), this.$$l_u.delete(t));
    }
  }
  async connectedCallback() {
    if (this.$$cn = !0, !this.$$c) {
      let e = function(n) {
        return (s) => {
          const a = sn("slot");
          n !== "default" && (a.name = n), k(s, a);
        };
      };
      if (await Promise.resolve(), !this.$$cn || this.$$c)
        return;
      const t = {}, r = Nl(this);
      for (const n of this.$$s)
        n in r && (n === "default" && !this.$$d.children ? (this.$$d.children = e(n), t.default = !0) : t[n] = e(n));
      for (const n of this.attributes) {
        const s = this.$$g_p(n.name);
        s in this.$$d || (this.$$d[s] = Br(s, n.value, this.$$p_d, "toProp"));
      }
      for (const n in this.$$p_d)
        !(n in this.$$d) && this[n] !== void 0 && (this.$$d[n] = this[n], delete this[n]);
      this.$$c = Cl({
        component: this.$$ctor,
        target: this.$$shadowRoot || this,
        props: {
          ...this.$$d,
          $$slots: t,
          $$host: this
        }
      }), this.$$me = Di(() => {
        as(() => {
          this.$$r = !0;
          for (const n of Ur(this.$$c)) {
            if (!this.$$p_d[n]?.reflect) continue;
            this.$$d[n] = this.$$c[n];
            const s = Br(
              n,
              this.$$d[n],
              this.$$p_d,
              "toAttribute"
            );
            s == null ? this.removeAttribute(this.$$p_d[n].attribute || n) : this.setAttribute(this.$$p_d[n].attribute || n, s);
          }
          this.$$r = !1;
        });
      });
      for (const n in this.$$l)
        for (const s of this.$$l[n]) {
          const a = this.$$c.$on(n, s);
          this.$$l_u.set(s, a);
        }
      this.$$l = {};
    }
  }
  // We don't need this when working within Svelte code, but for compatibility of people using this outside of Svelte
  // and setting attributes through setAttribute etc, this is helpful
  /**
   * @param {string} attr
   * @param {string} _oldValue
   * @param {string} newValue
   */
  attributeChangedCallback(e, t, r) {
    this.$$r || (e = this.$$g_p(e), this.$$d[e] = Br(e, r, this.$$p_d, "toProp"), this.$$c?.$set({ [e]: this.$$d[e] }));
  }
  disconnectedCallback() {
    this.$$cn = !1, Promise.resolve().then(() => {
      !this.$$cn && this.$$c && (this.$$c.$destroy(), this.$$me(), this.$$c = void 0);
    });
  }
  /**
   * @param {string} attribute_name
   */
  $$g_p(e) {
    return Ur(this.$$p_d).find(
      (t) => this.$$p_d[t].attribute === e || !this.$$p_d[t].attribute && t.toLowerCase() === e
    ) || e;
  }
});
function Br(e, t, r, n) {
  const s = r[e]?.type;
  if (t = s === "Boolean" && typeof t != "boolean" ? t != null : t, !n || !r[e])
    return t;
  if (n === "toAttribute")
    switch (s) {
      case "Object":
      case "Array":
        return t == null ? null : JSON.stringify(t);
      case "Boolean":
        return t ? "" : null;
      case "Number":
        return t ?? null;
      default:
        return t;
    }
  else
    switch (s) {
      case "Object":
      case "Array":
        return t && JSON.parse(t);
      case "Boolean":
        return t;
      // conversion already handled above
      case "Number":
        return t != null ? +t : t;
      default:
        return t;
    }
}
function Nl(e) {
  const t = {};
  return e.childNodes.forEach((r) => {
    t[
      /** @type {Element} node */
      r.slot || "default"
    ] = !0;
  }), t;
}
function Lt(e, t, r, n, s, a) {
  let o = class extends oo {
    constructor() {
      super(e, r, s), this.$$p_d = t;
    }
    static get observedAttributes() {
      return Ur(t).map(
        (i) => (t[i].attribute || i).toLowerCase()
      );
    }
  };
  return Ur(t).forEach((i) => {
    ft(o.prototype, i, {
      get() {
        return this.$$c && i in this.$$c ? this.$$c[i] : this.$$d[i];
      },
      set(l) {
        l = Br(i, l, t), this.$$d[i] = l;
        var f = this.$$c;
        if (f) {
          var d = zt(f, i)?.get;
          d ? f[i] = l : f.$set({ [i]: l });
        }
      }
    });
  }), n.forEach((i) => {
    ft(o.prototype, i, {
      get() {
        return this.$$c?.[i];
      }
    });
  }), e.element = /** @type {any} */
  o, o;
}
var Rl = /* @__PURE__ */ new Set([
  "$$slots",
  "$$events",
  "$$legacy",
  "variant",
  "tone",
  "size",
  "icon",
  "dot",
  "children"
]), Ll = /* @__PURE__ */ O('<span class="sky-badge__dot svelte-a0twff" aria-hidden="true"></span>'), Ol = /* @__PURE__ */ O('<span class="sky-badge__icon svelte-a0twff"><!></span>'), Dl = /* @__PURE__ */ O('<span class="sky-badge__label svelte-a0twff"><!></span>'), Il = /* @__PURE__ */ O("<span><!> <!></span>");
const Pl = {
  hash: "svelte-a0twff",
  code: `.sky-badge.svelte-a0twff {--_bg: var(--sky-color-neutral-soft);--_fg: var(--ds-color-text-muted);--_border: transparent;display:inline-flex;align-items:center;gap:var(--ds-space-1-5);box-sizing:border-box;height:1.625rem; /* 26 */max-width:100%;padding:0 var(--ds-space-3);border:var(--ds-border-width) solid var(--_border);border-radius:var(--ds-radius-full);background:var(--_bg);color:var(--_fg);font-size:var(--ds-text-sm);font-weight:var(--ds-font-weight-semibold);line-height:1;white-space:nowrap;vertical-align:middle;}.sky-badge[data-has-icon].svelte-a0twff {padding-left:var(--ds-space-2-5);}.sky-badge[data-size='sm'].svelte-a0twff {height:1.25rem; /* 20 */gap:var(--ds-space-1);padding:0 var(--ds-space-2);font-size:var(--ds-text-xs);}.sky-badge__label.svelte-a0twff {overflow:hidden;text-overflow:ellipsis;}.sky-badge__icon.svelte-a0twff {display:flex;}.sky-badge__icon.svelte-a0twff svg {width:0.75rem;height:0.75rem;}.sky-badge__dot.svelte-a0twff {flex-shrink:0;width:0.4375rem;height:0.4375rem;border-radius:50%;background:currentColor;box-shadow:0 0 0 3px color-mix(in oklab, currentColor 24%, transparent);}
  @media (prefers-reduced-motion: no-preference) {.sky-badge__dot.svelte-a0twff {
      animation: svelte-a0twff-sky-badge-pulse 1.6s var(--sky-ease-in-out) infinite;}
  }
  @keyframes svelte-a0twff-sky-badge-pulse {
    50% {
      box-shadow: 0 0 0 5px color-mix(in oklab, currentColor 10%, transparent);
    }
  }

  /* soft */.sky-badge[data-variant='soft'][data-tone='accent'].svelte-a0twff {--_bg: var(--sky-color-accent-soft);--_fg: var(--sky-color-accent-soft-fg);}.sky-badge[data-variant='soft'][data-tone='danger'].svelte-a0twff {--_bg: var(--sky-color-danger-soft);--_fg: var(--sky-color-danger-soft-fg);}.sky-badge[data-variant='soft'][data-tone='warning'].svelte-a0twff {--_bg: var(--sky-color-warning-soft);--_fg: var(--sky-color-warning-soft-fg);}.sky-badge[data-variant='soft'][data-tone='success'].svelte-a0twff {--_bg: color-mix(in oklab, var(--ds-color-success) 16%, transparent);--_fg: color-mix(in oklab, var(--ds-color-success) 55%, var(--ds-color-fg));}

  /* solid */.sky-badge[data-variant='solid'].svelte-a0twff {--_fg: var(--ds-color-bg);}.sky-badge[data-variant='solid'][data-tone='neutral'].svelte-a0twff {--_bg: var(--ds-color-text-muted);}.sky-badge[data-variant='solid'][data-tone='accent'].svelte-a0twff {--_bg: var(--sky-color-accent-solid);--_fg: var(--sky-color-accent-solid-contrast);}.sky-badge[data-variant='solid'][data-tone='danger'].svelte-a0twff {--_bg: var(--ds-color-danger);}.sky-badge[data-variant='solid'][data-tone='warning'].svelte-a0twff {--_bg: var(--ds-color-warning);}.sky-badge[data-variant='solid'][data-tone='success'].svelte-a0twff {--_bg: var(--ds-color-success);}

  /* outline: a quiet fill with a hairline (Cancelled reads as the canvas's grey pill) */.sky-badge[data-variant='outline'].svelte-a0twff {--_bg: var(--sky-color-neutral-soft);--_border: var(--sky-color-border-muted);}.sky-badge[data-variant='outline'][data-tone='accent'].svelte-a0twff {--_bg: transparent;--_fg: var(--sky-color-accent-soft-fg);--_border: var(--sky-color-accent-ring);}.sky-badge[data-variant='outline'][data-tone='danger'].svelte-a0twff {--_bg: transparent;--_fg: var(--sky-color-danger-soft-fg);--_border: color-mix(in oklab, var(--ds-color-danger) 35%, transparent);}.sky-badge[data-variant='outline'][data-tone='warning'].svelte-a0twff {--_bg: transparent;--_fg: var(--sky-color-warning-soft-fg);--_border: color-mix(in oklab, var(--ds-color-warning) 35%, transparent);}.sky-badge[data-variant='outline'][data-tone='success'].svelte-a0twff {--_bg: transparent;--_fg: var(--ds-color-success);--_border: color-mix(in oklab, var(--ds-color-success) 35%, transparent);}`
};
function Fl(e, t) {
  Ge(e, Pl);
  let r = x(t, "variant", 3, "soft"), n = x(t, "tone", 3, "neutral"), s = x(t, "size", 3, "md"), a = x(t, "dot", 3, !1), o = /* @__PURE__ */ wt(t, Rl);
  var i = Il();
  _e(
    i,
    () => ({
      ...o,
      class: "sky-badge",
      "data-variant": r(),
      "data-tone": n(),
      "data-size": s(),
      "data-has-icon": t.icon || a() ? "" : void 0
    }),
    void 0,
    void 0,
    void 0,
    "svelte-a0twff"
  );
  var l = z(i);
  {
    var f = (_) => {
      var u = Ll();
      k(_, u);
    }, d = (_) => {
      var u = Ol(), y = z(u);
      Le(y, () => t.icon), S(u), k(_, u);
    };
    U(l, (_) => {
      a() ? _(f) : t.icon && _(d, 1);
    });
  }
  var v = E(l, 2);
  {
    var h = (_) => {
      var u = Dl(), y = z(u);
      Le(y, () => t.children), S(u), k(_, u);
    };
    U(v, (_) => {
      t.children && _(h);
    });
  }
  S(i), k(e, i);
}
const Hl = ".sky-visually-hidden{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}.sky-focus-ring:focus-visible{outline:var(--sky-focus-ring-width) solid var(--sky-color-focus);outline-offset:var(--sky-focus-ring-offset)}.sky-mono{font-family:var(--ds-font-mono);font-size:var(--sky-text-data);font-variant-numeric:tabular-nums}.sky-label{font-family:var(--ds-font-mono);font-size:var(--sky-text-label);letter-spacing:var(--sky-tracking-label);text-transform:uppercase;color:var(--ds-color-text-subtle)}", Is = /* @__PURE__ */ new Map();
function jl(e) {
  if (typeof CSSStyleSheet > "u" || !("replaceSync" in CSSStyleSheet.prototype)) return null;
  let t = Is.get(e);
  return t || (t = new CSSStyleSheet(), t.replaceSync(e), Is.set(e, t)), t;
}
function Ps(e, t) {
  const r = jl(t);
  !r || e.adoptedStyleSheets.includes(r) || (e.adoptedStyleSheets = [...e.adoptedStyleSheets, r]);
}
const yt = "slot", Bl = ":host { display: block; }";
function Ot(e, t = {}) {
  return (r) => {
    const n = r.getRootNode();
    if (!(!(n instanceof ShadowRoot) || !(n.host instanceof HTMLElement)))
      return Ps(n, Hl), t.block && Ps(n, Bl), e?.(n.host);
  };
}
function Fs(e) {
  const t = /* @__PURE__ */ new Set();
  for (const r of Array.from(e.childNodes))
    r instanceof Element ? t.add(r.getAttribute("slot") ?? "") : r.nodeType === Node.TEXT_NODE && r.textContent?.trim() && t.add("");
  return t;
}
function dn(e, t) {
  t(Fs(e));
  const r = new MutationObserver(() => t(Fs(e)));
  return r.observe(e, { childList: !0, subtree: !0, characterData: !0, attributes: !0, attributeFilter: ["slot"] }), () => r.disconnect();
}
function Un(e, t, r) {
  e?.dispatchEvent(new CustomEvent(t, { detail: r, bubbles: !0, composed: !0 }));
}
const Ul = (e) => {
  var t = ke(), r = re(t);
  ot(r, () => yt), k(e, t);
}, Yl = (e) => {
  var t = ke(), r = re(t);
  ot(r, () => yt, !1, (n, s) => {
    _e(n, () => ({ name: "icon" }));
  }), k(e, t);
};
function io(e, t) {
  Ce(t, !0);
  let r = x(t, "variant", 7), n = x(t, "tone", 7), s = x(t, "size", 7), a = x(t, "dot", 7, !1), o = /* @__PURE__ */ xe(!1);
  const i = Ot((f) => dn(f, (d) => ve(o, d.has("icon"), !0)));
  var l = {
    get variant() {
      return r();
    },
    set variant(f) {
      r(f), I();
    },
    get tone() {
      return n();
    },
    set tone(f) {
      n(f), I();
    },
    get size() {
      return s();
    },
    set size(f) {
      s(f), I();
    },
    get dot() {
      return a();
    },
    set dot(f = !1) {
      a(f), I();
    }
  };
  {
    let f = /* @__PURE__ */ F(() => c(o) ? Yl : void 0);
    Fl(e, {
      get variant() {
        return r();
      },
      get tone() {
        return n();
      },
      get size() {
        return s();
      },
      get dot() {
        return a();
      },
      get children() {
        return Ul;
      },
      get icon() {
        return c(f);
      },
      [Rt()]: (d) => (i || We)(d)
    });
  }
  return $e(l);
}
customElements.define("sky-badge", Lt(
  io,
  {
    variant: { type: "String" },
    tone: { type: "String" },
    size: { type: "String" },
    dot: { type: "Boolean" }
  },
  [],
  [],
  { mode: "open" }
));
var Vl = /* @__PURE__ */ _t('<svg class="sky-spinner svelte-1jua4x2" viewBox="0 0 16 16" fill="none" aria-hidden="true" focusable="false"><circle cx="8" cy="8" r="6" stroke="currentColor" stroke-opacity="0.3" stroke-width="2"></circle><path d="M8 2a6 6 0 0 1 6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round"></path></svg>');
const ql = {
  hash: "svelte-1jua4x2",
  code: `.sky-spinner.svelte-1jua4x2 {flex-shrink:0;}
  @media (prefers-reduced-motion: no-preference) {.sky-spinner.svelte-1jua4x2 {
      animation: svelte-1jua4x2-sky-spin 0.8s linear infinite;}
  }
  @keyframes svelte-1jua4x2-sky-spin {
    to {
      transform: rotate(360deg);
    }
  }`
};
function Hs(e, t) {
  Ge(e, ql);
  let r = x(t, "size", 3, 15);
  var n = Vl();
  W(() => {
    L(n, "width", r()), L(n, "height", r());
  }), k(e, n);
}
var Wl = /* @__PURE__ */ new Set([
  "$$slots",
  "$$events",
  "$$legacy",
  "variant",
  "tone",
  "size",
  "type",
  "disabled",
  "loading",
  "href",
  "block",
  "icon",
  "iconEnd",
  "children",
  "onclick"
]), Fr = /* @__PURE__ */ O('<span class="sky-button__icon svelte-yayskl"><!></span>'), js = /* @__PURE__ */ O('<span class="sky-button__label svelte-yayskl"><!></span>'), Kl = /* @__PURE__ */ O("<a><!> <!> <!></a>"), Gl = /* @__PURE__ */ O("<button><!> <!> <!></button>");
const Xl = {
  hash: "svelte-yayskl",
  code: `.sky-button.svelte-yayskl {--_bg: var(--sky-color-control);--_fg: var(--ds-color-fg);--_border: var(--sky-color-border-strong);--_shadow: var(--sky-shadow-raised);--_hover-bg: var(--sky-color-control-hover);--_hover-border: var(--sky-color-border-hover);--_h: var(--sky-size-control-md);display:inline-flex;align-items:center;justify-content:center;gap:var(--ds-space-2);box-sizing:border-box;height:var(--_h);min-width:0;padding:0 var(--ds-space-4);border:var(--ds-border-width) solid var(--_border);border-radius:var(--sky-radius-control);background:var(--_bg);box-shadow:var(--_shadow);color:var(--_fg);font-family:inherit;font-size:0.84375rem; /* 13.5 */font-weight:var(--ds-font-weight-semibold);line-height:1;text-decoration:none;white-space:nowrap;cursor:pointer;user-select:none;-webkit-tap-highlight-color:transparent;transition:background-color var(--sky-duration-fast) var(--sky-ease-out),
      border-color var(--sky-duration-fast) var(--sky-ease-out),
      filter var(--sky-duration-fast) var(--sky-ease-out);}.sky-button__label.svelte-yayskl {overflow:hidden;text-overflow:ellipsis;}.sky-button__icon.svelte-yayskl {display:flex;flex-shrink:0;}

  /* ---- Sizes ---- */.sky-button[data-size='sm'].svelte-yayskl {--_h: var(--sky-size-control-sm);padding:0 var(--ds-space-3);border-radius:var(--ds-radius-md);font-size:var(--sky-text-data);}.sky-button[data-size='lg'].svelte-yayskl {--_h: var(--sky-size-control-lg);border-radius:var(--sky-radius-row);font-size:var(--sky-text-body);}.sky-button[data-icon-only].svelte-yayskl {width:var(--_h);padding:0;}.sky-button[data-block].svelte-yayskl {display:flex;width:100%;}

  /* ---- Variants x tones ---- */.sky-button[data-variant='solid'][data-tone='accent'].svelte-yayskl {--_bg: var(--sky-color-accent-solid);--_fg: var(--sky-color-accent-solid-contrast);--_border: transparent;--_shadow: var(--sky-shadow-glow);--_hover-bg: var(--sky-color-accent-solid);--_hover-border: transparent;}.sky-button[data-variant='solid'][data-tone='neutral'].svelte-yayskl {--_bg: var(--ds-color-fg);--_fg: var(--ds-color-bg);--_border: transparent;--_hover-bg: var(--ds-color-fg);--_hover-border: transparent;}.sky-button[data-variant='solid'][data-tone='danger'].svelte-yayskl {--_bg: var(--ds-color-danger);--_fg: var(--ds-color-bg);--_border: transparent;--_hover-bg: var(--ds-color-danger);--_hover-border: transparent;}.sky-button[data-variant='solid'][data-tone='warning'].svelte-yayskl {--_bg: var(--ds-color-warning);--_fg: var(--ds-color-bg);--_border: transparent;--_hover-bg: var(--ds-color-warning);--_hover-border: transparent;}.sky-button[data-variant='solid'][data-tone='success'].svelte-yayskl {--_bg: var(--ds-color-success);--_fg: var(--ds-color-bg);--_border: transparent;--_hover-bg: var(--ds-color-success);--_hover-border: transparent;}.sky-button[data-variant='solid'].svelte-yayskl:hover:not(:disabled, [aria-disabled='true']) {filter:brightness(1.12);}.sky-button[data-variant='outline'][data-tone='accent'].svelte-yayskl {--_fg: var(--sky-color-accent-soft-fg);--_border: var(--sky-color-accent-ring);--_hover-border: var(--ds-color-accent);}.sky-button[data-variant='outline'][data-tone='danger'].svelte-yayskl {--_bg: var(--sky-color-danger-soft);--_fg: var(--sky-color-danger-soft-fg);--_border: color-mix(in oklab, var(--ds-color-danger) 28%, var(--ds-color-bg));--_shadow: none;--_hover-bg: color-mix(in oklab, var(--ds-color-danger) 16%, var(--sky-color-danger-soft));--_hover-border: color-mix(in oklab, var(--ds-color-danger) 50%, var(--ds-color-bg));}.sky-button[data-variant='outline'][data-tone='warning'].svelte-yayskl {--_bg: var(--sky-color-warning-soft);--_fg: var(--sky-color-warning-soft-fg);--_border: color-mix(in oklab, var(--ds-color-warning) 28%, var(--ds-color-bg));--_shadow: none;--_hover-border: color-mix(in oklab, var(--ds-color-warning) 50%, var(--ds-color-bg));}.sky-button[data-variant='outline'][data-tone='success'].svelte-yayskl {--_fg: var(--ds-color-success);--_border: color-mix(in oklab, var(--ds-color-success) 35%, var(--ds-color-bg));}.sky-button[data-variant='ghost'].svelte-yayskl {--_bg: transparent;--_fg: var(--ds-color-text-muted);--_border: transparent;--_shadow: none;--_hover-border: transparent;}.sky-button[data-variant='ghost'][data-tone='accent'].svelte-yayskl {--_fg: var(--ds-color-accent);}.sky-button[data-variant='ghost'][data-tone='danger'].svelte-yayskl {--_fg: var(--sky-color-danger-soft-fg);--_hover-bg: var(--sky-color-danger-soft);}.sky-button[data-variant='ghost'][data-tone='warning'].svelte-yayskl {--_fg: var(--sky-color-warning-soft-fg);--_hover-bg: var(--sky-color-warning-soft);}.sky-button[data-variant='ghost'][data-tone='success'].svelte-yayskl {--_fg: var(--ds-color-success);}.sky-button[data-variant='ghost'].svelte-yayskl:hover:not(:disabled, [aria-disabled='true']) {color:var(--ds-color-fg);}

  /* ---- States ---- */.sky-button.svelte-yayskl:hover:not(:disabled, [aria-disabled='true']) {background:var(--_hover-bg);border-color:var(--_hover-border);}.sky-button.svelte-yayskl:active:not(:disabled, [aria-disabled='true']) {filter:brightness(0.88);box-shadow:none;}.sky-button.svelte-yayskl:focus-visible {outline:var(--sky-focus-ring-width) solid var(--sky-color-focus);outline-offset:var(--sky-focus-ring-offset);}.sky-button.svelte-yayskl:disabled {opacity:0.4;cursor:not-allowed;}.sky-button[aria-busy='true'].svelte-yayskl {cursor:progress;}

  @media (pointer: coarse) {.sky-button.svelte-yayskl {min-height:var(--sky-size-touch);}.sky-button[data-icon-only].svelte-yayskl {min-width:var(--sky-size-touch);}
  }`
};
function Jl(e, t) {
  Ce(t, !0), Ge(e, Xl);
  let r = x(t, "variant", 3, "outline"), n = x(t, "size", 3, "md"), s = x(t, "type", 3, "button"), a = x(t, "disabled", 3, !1), o = x(t, "loading", 3, !1), i = x(t, "block", 3, !1), l = /* @__PURE__ */ wt(t, Wl);
  const f = /* @__PURE__ */ F(() => t.tone ?? (r() === "solid" ? "accent" : "neutral")), d = /* @__PURE__ */ F(() => !t.children && !!(t.icon || o()));
  function v(g) {
    if (o()) {
      g.preventDefault();
      return;
    }
    t.onclick?.(g);
  }
  var h = ke(), _ = re(h);
  {
    var u = (g) => {
      var b = Kl(), A = (p) => {
        o() ? p.preventDefault() : t.onclick?.(p);
      };
      _e(
        b,
        () => ({
          ...l,
          class: "sky-button",
          href: t.href,
          "data-variant": r(),
          "data-tone": c(f),
          "data-size": n(),
          "data-icon-only": c(d) || void 0,
          "data-block": i() || void 0,
          "aria-busy": o() || void 0,
          "aria-disabled": o() || void 0,
          onclick: A
        }),
        void 0,
        void 0,
        void 0,
        "svelte-yayskl"
      );
      var R = z(b);
      {
        var w = (p) => {
          Hs(p, {});
        }, q = (p) => {
          var C = Fr(), K = z(C);
          Le(K, () => t.icon), S(C), k(p, C);
        };
        U(R, (p) => {
          o() ? p(w) : t.icon && p(q, 1);
        });
      }
      var N = E(R, 2);
      {
        var M = (p) => {
          var C = js(), K = z(C);
          Le(K, () => t.children), S(C), k(p, C);
        };
        U(N, (p) => {
          t.children && p(M);
        });
      }
      var H = E(N, 2);
      {
        var T = (p) => {
          var C = Fr(), K = z(C);
          Le(K, () => t.iconEnd), S(C), k(p, C);
        };
        U(H, (p) => {
          t.iconEnd && p(T);
        });
      }
      S(b), k(g, b);
    }, y = (g) => {
      var b = Gl();
      _e(
        b,
        () => ({
          ...l,
          class: "sky-button",
          type: s(),
          disabled: a(),
          "data-variant": r(),
          "data-tone": c(f),
          "data-size": n(),
          "data-icon-only": c(d) || void 0,
          "data-block": i() || void 0,
          "aria-busy": o() || void 0,
          "aria-disabled": o() || void 0,
          onclick: v
        }),
        void 0,
        void 0,
        void 0,
        "svelte-yayskl"
      );
      var A = z(b);
      {
        var R = (T) => {
          Hs(T, {});
        }, w = (T) => {
          var p = Fr(), C = z(p);
          Le(C, () => t.icon), S(p), k(T, p);
        };
        U(A, (T) => {
          o() ? T(R) : t.icon && T(w, 1);
        });
      }
      var q = E(A, 2);
      {
        var N = (T) => {
          var p = js(), C = z(p);
          Le(C, () => t.children), S(p), k(T, p);
        };
        U(q, (T) => {
          t.children && T(N);
        });
      }
      var M = E(q, 2);
      {
        var H = (T) => {
          var p = Fr(), C = z(p);
          Le(C, () => t.iconEnd), S(p), k(T, p);
        };
        U(M, (T) => {
          t.iconEnd && T(H);
        });
      }
      S(b), k(g, b);
    };
    U(_, (g) => {
      t.href && !a() ? g(u) : g(y, -1);
    });
  }
  k(e, h), $e();
}
const Zl = (e) => {
  var t = ke(), r = re(t);
  ot(r, () => yt), k(e, t);
}, Ql = (e) => {
  var t = ke(), r = re(t);
  ot(r, () => yt, !1, (n, s) => {
    _e(n, () => ({ name: "icon" }));
  }), k(e, t);
}, ed = (e) => {
  var t = ke(), r = re(t);
  ot(r, () => yt, !1, (n, s) => {
    _e(n, () => ({ name: "icon-end" }));
  }), k(e, t);
};
function lo(e, t) {
  Ce(t, !0);
  let r = x(t, "variant", 7), n = x(t, "tone", 7), s = x(t, "size", 7), a = x(t, "type", 7, "button"), o = x(t, "href", 7), i = x(t, "label", 7), l = x(t, "disabled", 7, !1), f = x(t, "loading", 7, !1), d = x(t, "block", 7, !1), v = /* @__PURE__ */ xe(Et(/* @__PURE__ */ new Set([""])));
  const h = Ot((u) => dn(u, (y) => ve(v, y, !0)));
  var _ = {
    get variant() {
      return r();
    },
    set variant(u) {
      r(u), I();
    },
    get tone() {
      return n();
    },
    set tone(u) {
      n(u), I();
    },
    get size() {
      return s();
    },
    set size(u) {
      s(u), I();
    },
    get type() {
      return a();
    },
    set type(u = "button") {
      a(u), I();
    },
    get href() {
      return o();
    },
    set href(u) {
      o(u), I();
    },
    get label() {
      return i();
    },
    set label(u) {
      i(u), I();
    },
    get disabled() {
      return l();
    },
    set disabled(u = !1) {
      l(u), I();
    },
    get loading() {
      return f();
    },
    set loading(u = !1) {
      f(u), I();
    },
    get block() {
      return d();
    },
    set block(u = !1) {
      d(u), I();
    }
  };
  {
    let u = /* @__PURE__ */ F(() => c(v).has("") ? Zl : void 0), y = /* @__PURE__ */ F(() => c(v).has("icon") ? Ql : void 0), g = /* @__PURE__ */ F(() => c(v).has("icon-end") ? ed : void 0);
    Jl(e, {
      get variant() {
        return r();
      },
      get tone() {
        return n();
      },
      get size() {
        return s();
      },
      get type() {
        return a();
      },
      get href() {
        return o();
      },
      get disabled() {
        return l();
      },
      get loading() {
        return f();
      },
      get block() {
        return d();
      },
      get "aria-label"() {
        return i();
      },
      get children() {
        return c(u);
      },
      get icon() {
        return c(y);
      },
      get iconEnd() {
        return c(g);
      },
      [Rt()]: (b) => (h || We)(b)
    });
  }
  return $e(_);
}
customElements.define("sky-button", Lt(
  lo,
  {
    variant: { type: "String" },
    tone: { type: "String" },
    size: { type: "String" },
    type: { type: "String" },
    href: { type: "String" },
    label: { type: "String" },
    disabled: { type: "Boolean" },
    loading: { type: "Boolean" },
    block: { type: "Boolean" }
  },
  [],
  [],
  { mode: "open" }
));
var td = /* @__PURE__ */ new Set([
  "$$slots",
  "$$events",
  "$$legacy",
  "variant",
  "padding",
  "interactive",
  "selected",
  "href",
  "as",
  "children"
]), rd = /* @__PURE__ */ O("<a><!></a>");
const nd = {
  hash: "svelte-hubdo1",
  code: `.sky-card.svelte-hubdo1 {display:block;box-sizing:border-box;min-width:0;border:var(--ds-border-width) solid var(--ds-color-border);border-radius:var(--sky-radius-xl);background:var(--ds-color-surface);box-shadow:var(--sky-shadow-raised);color:inherit;text-decoration:none;container-type:inline-size;transition:border-color var(--sky-duration-fast) var(--sky-ease-out),
      background-color var(--sky-duration-fast) var(--sky-ease-out);}.sky-card[data-padding='sm'].svelte-hubdo1 {padding:var(--ds-space-3) var(--ds-space-3-5);}.sky-card[data-padding='md'].svelte-hubdo1 {padding:var(--ds-space-4);}.sky-card[data-padding='lg'].svelte-hubdo1 {padding:var(--ds-space-5);}.sky-card[data-variant='header'].svelte-hubdo1 {border-radius:var(--sky-radius-2xl);background:radial-gradient(60% 130% at 100% 0%, var(--sky-color-hero-glow), transparent 70%),
      var(--ds-color-surface);box-shadow:var(--sky-shadow-raised-strong);}.sky-card[data-variant='raised'].svelte-hubdo1 {background:var(--ds-color-surface-raised);box-shadow:var(--sky-shadow-selected);}.sky-card[data-selected].svelte-hubdo1 {border-color:color-mix(in oklab, var(--ds-color-accent) 60%, var(--ds-color-border));background:var(--ds-color-surface-raised);box-shadow:var(--sky-shadow-selected),
      0 16px 40px -24px var(--ds-color-accent);}.sky-card[data-interactive].svelte-hubdo1 {cursor:pointer;}.sky-card[data-interactive].svelte-hubdo1:hover {border-color:var(--sky-color-border-hover);}.sky-card.svelte-hubdo1:focus-visible {outline:var(--sky-focus-ring-width) solid var(--sky-color-focus);outline-offset:var(--sky-focus-ring-offset);}

  @media (min-width: 48rem) {.sky-card[data-padding='md'].svelte-hubdo1 {padding:var(--ds-space-5) var(--ds-space-6);}.sky-card[data-padding='lg'].svelte-hubdo1 {padding:var(--ds-space-8) var(--ds-space-9);}
  }`
};
function sd(e, t) {
  Ge(e, nd);
  let r = x(t, "variant", 3, "standard"), n = x(t, "padding", 3, "md"), s = x(t, "interactive", 3, !1), a = x(t, "selected", 3, !1), o = x(t, "as", 3, "div"), i = /* @__PURE__ */ wt(t, td);
  var l = ke(), f = re(l);
  {
    var d = (h) => {
      var _ = rd();
      _e(
        _,
        () => ({
          ...i,
          class: "sky-card",
          href: t.href,
          "data-variant": r(),
          "data-padding": n(),
          "data-interactive": "",
          "data-selected": a() || void 0
        }),
        void 0,
        void 0,
        void 0,
        "svelte-hubdo1"
      );
      var u = z(_);
      Le(u, () => t.children ?? We), S(_), k(h, _);
    }, v = (h) => {
      var _ = ke(), u = re(_);
      ot(u, o, !1, (y, g) => {
        _e(
          y,
          () => ({
            ...i,
            class: "sky-card",
            "data-variant": r(),
            "data-padding": n(),
            "data-interactive": s() || void 0,
            "data-selected": a() || void 0
          }),
          void 0,
          void 0,
          void 0,
          "svelte-hubdo1"
        );
        var b = ke(), A = re(b);
        Le(A, () => t.children ?? We), k(g, b);
      }), k(h, _);
    };
    U(f, (h) => {
      t.href ? h(d) : h(v, -1);
    });
  }
  k(e, l);
}
const ad = (e) => {
  var t = ke(), r = re(t);
  ot(r, () => yt), k(e, t);
};
function co(e, t) {
  Ce(t, !0);
  let r = x(t, "variant", 7), n = x(t, "padding", 7), s = x(t, "href", 7), a = x(t, "as", 7), o = x(t, "interactive", 7, !1), i = x(t, "selected", 7, !1);
  const l = Ot(void 0, { block: !0 });
  var f = {
    get variant() {
      return r();
    },
    set variant(d) {
      r(d), I();
    },
    get padding() {
      return n();
    },
    set padding(d) {
      n(d), I();
    },
    get href() {
      return s();
    },
    set href(d) {
      s(d), I();
    },
    get as() {
      return a();
    },
    set as(d) {
      a(d), I();
    },
    get interactive() {
      return o();
    },
    set interactive(d = !1) {
      o(d), I();
    },
    get selected() {
      return i();
    },
    set selected(d = !1) {
      i(d), I();
    }
  };
  return sd(e, {
    get variant() {
      return r();
    },
    get padding() {
      return n();
    },
    get href() {
      return s();
    },
    get as() {
      return a();
    },
    get interactive() {
      return o();
    },
    get selected() {
      return i();
    },
    get children() {
      return ad;
    },
    [Rt()]: (d) => (l || We)(d)
  }), $e(f);
}
customElements.define("sky-card", Lt(
  co,
  {
    variant: { type: "String" },
    padding: { type: "String" },
    href: { type: "String" },
    as: { type: "String" },
    interactive: { type: "Boolean" },
    selected: { type: "Boolean" }
  },
  [],
  [],
  { mode: "open" }
));
function Pe(e) {
  return Math.round(e * 100) / 100;
}
function En(e) {
  return e.length === 0 ? "" : "M" + e.map(([t, r]) => `${Pe(t)},${Pe(r)}`).join("L") + "Z";
}
function od(e = "var(--ds-color-accent)", t = {}) {
  const r = t.light ?? "var(--ds-color-fg)", n = t.shade ?? "var(--ds-color-bg)", s = t.topMix ?? 58, a = t.sideMix ?? 50;
  return {
    front: e,
    top: `color-mix(in oklab, ${e} ${s}%, ${r})`,
    side: `color-mix(in oklab, ${e} ${a}%, ${n})`
  };
}
function us(e) {
  const { x: t, y: r, width: n, height: s, dx: a, dy: o } = e, i = [[t, r], [t + n, r], [t + n, r - s], [t, r - s]], l = [[t + n, r], [t + n + a, r - o], [t + n + a, r - o - s], [t + n, r - s]], f = [[t, r - s], [t + n, r - s], [t + n + a, r - s - o], [t + a, r - s - o]];
  return {
    front: s > 0 ? En(i) : "",
    side: s > 0 ? En(l) : "",
    top: En(f)
  };
}
function Bs(e) {
  return us({ ...e, height: 0 }).top;
}
function id(e, t, r, n = 0) {
  return e <= 0 || t <= 0 ? 0 : Math.max(n, Math.round(r * Math.sqrt(Math.min(e, t) / t)));
}
const fs = {
  week: 18,
  bar: 12,
  rowDx: 8,
  rowDy: 6.5,
  depthX: 5.6,
  depthY: 4.55,
  originX: 20,
  groundY: 160,
  maxHeight: 90,
  minHeight: 12,
  hitMin: 22,
  hitPad: 3,
  labelY: 182,
  leadY: -14,
  viewBox: { x: 0, y: -30, width: 1040, height: 220 }
}, ld = {
  week: 19.3,
  bar: 13.5,
  rowDx: 6,
  rowDy: 5,
  depthX: 4.2,
  depthY: 3.5,
  originX: 6,
  groundY: 118,
  maxHeight: 72,
  minHeight: 11,
  hitMin: 30,
  hitPad: 3,
  labelY: 140,
  leadY: 0,
  viewBox: { x: 0, y: 0, width: 350, height: 146 }
}, uo = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"], cn = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], Yn = 864e5;
function Tt(e) {
  const t = /^(\d{4})-(\d{2})-(\d{2})/.exec(e);
  return t ? Date.UTC(Number(t[1]), Number(t[2]) - 1, Number(t[3])) : Number.NaN;
}
function vs(e) {
  return new Date(e).toISOString().slice(0, 10);
}
function Vn(e, t) {
  return vs(Tt(e) + t * Yn);
}
function dd(e) {
  return new Date(Tt(e)).getUTCDay();
}
function fo(e) {
  return Vn(e, -dd(e));
}
function cd(e) {
  return { start: `${e}-01-01`, end: `${e}-12-31` };
}
function ud(e, t = 16) {
  const r = fo(e);
  return { start: Vn(r, -7 * (t - 1)), end: Vn(r, 6) };
}
function fd(e) {
  const t = new Date(Tt(e));
  return `${uo[t.getUTCDay()]}, ${cn[t.getUTCMonth()]} ${t.getUTCDate()}`;
}
function vo(e) {
  return e === 1 ? "session" : "sessions";
}
function vd(e) {
  const t = e.dims ?? fs, { week: r, bar: n, rowDx: s, rowDy: a, depthX: o, depthY: i, originX: l, groundY: f } = t, d = /* @__PURE__ */ new Map();
  let v = 0;
  for (const M of e.days)
    M.sessions > 0 && (d.set(M.date.slice(0, 10), M), v = Math.max(v, M.sessions));
  const h = e.maxSessions ?? v, _ = Tt(e.range.start), u = Tt(e.range.end), y = Tt(e.today), g = Tt(fo(e.range.start)), b = Array.from({ length: 7 }, () => ({ front: [], side: [], top: [] })), A = [], R = [], w = [], q = [];
  if (Number.isFinite(_) && Number.isFinite(u) && u >= _) {
    const M = Math.round((u - g) / Yn);
    for (let H = 0; H <= M; H++) {
      const T = g + H * Yn;
      if (T < _) continue;
      const p = Math.floor(H / 7), K = 6 - H % 7, Q = l + p * r + K * s, G = f - K * a, ie = vs(T), le = new Date(T);
      le.getUTCDate() === 1 && q.push({ x: Pe(l + p * r), y: t.labelY, label: cn[le.getUTCMonth()] ?? "" });
      const fe = { x: Q, y: G, width: n, dx: o, dy: i }, de = d.get(ie);
      if (T > y)
        R.push(Bs(fe));
      else if (!de)
        A.push(Bs(fe));
      else {
        const me = id(de.sessions, h, t.maxHeight, t.minHeight), Te = us({ ...fe, height: me });
        b[K].front.push(Te.front), b[K].side.push(Te.side), b[K].top.push(Te.top);
        const ee = t.hitPad, te = G + ee;
        let se = G - me - i - ee;
        te - se < t.hitMin && (se = te - t.hitMin), w.push({
          date: ie,
          day: de,
          index: w.length,
          row: K,
          x: Q,
          y: G,
          height: me,
          paths: Te,
          anchor: { x: Pe(Q + (n + o) / 2), y: Pe(G - me - i / 2) },
          hit: { x: Pe(Q - ee), y: Pe(se), width: Pe(n + o + ee * 2), height: Pe(te - se), z: 10 - K },
          label: `${fd(ie)}: ${de.sessions} ${vo(de.sessions)}`
        });
      }
    }
  }
  const N = t.viewBox;
  return {
    dims: t,
    viewBox: `${N.x} ${N.y} ${N.width} ${N.height}`,
    floor: A.join(""),
    future: R.join(""),
    rows: b.map((M) => ({ front: M.front.join(""), side: M.side.join(""), top: M.top.join("") })),
    bars: w,
    months: q,
    maxSessions: h
  };
}
function hd(e, t, r = fs) {
  return `M${e.anchor.x},${e.anchor.y}V${r.leadY}H${Pe(t)}`;
}
function _d(e, t) {
  const r = t.viewBox, n = (s, a) => `${Pe(s / a * 100)}%`;
  return {
    left: n(e.x - r.x, r.width),
    top: n(e.y - r.y, r.height),
    width: n(e.width, r.width),
    height: n(e.height, r.height)
  };
}
function yd(e, t) {
  const r = e.bars.length;
  if (r === 0) return `Activity skyline for ${t}. No sessions yet.`;
  const n = e.bars[0], s = e.bars[r - 1], a = e.bars.reduce((u, y) => y.day.sessions > u.day.sessions ? y : u), [, o, i] = /^\d{4}-(\d{2})-(\d{2})/.exec(n.date) ?? [], [, l, f] = /^\d{4}-(\d{2})-(\d{2})/.exec(s.date) ?? [], d = (u, y) => `${cn[Number(u) - 1] ?? ""} ${Number(y)}`, [, v, h] = /^\d{4}-(\d{2})-(\d{2})/.exec(a.date) ?? [], _ = r === 1 ? `One active day, ${d(o, i)}` : `${r} active days run from ${d(o, i)} to ${d(l, f)}`;
  return `Activity skyline for ${t}. ${_}, and ${d(v, h)} is the tallest with ${a.day.sessions} ${vo(a.day.sessions)}.`;
}
const Us = (e) => Math.round(e * 10) / 10;
function gd(e, t, r) {
  const n = e.length;
  if (n === 0) return [];
  if (r * n >= t) return e.map(() => Us(t / n));
  const s = /* @__PURE__ */ new Set();
  for (; ; ) {
    const a = e.reduce((l, f, d) => s.has(d) ? l : l + Math.max(0, f), 0), o = t - s.size * r;
    let i = !1;
    for (let l = 0; l < n; l++) {
      if (s.has(l)) continue;
      (a > 0 ? Math.max(0, e[l]) / a * o : o / (n - s.size)) < r && (s.add(l), i = !0);
    }
    if (!i)
      return e.map((l, f) => s.has(f) ? r : Us(a > 0 ? Math.max(0, l) / a * o : o / (n - s.size)));
  }
}
const pd = { width: 1e3, height: 46, dx: 16, dy: 12, gap: 4, minWidth: 8 };
function bd(e, t = pd) {
  const r = e.filter((f) => typeof f.value == "number" && f.value > 0), n = r.reduce((f, d) => f + d.value, 0), s = t.width - t.dx - t.gap * Math.max(0, r.length - 1), a = gd(
    r.map((f) => f.value),
    s,
    t.minWidth
  ), o = t.height - t.dy;
  let i = 0;
  const l = r.map((f, d) => {
    const v = a[d], h = {
      key: f.key,
      value: f.value,
      share: n > 0 ? f.value / n : 0,
      x: Pe(i),
      width: v,
      paths: us({ x: i, y: t.height - 2, width: v, height: o - 2, dx: t.dx, dy: t.dy })
    };
    return i = Pe(i + v + t.gap), h;
  });
  return { viewBox: `0 0 ${t.width} ${t.height}`, segments: l, total: n };
}
const kd = {
  completed: { label: "Completed", variant: "soft", tone: "accent", glyph: "check", live: !1, terminal: !0 },
  failed: { label: "Failed", variant: "soft", tone: "danger", glyph: "cross", live: !1, terminal: !0 },
  cancelled: { label: "Cancelled", variant: "outline", tone: "neutral", glyph: "dash", live: !1, terminal: !0 },
  interrupted: { label: "Interrupted", variant: "outline", tone: "warning", glyph: "pause", live: !1, terminal: !0 },
  running: { label: "Running", variant: "soft", tone: "accent", glyph: "spinner", live: !0, terminal: !1 },
  pending: { label: "Pending", variant: "outline", tone: "neutral", glyph: "clock", live: !1, terminal: !1 },
  skipped: { label: "Skipped", variant: "outline", tone: "neutral", glyph: "skip", live: !1, terminal: !0 },
  unknown: { label: "Unknown", variant: "outline", tone: "neutral", glyph: "dot", live: !1, terminal: !1 }
}, md = {
  completed: "completed",
  succeeded: "completed",
  success: "completed",
  passed: "completed",
  failed: "failed",
  error: "failed",
  cancelled: "cancelled",
  canceled: "cancelled",
  interrupted: "interrupted",
  running: "running",
  in_progress: "running",
  started: "running",
  active: "running",
  pending: "pending",
  queued: "pending",
  not_started: "pending",
  skipped: "skipped"
};
function wd(e) {
  return e ? md[e.toLowerCase()] ?? "unknown" : "unknown";
}
function xd(e) {
  const t = wd(e), r = kd[t];
  let n = r.label;
  return t === "unknown" && e ? n = Sd(e) : e?.toLowerCase() === "queued" && (n = "Queued"), { kind: t, ...r, label: n };
}
function Sd(e) {
  const t = e.replace(/[_-]+/g, " ").trim();
  return t.charAt(0).toUpperCase() + t.slice(1).toLowerCase();
}
const Ed = {
  check: "M3.5 8.5l3 3 6-7",
  cross: "M4.5 4.5l7 7M11.5 4.5l-7 7",
  dash: "M3.5 8h9",
  // A three-quarter arc; the badge spins it unless reduced motion.
  spinner: "M8 2.75a5.25 5.25 0 1 1-5.25 5.25",
  clock: "M8 2.75a5.25 5.25 0 1 0 0 10.5a5.25 5.25 0 1 0 0-10.5M8 5v3.25l2 1.25",
  pause: "M6 4v8M10 4v8",
  skip: "M4 4l5 4-5 4M11.5 4v8",
  dot: "M8 7.25v1.5"
}, Jr = {
  chevronLeft: "M10 3.5L5.5 8l4.5 4.5",
  chevronRight: "M6 3.5L10.5 8 6 12.5"
}, Wt = "—";
function Lr(e) {
  if (e == null || e === "") return null;
  const t = typeof e == "string" ? Number(e) : e;
  return Number.isFinite(t) ? t : null;
}
const ho = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
function Td(e) {
  const t = Lr(e);
  return t === null || t < 0 ? Wt : t === 0 ? "$0.00" : t < 0.01 ? "<$0.01" : `$${ho.format(t)}`;
}
function Ys(e) {
  const t = Lr(e);
  return t === null || t < 0 ? Wt : t < 0.01 ? `$${t.toFixed(6)}` : t < 1 ? `$${t.toFixed(4)}` : `$${ho.format(t)}`;
}
const Vs = [
  { suffix: "k", size: 1e3, key: "k" },
  { suffix: "M", size: 1e6, key: "m" },
  { suffix: "B", size: 1e9, key: "m" }
];
function qn(e, t = {}) {
  const r = Lr(e);
  if (r === null || r < 0) return Wt;
  if (r < 1e3) return String(Math.round(r));
  const n = t.case === "upper", s = Vs.length - 1;
  for (const [a, o] of Vs.entries()) {
    const i = o.key === "k" ? t.digits?.k ?? 1 : t.digits?.m ?? 2, l = 10 ** i, f = Math.round(r / o.size * l) / l;
    if (f < 1e3 || a === s) {
      const d = n ? o.suffix.toUpperCase() : o.suffix;
      return `${f.toFixed(i)}${d}`;
    }
  }
  return String(r);
}
const Zr = [
  { key: "cacheRead", label: "Cache read", token: "--sky-color-data-1" },
  { key: "cacheWrite", label: "Cache write", token: "--sky-color-data-2" },
  { key: "output", label: "Output", token: "--sky-color-data-3" },
  { key: "input", label: "Input", token: "--sky-color-data-4" }
], Tn = (e) => typeof e == "number" && Number.isFinite(e) ? String(Math.round(e)) : "0";
function zd(e) {
  const t = new Date(Tt(e.date)), r = e.tokens ?? { input: 0, output: 0, cacheWrite: 0, cacheRead: 0 }, n = r.input + r.output + r.cacheWrite + r.cacheRead, s = Zr.map((a) => ({
    key: a.key,
    label: a.label,
    token: a.token,
    value: r[a.key],
    display: qn(r[a.key], { case: "upper" }),
    flex: Math.max(r[a.key], n * 8e-3)
  }));
  return {
    date: e.date,
    dateLabel: `${uo[t.getUTCDay()]}, ${cn[t.getUTCMonth()]} ${t.getUTCDate()}`,
    year: String(t.getUTCFullYear()),
    sessions: Tn(e.sessions),
    executions: Tn(e.executions),
    commits: Tn(e.commits),
    tokens: qn(n, { case: "upper" }),
    cost: e.costUsd === null || e.costUsd === void 0 ? "—" : Td(e.costUsd),
    parts: s,
    hasTokens: n > 0
  };
}
const Ad = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
function Md(e) {
  const t = Lr(e);
  return t === null ? Wt : Ad.format(Math.round(t));
}
function Cd(e, t = 0) {
  const r = Lr(e);
  return r === null ? Wt : `${(r * 100).toFixed(t)}%`;
}
function $d(e) {
  const t = e.tokens, r = t.input + t.output + t.cacheWrite + t.cacheRead, n = Zr.filter((l) => t[l.key] > 0).map((l) => {
    const f = r > 0 ? t[l.key] / r : 0, d = { key: l.key, label: l.label, token: l.token, value: t[l.key], display: Md(t[l.key]), percent: Cd(f, 1) }, v = e.rates?.[l.key];
    return v && (d.rate = v), d;
  }), s = e.costRows.map((l) => typeof l.value == "number" && l.value > 0 ? l.value : 0), a = s.reduce((l, f) => l + f, 0), o = Math.max(0, ...s), i = e.costRows.map((l, f) => ({
    label: l.label,
    display: l.display ?? Ys(l.value),
    percent: a > 0 ? `${Math.round(s[f] / a * 100)}%` : "—",
    fill: o > 0 ? Math.round(s[f] / o * 100) : 0,
    tone: l.tone ?? (e.costBy === "phase" ? "accent" : "neutral")
  }));
  return {
    cost: e.cost ?? Ys(a),
    tokensTotal: r,
    tokensLabel: `${qn(r, { case: "upper" })} tokens`,
    series: n,
    costRows: i,
    bandLabel: r > 0 ? `Tokens by type: ${n.map((l) => `${l.label} ${l.percent.replace("%", " percent")}`).join(", ")}` : "No tokens recorded"
  };
}
const Nd = (e, t) => {
  const { count: r } = e;
  if (t.type === "resize") {
    if (t.count <= 0) return { index: null, count: 0 };
    const s = t.keep ?? null;
    return { index: s !== null && s >= 0 && s < t.count ? s : t.count - 1, count: t.count };
  }
  if (r <= 0) return e;
  const n = e.index ?? r - 1;
  switch (t.type) {
    case "prev":
      return { count: r, index: (n + r - 1) % r };
    case "next":
      return { count: r, index: (n + 1) % r };
    case "first":
      return { count: r, index: 0 };
    case "last":
      return { count: r, index: r - 1 };
    case "pick":
      return t.index >= 0 && t.index < r && t.index !== e.index ? { count: r, index: t.index } : e;
  }
};
function Rd(e) {
  return e.index === null || e.count === 0 ? "No active days" : `${e.index + 1} of ${e.count} active ${e.count === 1 ? "day" : "days"}`;
}
function Ld(e) {
  switch (e) {
    case "ArrowLeft":
    case "ArrowUp":
      return { type: "prev" };
    case "ArrowRight":
    case "ArrowDown":
      return { type: "next" };
    case "Home":
      return { type: "first" };
    case "End":
      return { type: "last" };
    default:
      return null;
  }
}
var Od = /* @__PURE__ */ _t('<svg class="sky-glyph svelte-14pvmyo" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path></path></svg>');
const Dd = {
  hash: "svelte-14pvmyo",
  code: ".sky-glyph.svelte-14pvmyo {flex-shrink:0;display:block;}"
};
function Er(e, t) {
  Ge(e, Dd);
  let r = x(t, "size", 3, 14), n = x(t, "weight", 3, 1.6);
  var s = Od(), a = ne(s);
  W(() => {
    L(s, "width", r()), L(s, "height", r()), L(s, "stroke-width", n()), L(a, "d", t.d);
  }), k(e, s);
}
var Id = /* @__PURE__ */ new Set([
  "$$slots",
  "$$events",
  "$$legacy",
  "day",
  "variant",
  "position",
  "onprev",
  "onnext",
  "runsHref"
]), Pd = /* @__PURE__ */ O('<span class="sky-readout__pos svelte-1wa8bs6"> </span>'), Fd = /* @__PURE__ */ O('<div class="sky-readout__stepper svelte-1wa8bs6"><button class="sky-readout__step svelte-1wa8bs6" type="button" aria-label="Previous active day"><!></button> <div class="sky-readout__when svelte-1wa8bs6"><span class="sky-readout__date svelte-1wa8bs6"> </span> <!></div> <button class="sky-readout__step svelte-1wa8bs6" type="button" aria-label="Next active day"><!></button></div>'), Hd = /* @__PURE__ */ O('<a class="sky-readout__runs svelte-1wa8bs6">Runs →</a>'), jd = /* @__PURE__ */ O('<div class="sky-readout__head svelte-1wa8bs6"><span class="sky-readout__date svelte-1wa8bs6"> <span class="sky-readout__year svelte-1wa8bs6"> </span></span> <!></div>'), Bd = /* @__PURE__ */ O('<span class="svelte-1wa8bs6"></span>'), Ud = /* @__PURE__ */ O('<li class="svelte-1wa8bs6"><span class="sky-readout__swatch svelte-1wa8bs6"></span> <span class="sky-readout__part-label svelte-1wa8bs6"> </span> <span class="sky-readout__part-value svelte-1wa8bs6"> </span></li>'), Yd = /* @__PURE__ */ O('<div class="sky-readout__split svelte-1wa8bs6" aria-hidden="true"></div> <ul class="sky-readout__parts svelte-1wa8bs6"></ul>', 1), Vd = /* @__PURE__ */ O('<span class="sky-readout__none svelte-1wa8bs6">No tokens recorded for this day.</span>'), qd = /* @__PURE__ */ O('<a class="sky-readout__runs-button svelte-1wa8bs6">Runs that day →</a>'), Wd = /* @__PURE__ */ O('<!> <dl class="sky-readout__stats svelte-1wa8bs6"><div class="svelte-1wa8bs6"><dt class="svelte-1wa8bs6">Sessions</dt><dd data-accent="" class="svelte-1wa8bs6"> </dd></div> <div class="svelte-1wa8bs6"><dt class="svelte-1wa8bs6">Executions</dt><dd class="svelte-1wa8bs6"> </dd></div> <div class="svelte-1wa8bs6"><dt class="svelte-1wa8bs6">Commits</dt><dd class="svelte-1wa8bs6"> </dd></div></dl> <div class="sky-readout__usage svelte-1wa8bs6"><div class="sky-readout__totals svelte-1wa8bs6"><span class="svelte-1wa8bs6"><span class="sky-readout__k svelte-1wa8bs6">Tokens</span><span class="sky-readout__v svelte-1wa8bs6"> </span></span> <span class="svelte-1wa8bs6"><span class="sky-readout__k svelte-1wa8bs6">Spend</span><span class="sky-readout__v svelte-1wa8bs6"> </span></span></div> <!></div> <!>', 1), Kd = /* @__PURE__ */ O('<span class="sky-readout__none svelte-1wa8bs6">No activity in this range yet.</span>'), Gd = /* @__PURE__ */ O("<div><!></div>");
const Xd = {
  hash: "svelte-1wa8bs6",
  code: `.sky-readout.svelte-1wa8bs6 {display:flex;flex-direction:column;gap:var(--ds-space-3);box-sizing:border-box;padding:var(--ds-space-3) var(--ds-space-3-5) var(--ds-space-3-5);border-radius:var(--ds-space-4);border:var(--ds-border-width) solid var(--sky-color-border-strong);background:var(--ds-color-surface-raised);box-shadow:var(--sky-shadow-selected);color:var(--ds-color-fg);}.sky-readout[data-variant='dock'].svelte-1wa8bs6 {padding:var(--ds-space-3-5) var(--ds-space-4);box-shadow:var(--sky-shadow-overlay);}.sky-readout__head.svelte-1wa8bs6 {display:flex;align-items:baseline;justify-content:space-between;gap:var(--ds-space-2-5);}.sky-readout__date.svelte-1wa8bs6 {font-size:var(--ds-text-lg);font-weight:var(--ds-font-weight-semibold);letter-spacing:-0.01em;}.sky-readout__year.svelte-1wa8bs6 {font-weight:var(--ds-font-weight-regular);color:var(--ds-color-text-subtle);}.sky-readout__runs.svelte-1wa8bs6 {font-size:var(--sky-text-data);font-weight:var(--ds-font-weight-semibold);color:var(--sky-color-accent-soft-fg);text-decoration:none;border-radius:var(--ds-radius-xs);}.sky-readout__runs.svelte-1wa8bs6:hover {text-decoration:underline;}.sky-readout__stepper.svelte-1wa8bs6 {display:flex;align-items:center;gap:var(--ds-space-2-5);}.sky-readout__step.svelte-1wa8bs6 {display:flex;align-items:center;justify-content:center;flex-shrink:0;width:var(--sky-size-touch);height:var(--sky-size-touch);padding:0;border-radius:var(--sky-radius-row);border:var(--ds-border-width) solid var(--sky-color-border-strong);background:var(--sky-color-control);color:var(--ds-color-fg);cursor:pointer;}.sky-readout__step.svelte-1wa8bs6:hover {background:var(--sky-color-control-hover);}.sky-readout__when.svelte-1wa8bs6 {display:flex;flex-direction:column;align-items:center;flex-grow:1;min-width:0;}.sky-readout__pos.svelte-1wa8bs6 {font-family:var(--ds-font-mono);font-size:var(--ds-text-xs);color:var(--ds-color-text-subtle);}.sky-readout__stats.svelte-1wa8bs6 {display:grid;grid-template-columns:repeat(3, minmax(0, 1fr));gap:var(--ds-space-2-5);margin:0;}.sky-readout__stats.svelte-1wa8bs6 div:where(.svelte-1wa8bs6) {display:flex;flex-direction:column-reverse;gap:1px;}.sky-readout__stats.svelte-1wa8bs6 dt:where(.svelte-1wa8bs6),
  .sky-readout__k.svelte-1wa8bs6 {font-family:var(--ds-font-mono);font-size:0.625rem;letter-spacing:var(--sky-tracking-label);text-transform:uppercase;color:var(--ds-color-text-subtle);}.sky-readout__stats.svelte-1wa8bs6 dd:where(.svelte-1wa8bs6) {margin:0;font-size:1.375rem;line-height:1.1;font-weight:var(--ds-font-weight-semibold);letter-spacing:-0.02em;font-variant-numeric:tabular-nums;}.sky-readout__stats.svelte-1wa8bs6 dd[data-accent]:where(.svelte-1wa8bs6) {color:var(--sky-color-accent-soft-fg);}.sky-readout__usage.svelte-1wa8bs6 {display:flex;flex-direction:column;gap:var(--ds-space-2);padding-top:var(--ds-space-3);border-top:var(--ds-border-width) solid var(--sky-color-border-muted);}.sky-readout__totals.svelte-1wa8bs6 {display:flex;align-items:baseline;justify-content:space-between;gap:var(--ds-space-2-5);}.sky-readout__totals.svelte-1wa8bs6 > span:where(.svelte-1wa8bs6) {display:flex;align-items:baseline;gap:var(--ds-space-2);}.sky-readout__v.svelte-1wa8bs6 {font-family:var(--ds-font-mono);font-size:var(--ds-text-sm);font-weight:var(--ds-font-weight-semibold);}.sky-readout__split.svelte-1wa8bs6 {display:flex;gap:2px;height:0.5rem;}.sky-readout__split.svelte-1wa8bs6 span:where(.svelte-1wa8bs6) {border-radius:2px;}.sky-readout__parts.svelte-1wa8bs6 {display:grid;grid-template-columns:repeat(2, minmax(0, 1fr));gap:5px var(--ds-space-3-5);margin:0;padding:0;list-style:none;}.sky-readout[data-variant='dock'].svelte-1wa8bs6 .sky-readout__parts:where(.svelte-1wa8bs6) {grid-template-columns:minmax(0, 1fr);gap:var(--ds-space-1);}.sky-readout__parts.svelte-1wa8bs6 li:where(.svelte-1wa8bs6) {display:flex;align-items:center;gap:var(--ds-space-1-5);font-size:0.75rem;color:var(--ds-color-text-muted);}.sky-readout__swatch.svelte-1wa8bs6 {flex-shrink:0;width:0.5rem;height:0.5rem;border-radius:2px;}.sky-readout__part-label.svelte-1wa8bs6 {flex-grow:1;min-width:0;}.sky-readout__part-value.svelte-1wa8bs6 {font-family:var(--ds-font-mono);font-size:var(--ds-text-xs);color:var(--ds-color-fg);}.sky-readout__none.svelte-1wa8bs6 {font-size:var(--sky-text-data);color:var(--ds-color-text-muted);}.sky-readout__runs-button.svelte-1wa8bs6 {display:flex;align-items:center;justify-content:center;height:var(--sky-size-touch);border-radius:var(--sky-radius-control);border:var(--ds-border-width) solid var(--sky-color-border-strong);background:var(--sky-color-control);color:var(--ds-color-fg);font-size:var(--ds-text-md);font-weight:var(--ds-font-weight-semibold);text-decoration:none;}.sky-readout__runs-button.svelte-1wa8bs6:hover {background:var(--sky-color-control-hover);}.sky-readout__step.svelte-1wa8bs6:focus-visible,
  .sky-readout__runs.svelte-1wa8bs6:focus-visible,
  .sky-readout__runs-button.svelte-1wa8bs6:focus-visible {outline:var(--sky-focus-ring-width) solid var(--sky-color-focus);outline-offset:var(--sky-focus-ring-offset);}`
};
function qs(e, t) {
  Ce(t, !0), Ge(e, Xd);
  let r = x(t, "variant", 3, "dock"), n = /* @__PURE__ */ wt(t, Id);
  const s = /* @__PURE__ */ F(() => t.day ? zd(t.day) : null);
  var a = Gd();
  _e(
    a,
    () => ({
      ...n,
      class: "sky-readout",
      "data-variant": r(),
      role: "status",
      "aria-live": "polite"
    }),
    void 0,
    void 0,
    void 0,
    "svelte-1wa8bs6"
  );
  var o = z(a);
  {
    var i = (f) => {
      var d = Wd(), v = re(d);
      {
        var h = (ee) => {
          var te = Fd(), se = z(te), Xe = z(se);
          Er(Xe, {
            get d() {
              return Jr.chevronLeft;
            },
            weight: 1.75
          }), S(se);
          var we = E(se, 2), ye = z(we), ce = ne(ye, !0), ge = E(ye, 2);
          {
            var Ie = (je) => {
              var Jt = Pd(), Or = ne(Jt, !0);
              W(() => J(Or, t.position)), k(je, Jt);
            };
            U(ge, (je) => {
              t.position && je(Ie);
            });
          }
          S(we);
          var He = E(we, 2), Xt = z(He);
          Er(Xt, {
            get d() {
              return Jr.chevronRight;
            },
            weight: 1.75
          }), S(He), S(te), W(() => J(ce, c(s).dateLabel)), it("click", se, function(...je) {
            t.onprev?.apply(this, je);
          }), it("click", He, function(...je) {
            t.onnext?.apply(this, je);
          }), k(ee, te);
        }, _ = (ee) => {
          var te = jd(), se = z(te), Xe = z(se, !0), we = E(Xe), ye = ne(we);
          S(se);
          var ce = E(se, 2);
          {
            var ge = (Ie) => {
              var He = Hd();
              W(() => L(He, "href", t.runsHref)), k(Ie, He);
            };
            U(ce, (Ie) => {
              t.runsHref && Ie(ge);
            });
          }
          S(te), W(() => {
            J(Xe, c(s).dateLabel), J(ye, `, ${c(s).year ?? ""}`);
          }), k(ee, te);
        };
        U(v, (ee) => {
          r() === "card" ? ee(h) : ee(_, -1);
        });
      }
      var u = E(v, 2), y = z(u), g = E(z(y)), b = ne(g, !0);
      S(y);
      var A = E(y, 2), R = E(z(A)), w = ne(R, !0);
      S(A);
      var q = E(A, 2), N = E(z(q)), M = ne(N, !0);
      S(q), S(u);
      var H = E(u, 2), T = z(H), p = z(T), C = E(z(p)), K = ne(C, !0);
      S(p);
      var Q = E(p, 2), G = E(z(Q)), ie = ne(G, !0);
      S(Q), S(T);
      var le = E(T, 2);
      {
        var fe = (ee) => {
          var te = Yd(), se = re(te);
          kt(se, 21, () => c(s).parts, (we) => we.key, (we, ye) => {
            var ce = Bd();
            let ge;
            W(() => ge = bt(ce, "", ge, {
              flex: `${c(ye).flex} 1 0`,
              background: `var(${c(ye).token})`
            })), k(we, ce);
          }), S(se);
          var Xe = E(se, 2);
          kt(Xe, 21, () => c(s).parts, (we) => we.key, (we, ye) => {
            var ce = Ud(), ge = z(ce);
            let Ie;
            var He = E(ge, 2), Xt = ne(He, !0), je = E(He, 2), Jt = ne(je, !0);
            S(ce), W(() => {
              Ie = bt(ge, "", Ie, { background: `var(${c(ye).token})` }), J(Xt, c(ye).label), J(Jt, c(ye).display);
            }), k(we, ce);
          }), S(Xe), k(ee, te);
        }, de = (ee) => {
          var te = Vd();
          k(ee, te);
        };
        U(le, (ee) => {
          c(s).hasTokens ? ee(fe) : ee(de, -1);
        });
      }
      S(H);
      var me = E(H, 2);
      {
        var Te = (ee) => {
          var te = qd();
          W(() => L(te, "href", t.runsHref)), k(ee, te);
        };
        U(me, (ee) => {
          r() === "card" && t.runsHref && ee(Te);
        });
      }
      W(() => {
        J(b, c(s).sessions), J(w, c(s).executions), J(M, c(s).commits), J(K, c(s).tokens), J(ie, c(s).cost);
      }), k(f, d);
    }, l = (f) => {
      var d = Kd();
      k(f, d);
    };
    U(o, (f) => {
      c(s) ? f(i) : f(l, -1);
    });
  }
  S(a), k(e, a), $e();
}
ls(["click"]);
var Jd = /* @__PURE__ */ new Set([
  "$$slots",
  "$$events",
  "$$legacy",
  "days",
  "today",
  "year",
  "years",
  "onyearchange",
  "selected",
  "onselect",
  "runsHref",
  "wideFrom"
]), Zd = /* @__PURE__ */ O('<button type="button" class="svelte-vvn46c"> </button>'), Qd = /* @__PURE__ */ O('<div class="sky-skyline__segmented svelte-vvn46c" role="group" aria-label="Year"></div>'), ec = /* @__PURE__ */ O('<div class="sky-skyline__stepper svelte-vvn46c" role="group" aria-label="Active day"><button class="sky-skyline__step svelte-vvn46c" type="button" aria-label="Previous active day"><!></button> <span class="sky-skyline__pos svelte-vvn46c"> </span> <button class="sky-skyline__step svelte-vvn46c" type="button" aria-label="Next active day"><!></button></div> <!>', 1), tc = /* @__PURE__ */ O('<div class="sky-skyline__segmented svelte-vvn46c" role="group" aria-label="Range" data-size="lg"><button type="button" class="svelte-vvn46c">16w</button> <button type="button" class="svelte-vvn46c">Year</button></div>'), rc = /* @__PURE__ */ _t('<path class="sky-skyline__side svelte-vvn46c"></path><path class="sky-skyline__front svelte-vvn46c"></path><path class="sky-skyline__top svelte-vvn46c"></path>', 1), nc = /* @__PURE__ */ _t('<path class="sky-skyline__lead svelte-vvn46c"></path><circle class="sky-skyline__dot svelte-vvn46c" r="2.5"></circle>', 1), sc = /* @__PURE__ */ _t('<g class="sky-skyline__picked svelte-vvn46c"><path class="sky-skyline__picked-side svelte-vvn46c"></path><path class="sky-skyline__picked-front svelte-vvn46c"></path><path class="sky-skyline__picked-top svelte-vvn46c"></path></g><!>', 1), ac = /* @__PURE__ */ _t("<text> </text>"), oc = /* @__PURE__ */ O('<button class="sky-skyline__hit svelte-vvn46c" type="button"></button>'), ic = /* @__PURE__ */ O('<div class="sky-skyline__dock svelte-vvn46c"><!></div>'), lc = /* @__PURE__ */ O('<div><div class="sky-skyline__controls svelte-vvn46c"><span class="sky-skyline__caption svelte-vvn46c"><!></span> <div class="sky-skyline__tools svelte-vvn46c"><!></div></div> <div class="sky-skyline__stage svelte-vvn46c"><div class="sky-skyline__chart svelte-vvn46c"><svg class="sky-skyline__svg svelte-vvn46c" role="img"><path class="sky-skyline__floor svelte-vvn46c"></path><path class="sky-skyline__future svelte-vvn46c"></path><!><!><g class="sky-skyline__months svelte-vvn46c" aria-hidden="true"></g></svg> <div class="sky-skyline__hits svelte-vvn46c" role="group" aria-label="Active days"></div></div> <!></div> <!></div>');
const dc = {
  hash: "svelte-vvn46c",
  code: `.sky-skyline.svelte-vvn46c {display:flex;flex-direction:column;gap:var(--ds-space-3);min-width:0;}.sky-skyline__controls.svelte-vvn46c {display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:var(--ds-space-3);}.sky-skyline__caption.svelte-vvn46c {font-size:var(--ds-text-sm);color:var(--ds-color-text-muted);}.sky-skyline__tools.svelte-vvn46c {display:flex;flex-wrap:wrap;align-items:center;gap:var(--ds-space-2-5) var(--ds-space-4);}.sky-skyline__stepper.svelte-vvn46c {display:flex;align-items:center;gap:var(--ds-space-2);}.sky-skyline__step.svelte-vvn46c {display:flex;align-items:center;justify-content:center;flex-shrink:0;width:1.75rem;height:1.75rem;padding:0;border-radius:var(--ds-radius-sm);border:var(--ds-border-width) solid var(--sky-color-border-strong);background:var(--sky-color-control);color:var(--ds-color-fg);cursor:pointer;}.sky-skyline__step.svelte-vvn46c:hover:not(:disabled) {background:var(--sky-color-control-hover);}.sky-skyline__step.svelte-vvn46c:disabled {color:var(--ds-color-text-subtle);cursor:default;}.sky-skyline__pos.svelte-vvn46c {min-width:8.25rem;text-align:center;font-family:var(--ds-font-mono);font-size:var(--ds-text-xs);color:var(--ds-color-text-muted);}.sky-skyline__segmented.svelte-vvn46c {display:flex;gap:2px;padding:2px;border-radius:var(--ds-radius-sm);border:var(--ds-border-width) solid var(--ds-color-border);background:var(--ds-color-bg);font-family:var(--ds-font-mono);font-size:var(--ds-text-xs);}.sky-skyline__segmented.svelte-vvn46c button:where(.svelte-vvn46c) {height:1.5rem;padding:0 var(--ds-space-2-5);border:0;border-radius:7px;background:transparent;color:var(--ds-color-text-muted);font:inherit;cursor:pointer;}.sky-skyline__segmented[data-size='lg'].svelte-vvn46c {padding:3px;border-radius:var(--sky-radius-control);}.sky-skyline__segmented[data-size='lg'].svelte-vvn46c button:where(.svelte-vvn46c) {height:1.875rem;border-radius:var(--ds-radius-sm);}.sky-skyline__segmented.svelte-vvn46c button[aria-pressed='true']:where(.svelte-vvn46c) {background:var(--ds-color-overlay);color:var(--ds-color-fg);}.sky-skyline__step.svelte-vvn46c:focus-visible,
  .sky-skyline__segmented.svelte-vvn46c button:where(.svelte-vvn46c):focus-visible,
  .sky-skyline__hit.svelte-vvn46c:focus-visible {outline:var(--sky-focus-ring-width) solid var(--sky-color-focus);outline-offset:var(--sky-focus-ring-offset);}.sky-skyline__stage.svelte-vvn46c {position:relative;display:grid;grid-template-columns:minmax(0, 1fr);gap:var(--ds-space-4);}.sky-skyline[data-wide].svelte-vvn46c .sky-skyline__stage:where(.svelte-vvn46c):not([data-overlap]) {grid-template-columns:minmax(0, 1fr) 15.25rem;}.sky-skyline__stage[data-overlap].svelte-vvn46c .sky-skyline__dock:where(.svelte-vvn46c) {position:absolute;top:0;right:8px;z-index:var(--sky-z-nav);width:15.25rem;}.sky-skyline__chart.svelte-vvn46c {position:relative;min-width:0;}.sky-skyline__svg.svelte-vvn46c {display:block;width:100%;height:auto;overflow:visible;}.sky-skyline__floor.svelte-vvn46c {fill:var(--sky-color-neutral-soft);}.sky-skyline__future.svelte-vvn46c {fill:var(--sky-color-track);}.sky-skyline__side.svelte-vvn46c {fill:var(--sky-face-side);}.sky-skyline__front.svelte-vvn46c {fill:var(--sky-face-front);}.sky-skyline__top.svelte-vvn46c {fill:var(--sky-face-top);}.sky-skyline__picked.svelte-vvn46c path:where(.svelte-vvn46c) {stroke:var(--ds-color-fg);stroke-width:1;stroke-linejoin:round;}.sky-skyline__picked-side.svelte-vvn46c {fill:var(--ds-color-accent);}.sky-skyline__picked-front.svelte-vvn46c {fill:color-mix(in oklab, var(--ds-color-accent) 62%, var(--ds-color-fg));}.sky-skyline__picked-top.svelte-vvn46c {fill:var(--ds-color-fg);}.sky-skyline__lead.svelte-vvn46c {fill:none;stroke:var(--ds-color-fg);stroke-opacity:0.5;stroke-width:1;stroke-dasharray:2 3;}.sky-skyline__dot.svelte-vvn46c {fill:var(--ds-color-fg);}.sky-skyline__months.svelte-vvn46c {font-family:var(--ds-font-mono);font-size:10px;fill:var(--ds-color-text-subtle);}.sky-skyline__hits.svelte-vvn46c {position:absolute;inset:0;pointer-events:none;}.sky-skyline__hit.svelte-vvn46c {position:absolute;padding:0;border:0;border-radius:var(--ds-radius-xs);background:transparent;cursor:pointer;pointer-events:auto;}
  @media (pointer: coarse) {.sky-skyline__step.svelte-vvn46c,
    .sky-skyline__segmented.svelte-vvn46c button:where(.svelte-vvn46c) {min-width:var(--sky-size-touch);min-height:var(--sky-size-touch);}
  }`
};
function cc(e, t) {
  Ce(t, !0), Ge(e, dc);
  let r = x(t, "today", 19, () => vs(Date.now())), n = x(t, "years", 19, () => []), s = x(t, "selected", 15, null), a = x(t, "wideFrom", 3, 720), o = /* @__PURE__ */ wt(t, Jd), i = /* @__PURE__ */ xe(0), l = /* @__PURE__ */ xe(0), f = /* @__PURE__ */ xe(0), d = /* @__PURE__ */ xe("weeks"), v = /* @__PURE__ */ xe(void 0);
  const h = /* @__PURE__ */ F(() => t.year ?? Number(r().slice(0, 4))), _ = /* @__PURE__ */ F(() => c(i) === 0 || c(i) >= a()), u = /* @__PURE__ */ F(() => c(_) || c(d) === "year" ? "year" : "weeks"), y = /* @__PURE__ */ F(() => c(u) === "weeks" ? ld : fs), g = /* @__PURE__ */ F(() => c(u) === "weeks" ? ud(r()) : cd(c(h))), b = /* @__PURE__ */ F(() => vd({
    days: t.days,
    range: c(g),
    today: r(),
    dims: c(y)
  })), A = /* @__PURE__ */ F(() => c(b).bars), R = /* @__PURE__ */ F(() => {
    if (c(A).length === 0) return null;
    const $ = s() ? c(A).findIndex((P) => P.date === s()) : -1;
    return $ >= 0 ? $ : c(A).length - 1;
  }), w = /* @__PURE__ */ F(() => c(R) === null ? null : c(A)[c(R)] ?? null), q = /* @__PURE__ */ F(() => Rd({ index: c(R), count: c(A).length })), N = /* @__PURE__ */ F(() => c(u) === "weeks" ? "the last 16 weeks" : String(c(h))), M = /* @__PURE__ */ F(() => c(y).viewBox), H = /* @__PURE__ */ F(() => c(l) > 0 ? c(l) / c(M).width : 1), T = 8, p = /* @__PURE__ */ F(() => c(M).x + (c(l) - T - (c(f) || 244)) / c(H)), C = /* @__PURE__ */ F(() => c(_) && c(l) > 0 && c(A).every(($) => $.hit.x + $.hit.width < c(p))), K = /* @__PURE__ */ F(() => c(C) ? c(p) : c(M).x + c(M).width), Q = /* @__PURE__ */ F(() => c(_) && c(w) ? hd(c(w), c(K), c(y)) : null);
  async function G($, P = !1) {
    const X = Nd({ index: c(R), count: c(A).length }, $);
    if (X.index === null) return;
    const B = c(A)[X.index];
    B && (B.date !== s() && (s(B.date), t.onselect?.(B.day)), P && (await Ui(), c(v)?.querySelector(`[data-date="${B.date}"]`)?.focus()));
  }
  function ie($) {
    const P = Ld($.key);
    P && ($.preventDefault(), G(P, !0));
  }
  var le = lc();
  _e(
    le,
    () => ({
      ...o,
      class: "sky-skyline",
      "data-wide": c(_) || void 0
    }),
    void 0,
    void 0,
    void 0,
    "svelte-vvn46c"
  );
  var fe = z(le), de = z(fe), me = z(de);
  {
    var Te = ($) => {
      var P = Xr();
      W(() => J(P, `Agent activity · every day of ${c(h) ?? ""}. Taller means more sessions. Point at a bar, or step through the active days.`)), k($, P);
    }, ee = ($) => {
      var P = Xr();
      W(() => J(P, `Agent activity · ${(c(u) === "weeks" ? "last 16 weeks" : c(h)) ?? ""}`)), k($, P);
    };
    U(me, ($) => {
      c(_) ? $(Te) : $(ee, -1);
    });
  }
  S(de);
  var te = E(de, 2), se = z(te);
  {
    var Xe = ($) => {
      var P = ec(), X = re(P), B = z(X), Je = z(B);
      Er(Je, {
        get d() {
          return Jr.chevronLeft;
        },
        weight: 1.75
      }), S(B);
      var Zt = E(B, 2), Dt = ne(Zt, !0), gt = E(Zt, 2), xt = z(gt);
      Er(xt, {
        get d() {
          return Jr.chevronRight;
        },
        weight: 1.75
      }), S(gt), S(X);
      var It = E(X, 2);
      {
        var Qt = (er) => {
          var un = Qd();
          kt(un, 20, n, (fn) => fn, (fn, vn) => {
            var Dr = Zd(), So = ne(Dr, !0);
            W(() => {
              L(Dr, "aria-pressed", vn === c(h)), J(So, vn);
            }), it("click", Dr, () => t.onyearchange?.(vn)), k(fn, Dr);
          }), S(un), k(er, un);
        };
        U(It, (er) => {
          n().length > 1 && er(Qt);
        });
      }
      W(() => {
        B.disabled = !c(A).length, J(Dt, c(q)), gt.disabled = !c(A).length;
      }), it("click", B, () => G({ type: "prev" })), it("click", gt, () => G({ type: "next" })), k($, P);
    }, we = ($) => {
      var P = tc(), X = z(P), B = E(X, 2);
      S(P), W(() => {
        L(X, "aria-pressed", c(d) === "weeks"), L(B, "aria-pressed", c(d) === "year");
      }), it("click", X, () => ve(d, "weeks")), it("click", B, () => ve(d, "year")), k($, P);
    };
    U(se, ($) => {
      c(_) ? $(Xe) : $(we, -1);
    });
  }
  S(te), S(fe);
  var ye = E(fe, 2), ce = z(ye), ge = z(ce), Ie = z(ge), He = E(Ie), Xt = E(He);
  kt(Xt, 16, () => [6, 5, 4, 3, 2, 1, 0], ($) => $, ($, P) => {
    const X = /* @__PURE__ */ F(() => c(b).rows[P]);
    var B = ke(), Je = re(B);
    {
      var Zt = (Dt) => {
        var gt = rc(), xt = re(gt), It = E(xt), Qt = E(It);
        W(() => {
          L(xt, "d", c(X).side), L(It, "d", c(X).front), L(Qt, "d", c(X).top);
        }), k(Dt, gt);
      };
      U(Je, (Dt) => {
        c(X) && Dt(Zt);
      });
    }
    k($, B);
  });
  var je = E(Xt);
  {
    var Jt = ($) => {
      var P = sc(), X = re(P), B = z(X), Je = E(B), Zt = E(Je);
      S(X);
      var Dt = E(X);
      {
        var gt = (xt) => {
          var It = nc(), Qt = re(It), er = E(Qt);
          W(() => {
            L(Qt, "d", c(Q)), L(er, "cx", c(w).anchor.x), L(er, "cy", c(w).anchor.y);
          }), k(xt, It);
        };
        U(Dt, (xt) => {
          c(Q) && xt(gt);
        });
      }
      W(() => {
        L(B, "d", c(w).paths.side), L(Je, "d", c(w).paths.front), L(Zt, "d", c(w).paths.top);
      }), k($, P);
    };
    U(je, ($) => {
      c(w) && $(Jt);
    });
  }
  var Or = E(je);
  kt(Or, 21, () => c(b).months, ($) => $.label + $.x, ($, P) => {
    var X = ac(), B = ne(X, !0);
    W(() => {
      L(X, "x", c(P).x), L(X, "y", c(P).y), J(B, c(P).label);
    }), k($, X);
  }), S(Or), S(ge);
  var hs = E(ge, 2);
  kt(hs, 21, () => c(A), ($) => $.date, ($, P) => {
    const X = /* @__PURE__ */ F(() => _d(c(P).hit, c(y)));
    var B = oc();
    let Je;
    W(() => {
      L(B, "data-date", c(P).date), L(B, "aria-label", c(P).label), L(B, "aria-pressed", c(P).index === c(R)), L(B, "tabindex", c(P).index === c(R) ? 0 : -1), Je = bt(B, "", Je, {
        left: c(X).left,
        top: c(X).top,
        width: c(X).width,
        height: c(X).height,
        "z-index": c(P).hit.z
      });
    }), As("mouseenter", B, () => G({ type: "pick", index: c(P).index })), As("focus", B, () => G({ type: "pick", index: c(P).index })), it("click", B, () => G({ type: "pick", index: c(P).index })), it("keydown", B, ie), k($, B);
  }), S(hs), S(ce), zl(ce, ($) => ve(v, $), () => c(v));
  var ko = E(ce, 2);
  {
    var mo = ($) => {
      var P = ic(), X = z(P);
      {
        let B = /* @__PURE__ */ F(() => c(w)?.day ?? null), Je = /* @__PURE__ */ F(() => c(w) && t.runsHref ? t.runsHref(c(w).day) : void 0);
        qs(X, {
          get day() {
            return c(B);
          },
          variant: "dock",
          get runsHref() {
            return c(Je);
          }
        });
      }
      S(P), xn(P, "clientWidth", (B) => ve(f, B)), k($, P);
    };
    U(ko, ($) => {
      c(_) && $(mo);
    });
  }
  S(ye);
  var wo = E(ye, 2);
  {
    var xo = ($) => {
      {
        let P = /* @__PURE__ */ F(() => c(w)?.day ?? null), X = /* @__PURE__ */ F(() => c(w) && t.runsHref ? t.runsHref(c(w).day) : void 0);
        qs($, {
          get day() {
            return c(P);
          },
          variant: "card",
          get position() {
            return c(q);
          },
          onprev: () => G({ type: "prev" }),
          onnext: () => G({ type: "next" }),
          get runsHref() {
            return c(X);
          }
        });
      }
    };
    U(wo, ($) => {
      c(_) || $(xo);
    });
  }
  S(le), W(
    ($) => {
      L(ye, "data-overlap", c(C) || void 0), L(ge, "viewBox", c(b).viewBox), L(ge, "aria-label", $), L(Ie, "d", c(b).floor), L(He, "d", c(b).future);
    },
    [() => yd(c(b), c(N))]
  ), xn(ce, "clientWidth", ($) => ve(l, $)), xn(le, "clientWidth", ($) => ve(i, $)), k(e, le), $e();
}
ls(["click", "keydown"]);
function _o(e, t) {
  Ce(t, !0);
  let r = x(t, "days", 23, () => []), n = x(t, "today", 7), s = x(t, "year", 7), a = x(t, "years", 7), o = x(t, "selected", 15, null), i = x(t, "wideFrom", 7), l = x(t, "runsHref", 7), f = null;
  const d = Ot(
    (y) => {
      f = y;
    },
    { block: !0 }
  ), v = /* @__PURE__ */ F(() => {
    const y = l();
    return y ? (g) => y.replaceAll("{date}", encodeURIComponent(g.date)) : void 0;
  }), h = (y) => Un(f, "select", y), _ = (y) => Un(f, "yearchange", y);
  var u = {
    get days() {
      return r();
    },
    set days(y = []) {
      r(y), I();
    },
    get today() {
      return n();
    },
    set today(y) {
      n(y), I();
    },
    get year() {
      return s();
    },
    set year(y) {
      s(y), I();
    },
    get years() {
      return a();
    },
    set years(y) {
      a(y), I();
    },
    get selected() {
      return o();
    },
    set selected(y = null) {
      o(y), I();
    },
    get wideFrom() {
      return i();
    },
    set wideFrom(y) {
      i(y), I();
    },
    get runsHref() {
      return l();
    },
    set runsHref(y) {
      l(y), I();
    }
  };
  return cc(e, {
    get days() {
      return r();
    },
    get today() {
      return n();
    },
    get year() {
      return s();
    },
    get years() {
      return a();
    },
    get wideFrom() {
      return i();
    },
    get runsHref() {
      return c(v);
    },
    onselect: h,
    onyearchange: _,
    [Rt()]: (y) => (d || We)(y),
    get selected() {
      return o();
    },
    set selected(y) {
      o(y);
    }
  }), $e(u);
}
customElements.define("sky-skyline", Lt(
  _o,
  {
    days: { type: "Array" },
    today: { type: "String" },
    year: { type: "Number" },
    years: { type: "Array" },
    selected: { reflect: !0, type: "String" },
    wideFrom: { attribute: "wide-from", type: "Number" },
    runsHref: { attribute: "runs-href", type: "String" }
  },
  [],
  [],
  { mode: "open" }
));
var uc = /* @__PURE__ */ new Set([
  "$$slots",
  "$$events",
  "$$legacy",
  "label",
  "value",
  "size",
  "meta",
  "children"
]), fc = /* @__PURE__ */ O('<span class="sky-stat__meta svelte-1gbkqd"><!></span>'), vc = /* @__PURE__ */ O('<div><span class="sky-stat__label svelte-1gbkqd"> </span> <span class="sky-stat__value svelte-1gbkqd"><!></span> <!></div>');
const hc = {
  hash: "svelte-1gbkqd",
  code: ".sky-stat.svelte-1gbkqd {display:flex;flex-direction:column;gap:var(--ds-space-0-5);min-width:0;}.sky-stat__label.svelte-1gbkqd {font-family:var(--ds-font-mono);font-size:var(--sky-text-label);letter-spacing:var(--sky-tracking-label);text-transform:uppercase;color:var(--ds-color-text-subtle);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}.sky-stat__value.svelte-1gbkqd {display:flex;align-items:baseline;gap:var(--ds-space-1-5);font-size:var(--sky-text-figure);line-height:1.1;font-weight:var(--ds-font-weight-semibold);letter-spacing:-0.03em;font-variant-numeric:tabular-nums;color:var(--ds-color-fg);overflow-wrap:anywhere;}.sky-stat[data-size='hero'].svelte-1gbkqd .sky-stat__value:where(.svelte-1gbkqd) {font-size:clamp(var(--sky-text-3xl), 1.4rem + 1.2vw, 2.375rem);}.sky-stat[data-size='sm'].svelte-1gbkqd .sky-stat__value:where(.svelte-1gbkqd) {font-size:var(--ds-text-xl);letter-spacing:-0.02em;}.sky-stat__value[data-unknown].svelte-1gbkqd {color:var(--ds-color-text-subtle);}.sky-stat__meta.svelte-1gbkqd {font-size:var(--sky-text-data);color:var(--ds-color-text-muted);}"
};
function _c(e, t) {
  Ge(e, hc);
  let r = x(t, "size", 3, "md"), n = /* @__PURE__ */ wt(t, uc);
  const s = /* @__PURE__ */ F(() => !t.children && (t.value === null || t.value === void 0 || t.value === "" || t.value === Wt));
  var a = vc();
  _e(a, () => ({ ...n, class: "sky-stat", "data-size": r() }), void 0, void 0, void 0, "svelte-1gbkqd");
  var o = z(a), i = ne(o, !0), l = E(o, 2), f = z(l);
  {
    var d = (y) => {
      var g = ke(), b = re(g);
      Le(b, () => t.children), k(y, g);
    }, v = (y) => {
      var g = Xr();
      W(() => J(g, Wt)), k(y, g);
    }, h = (y) => {
      var g = Xr();
      W(() => J(g, t.value)), k(y, g);
    };
    U(f, (y) => {
      t.children ? y(d) : c(s) ? y(v, 1) : y(h, -1);
    });
  }
  S(l);
  var _ = E(l, 2);
  {
    var u = (y) => {
      var g = fc(), b = z(g);
      Le(b, () => t.meta), S(g), k(y, g);
    };
    U(_, (y) => {
      t.meta && y(u);
    });
  }
  S(a), W(() => {
    J(i, t.label), L(l, "data-unknown", c(s) || void 0);
  }), k(e, a);
}
const yc = (e) => {
  var t = ke(), r = re(t);
  ot(r, () => yt), k(e, t);
}, gc = (e) => {
  var t = ke(), r = re(t);
  ot(r, () => yt, !1, (n, s) => {
    _e(n, () => ({ name: "meta" }));
  }), k(e, t);
};
function yo(e, t) {
  Ce(t, !0);
  let r = x(t, "label", 7, ""), n = x(t, "value", 7), s = x(t, "size", 7), a = /* @__PURE__ */ xe(Et(/* @__PURE__ */ new Set()));
  const o = Ot((l) => dn(l, (f) => ve(a, f, !0)));
  var i = {
    get label() {
      return r();
    },
    set label(l = "") {
      r(l), I();
    },
    get value() {
      return n();
    },
    set value(l) {
      n(l), I();
    },
    get size() {
      return s();
    },
    set size(l) {
      s(l), I();
    }
  };
  {
    let l = /* @__PURE__ */ F(() => c(a).has("") ? yc : void 0), f = /* @__PURE__ */ F(() => c(a).has("meta") ? gc : void 0);
    _c(e, {
      get label() {
        return r();
      },
      get value() {
        return n();
      },
      get size() {
        return s();
      },
      get children() {
        return c(l);
      },
      get meta() {
        return c(f);
      },
      [Rt()]: (d) => (o || We)(d)
    });
  }
  return $e(i);
}
customElements.define("sky-stat", Lt(
  yo,
  {
    label: { type: "String" },
    value: { type: "String" },
    size: { type: "String" }
  },
  [],
  [],
  { mode: "open" }
));
var pc = /* @__PURE__ */ new Set([
  "$$slots",
  "$$events",
  "$$legacy",
  "status",
  "shape",
  "label"
]), bc = /* @__PURE__ */ O('<span class="sky-status__label"> </span>'), kc = /* @__PURE__ */ O('<span class="sky-visually-hidden"> </span>'), mc = /* @__PURE__ */ O('<span><span class="sky-status__glyph svelte-2hz5v0"><!></span> <!></span>');
const wc = {
  hash: "svelte-2hz5v0",
  code: `.sky-status.svelte-2hz5v0 {--_bg: var(--sky-color-neutral-soft);--_fg: var(--ds-color-text-muted);--_glyph: var(--ds-color-text-muted);display:inline-flex;align-items:center;justify-content:center;gap:var(--ds-space-1-5);flex-shrink:0;color:var(--_glyph);}.sky-status[data-tone='accent'].svelte-2hz5v0 {--_bg: var(--sky-color-accent-soft);--_fg: var(--sky-color-accent-soft-fg);--_glyph: var(--ds-color-accent);}.sky-status[data-tone='danger'].svelte-2hz5v0 {--_bg: var(--sky-color-danger-soft);--_fg: var(--sky-color-danger-soft-fg);--_glyph: var(--ds-color-danger);}.sky-status[data-tone='warning'].svelte-2hz5v0 {--_bg: var(--sky-color-warning-soft);--_fg: var(--sky-color-warning-soft-fg);--_glyph: var(--ds-color-warning);}.sky-status[data-shape='pill'].svelte-2hz5v0 {height:1.625rem;padding:0 var(--ds-space-3) 0 var(--ds-space-2);border-radius:var(--ds-radius-full);background:var(--_bg);color:var(--_fg);font-size:var(--ds-text-sm);font-weight:var(--ds-font-weight-semibold);white-space:nowrap;}.sky-status[data-shape='pill'][data-variant='outline'].svelte-2hz5v0 {background:transparent;box-shadow:inset 0 0 0 var(--ds-border-width) var(--sky-color-border-strong);}.sky-status[data-shape='pill'].svelte-2hz5v0 .sky-status__glyph:where(.svelte-2hz5v0) {color:currentColor;}.sky-status[data-shape='square'].svelte-2hz5v0 {width:var(--sky-size-control-sm);height:var(--sky-size-control-sm);border-radius:var(--ds-radius-md);background:var(--_bg);}.sky-status__glyph.svelte-2hz5v0 {display:inline-flex;}

  @media (prefers-reduced-motion: no-preference) {.sky-status[data-live].svelte-2hz5v0 .sky-status__glyph:where(.svelte-2hz5v0) {
      animation: svelte-2hz5v0-sky-status-spin 1.1s linear infinite;}
  }
  @keyframes svelte-2hz5v0-sky-status-spin {
    to {
      transform: rotate(360deg);
    }
  }`
};
function xc(e, t) {
  Ce(t, !0), Ge(e, wc);
  let r = x(t, "shape", 3, "pill"), n = /* @__PURE__ */ wt(t, pc);
  const s = /* @__PURE__ */ F(() => xd(t.status)), a = /* @__PURE__ */ F(() => t.label ?? c(s).label), o = /* @__PURE__ */ F(() => r() === "pill" ? 12 : r() === "square" ? 15 : 14);
  var i = mc();
  _e(
    i,
    () => ({
      ...n,
      class: "sky-status",
      "data-shape": r(),
      "data-variant": c(s).variant,
      "data-tone": c(s).tone,
      "data-kind": c(s).kind,
      "data-live": c(s).live || void 0
    }),
    void 0,
    void 0,
    void 0,
    "svelte-2hz5v0"
  );
  var l = z(i), f = z(l);
  {
    let _ = /* @__PURE__ */ F(() => r() === "pill" ? 2 : 1.9);
    Er(f, {
      get d() {
        return Ed[c(s).glyph];
      },
      get size() {
        return c(o);
      },
      get weight() {
        return c(_);
      }
    });
  }
  S(l);
  var d = E(l, 2);
  {
    var v = (_) => {
      var u = bc(), y = ne(u, !0);
      W(() => J(y, c(a))), k(_, u);
    }, h = (_) => {
      var u = kc(), y = ne(u, !0);
      W(() => J(y, c(a))), k(_, u);
    };
    U(d, (_) => {
      r() === "pill" ? _(v) : _(h, -1);
    });
  }
  S(i), k(e, i), $e();
}
function go(e, t) {
  Ce(t, !0);
  let r = x(t, "status", 7), n = x(t, "shape", 7), s = x(t, "label", 7);
  const a = Ot();
  var o = {
    get status() {
      return r();
    },
    set status(i) {
      r(i), I();
    },
    get shape() {
      return n();
    },
    set shape(i) {
      n(i), I();
    },
    get label() {
      return s();
    },
    set label(i) {
      s(i), I();
    }
  };
  {
    let i = /* @__PURE__ */ F(() => r() ?? null);
    xc(e, {
      get status() {
        return c(i);
      },
      get shape() {
        return n();
      },
      get label() {
        return s();
      },
      [Rt()]: (l) => (a || We)(l)
    });
  }
  return $e(o);
}
customElements.define("sky-status-badge", Lt(
  go,
  {
    status: { type: "String" },
    shape: { type: "String" },
    label: { type: "String" }
  },
  [],
  [],
  { mode: "open" }
));
const Sc = {
  copy: "M5.5 5.5h8v8h-8zM10.5 5.5V2.5h-8v8h3",
  check: "M3.5 8.5l3 3 6-7",
  cross: "M4.5 4.5l7 7M11.5 4.5l-7 7",
  dash: "M4 8h8",
  clock: "M8 4.5V8l2.5 1.5",
  "chevron-right": "M6 3.5L10.5 8 6 12.5",
  "chevron-left": "M10 3.5L5.5 8l4.5 4.5",
  "chevron-down": "M3.5 6L8 10.5 12.5 6",
  "chevron-up": "M3.5 10L8 5.5l4.5 4.5",
  search: "M10.25 10.25L13.5 13.5",
  warning: "M8 2.25l6 10.75H2zM8 6.5v3M8 11.4v.1",
  info: "M8 7.25v4M8 4.6v.1",
  home: "M2.75 7.25L8 2.75l5.25 4.5V13a.5.5 0 0 1-.5.5H9.5V9.75h-3v3.75H3.25a.5.5 0 0 1-.5-.5z",
  diamond: "M8 1.75L14.25 8 8 14.25 1.75 8z",
  more: "M3.5 8h.1M8 8h.1M12.5 8h.1"
};
var Ec = /* @__PURE__ */ _t('<circle cx="7" cy="7" r="4.25"></circle>'), Tc = /* @__PURE__ */ _t('<circle cx="8" cy="8" r="6"></circle>'), zc = /* @__PURE__ */ _t('<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><!><!><path></path></svg>');
const Ac = {
  hash: "svelte-27vo65",
  code: ".sky-glyph.svelte-27vo65 {flex-shrink:0;display:block;}"
};
function Ws(e, t) {
  Ge(e, Ac);
  let r = x(t, "size", 3, 15), n = x(t, "strokeWidth", 3, 1.5), s = x(t, "class", 3, "");
  var a = zc(), o = z(a);
  {
    var i = (v) => {
      var h = Ec();
      k(v, h);
    };
    U(o, (v) => {
      t.name === "search" && v(i);
    });
  }
  var l = E(o);
  {
    var f = (v) => {
      var h = Tc();
      k(v, h);
    };
    U(l, (v) => {
      t.name === "info" && v(f);
    });
  }
  var d = E(l);
  S(a), W(() => {
    Za(a, 0, Ja(["sky-glyph", s()]), "svelte-27vo65"), L(a, "width", r()), L(a, "height", r()), L(a, "stroke-width", t.name === "more" ? n() + 1 : n()), L(d, "d", Sc[t.name]);
  }), k(e, a);
}
var Mc = /* @__PURE__ */ new Set([
  "$$slots",
  "$$events",
  "$$legacy",
  "variant",
  "agent",
  "href",
  "onclick",
  "onremove",
  "removeLabel",
  "icon",
  "children"
]), Cc = /* @__PURE__ */ O('<span class="sky-tag__icon sky-tag__icon--accent svelte-11yntw7"><!></span>'), $c = /* @__PURE__ */ O('<span class="sky-tag__dot svelte-11yntw7" aria-hidden="true"></span>'), Nc = /* @__PURE__ */ O('<span class="sky-tag__icon svelte-11yntw7"><!></span>'), Rc = /* @__PURE__ */ O('<span class="sky-visually-hidden">Remove filter</span> ', 1), Lc = /* @__PURE__ */ O('<!> <span class="sky-tag__text svelte-11yntw7"><!><!></span> <!>', 1), Oc = /* @__PURE__ */ O("<a><!></a>"), Ks = /* @__PURE__ */ O("<button><!></button>"), Dc = /* @__PURE__ */ O("<span><!></span>");
const Ic = {
  hash: "svelte-11yntw7",
  code: `.sky-tag.svelte-11yntw7 {display:inline-flex;align-items:center;gap:var(--ds-space-1-5);box-sizing:border-box;max-width:100%;height:1.25rem; /* 20 */padding:0 var(--ds-space-2);border:var(--ds-border-width) solid var(--sky-color-border-strong);border-radius:var(--ds-radius-full);background:transparent;color:var(--ds-color-text-muted);font-family:var(--ds-font-mono);font-size:0.71875rem; /* 11.5 */line-height:1;text-decoration:none;white-space:nowrap;vertical-align:middle;-webkit-tap-highlight-color:transparent;}.sky-tag__text.svelte-11yntw7 {min-width:0;overflow:hidden;text-overflow:ellipsis;}.sky-tag__icon.svelte-11yntw7 {display:flex;}.sky-tag__icon--accent.svelte-11yntw7 {color:var(--ds-color-accent);}.sky-tag[data-variant='accent'].svelte-11yntw7 {height:1.5rem;padding:0 var(--ds-space-2-5);border-color:transparent;background:color-mix(in oklab, var(--ds-color-accent) 14%, transparent);color:color-mix(in oklab, var(--ds-color-accent) 45%, var(--ds-color-fg));}.sky-tag[data-variant='skill'].svelte-11yntw7 {height:1.5rem;padding:0 var(--ds-space-2) 0 var(--ds-space-1-5);border-color:var(--sky-color-border-muted);border-radius:var(--ds-space-2);background:var(--sky-color-control-hover);color:var(--sky-color-text-code);}.sky-tag[data-variant='agent'].svelte-11yntw7 {gap:var(--ds-space-2);height:1.625rem;padding:0 var(--ds-space-3);border-color:transparent;background:var(--sky-color-control-hover);color:var(--ds-color-fg);font-family:var(--ds-font-sans);font-size:var(--ds-text-sm);}.sky-tag[data-variant='dashed'].svelte-11yntw7 {border-style:dashed;border-color:var(--sky-color-border-hover);border-radius:0.4375rem;font-size:var(--ds-text-xs);}.sky-tag__dot.svelte-11yntw7 {flex-shrink:0;width:0.4375rem;height:0.4375rem;border-radius:50%;background:var(--ds-color-text-subtle);}.sky-tag__dot[data-agent='claude'].svelte-11yntw7 {background:var(--sky-color-agent-claude);}.sky-tag__dot[data-agent='codex'].svelte-11yntw7 {background:var(--sky-color-agent-codex);}.sky-tag[data-removable].svelte-11yntw7 {gap:var(--ds-space-2);height:1.75rem;padding:0 var(--ds-space-2) 0 var(--ds-space-3);border-color:var(--sky-color-border-hover);background:var(--ds-color-overlay);color:var(--ds-color-fg);}.sky-tag[data-interactive].svelte-11yntw7 {cursor:pointer;font-family:var(--ds-font-mono);}.sky-tag[data-interactive].svelte-11yntw7:hover {border-color:var(--sky-color-border-hover);color:var(--ds-color-fg);}.sky-tag[data-variant='accent'][data-interactive].svelte-11yntw7:hover {border-color:transparent;background:var(--sky-color-accent-ring);}.sky-tag.svelte-11yntw7:focus-visible {outline:var(--sky-focus-ring-width) solid var(--sky-color-focus);outline-offset:var(--sky-focus-ring-offset);}
  @media (pointer: coarse) {
    /* Grow the hit area, not the drawn chip. */.sky-tag[data-interactive].svelte-11yntw7 {position:relative;}.sky-tag[data-interactive].svelte-11yntw7::after {content:'';position:absolute;inset:50% auto auto 50%;width:max(100%, var(--sky-size-touch));height:var(--sky-size-touch);transform:translate(-50%, -50%);}
  }`
};
function Pc(e, t) {
  Ce(t, !0), Ge(e, Ic);
  const r = (u) => {
    var y = Lc(), g = re(y);
    {
      var b = (p) => {
        var C = Cc(), K = z(C);
        Ws(K, { name: "diamond", size: 11, strokeWidth: 1.75 }), S(C), k(p, C);
      }, A = (p) => {
        var C = $c();
        W(() => L(C, "data-agent", s())), k(p, C);
      }, R = (p) => {
        var C = Nc(), K = z(C);
        Le(K, () => t.icon), S(C), k(p, C);
      };
      U(g, (p) => {
        n() === "skill" ? p(b) : n() === "agent" ? p(A, 1) : t.icon && p(R, 2);
      });
    }
    var w = E(g, 2), q = z(w);
    {
      var N = (p) => {
        var C = Rc(), K = E(re(C), 1, !0);
        K.nodeValue = " ", k(p, C);
      };
      U(q, (p) => {
        c(o) === "remove" && !t.removeLabel && p(N);
      });
    }
    var M = E(q);
    Le(M, () => t.children ?? We), S(w);
    var H = E(w, 2);
    {
      var T = (p) => {
        Ws(p, { name: "cross", size: 12, strokeWidth: 1.9 });
      };
      U(H, (p) => {
        c(o) === "remove" && p(T);
      });
    }
    k(u, y);
  };
  let n = x(t, "variant", 3, "outline"), s = x(t, "agent", 3, "claude"), a = /* @__PURE__ */ wt(t, Mc);
  const o = /* @__PURE__ */ F(() => t.onremove ? "remove" : t.href ? "link" : t.onclick ? "button" : "static");
  function i(u) {
    t.onclick?.(u), u.defaultPrevented || t.onremove?.();
  }
  var l = ke(), f = re(l);
  {
    var d = (u) => {
      var y = Oc();
      _e(
        y,
        () => ({
          ...a,
          class: "sky-tag",
          href: t.href,
          "data-variant": n(),
          "data-interactive": ""
        }),
        void 0,
        void 0,
        void 0,
        "svelte-11yntw7"
      );
      var g = z(y);
      r(g), S(y), k(u, y);
    }, v = (u) => {
      var y = Ks();
      _e(
        y,
        () => ({
          ...a,
          type: "button",
          class: "sky-tag",
          "data-variant": n(),
          "data-interactive": "",
          onclick: t.onclick
        }),
        void 0,
        void 0,
        void 0,
        "svelte-11yntw7"
      );
      var g = z(y);
      r(g), S(y), k(u, y);
    }, h = (u) => {
      var y = Ks();
      _e(
        y,
        () => ({
          ...a,
          type: "button",
          class: "sky-tag",
          "data-variant": n(),
          "data-interactive": "",
          "data-removable": "",
          "aria-label": t.removeLabel,
          onclick: i
        }),
        void 0,
        void 0,
        void 0,
        "svelte-11yntw7"
      );
      var g = z(y);
      r(g), S(y), k(u, y);
    }, _ = (u) => {
      var y = Dc();
      _e(y, () => ({ ...a, class: "sky-tag", "data-variant": n() }), void 0, void 0, void 0, "svelte-11yntw7");
      var g = z(y);
      r(g), S(y), k(u, y);
    };
    U(f, (u) => {
      c(o) === "link" ? u(d) : c(o) === "button" ? u(v, 1) : c(o) === "remove" ? u(h, 2) : u(_, -1);
    });
  }
  k(e, l), $e();
}
const Fc = (e) => {
  var t = ke(), r = re(t);
  ot(r, () => yt), k(e, t);
}, Hc = (e) => {
  var t = ke(), r = re(t);
  ot(r, () => yt, !1, (n, s) => {
    _e(n, () => ({ name: "icon" }));
  }), k(e, t);
};
function po(e, t) {
  Ce(t, !0);
  let r = x(t, "variant", 7), n = x(t, "agent", 7), s = x(t, "href", 7), a = x(t, "removable", 7, !1), o = x(t, "removeLabel", 7), i = null, l = /* @__PURE__ */ xe(!1);
  const f = Ot((h) => (i = h, dn(h, (_) => ve(l, _.has("icon"), !0)))), d = () => Un(i, "remove", null);
  var v = {
    get variant() {
      return r();
    },
    set variant(h) {
      r(h), I();
    },
    get agent() {
      return n();
    },
    set agent(h) {
      n(h), I();
    },
    get href() {
      return s();
    },
    set href(h) {
      s(h), I();
    },
    get removable() {
      return a();
    },
    set removable(h = !1) {
      a(h), I();
    },
    get removeLabel() {
      return o();
    },
    set removeLabel(h) {
      o(h), I();
    }
  };
  {
    let h = /* @__PURE__ */ F(() => a() ? d : void 0), _ = /* @__PURE__ */ F(() => c(l) ? Hc : void 0);
    Pc(e, {
      get variant() {
        return r();
      },
      get agent() {
        return n();
      },
      get href() {
        return s();
      },
      get removeLabel() {
        return o();
      },
      get onremove() {
        return c(h);
      },
      get children() {
        return Fc;
      },
      get icon() {
        return c(_);
      },
      [Rt()]: (u) => (f || We)(u)
    });
  }
  return $e(v);
}
customElements.define("sky-tag", Lt(
  po,
  {
    variant: { type: "String" },
    agent: { type: "String" },
    href: { type: "String" },
    removable: { type: "Boolean" },
    removeLabel: { attribute: "remove-label", type: "String" }
  },
  [],
  [],
  { mode: "open" }
));
var jc = /* @__PURE__ */ new Set([
  "$$slots",
  "$$events",
  "$$legacy",
  "cost",
  "tokens",
  "costRows",
  "costBy",
  "note",
  "rates",
  "title"
]), Bc = /* @__PURE__ */ _t("<path></path><path></path><path></path>", 1), Uc = /* @__PURE__ */ O('<span class="sky-usage__rate svelte-1m7o0t6"> </span>'), Yc = /* @__PURE__ */ O('<li class="svelte-1m7o0t6"><span class="sky-usage__series svelte-1m7o0t6"><span class="sky-usage__swatch svelte-1m7o0t6"></span> <!></span> <span class="sky-usage__figure svelte-1m7o0t6"><span class="sky-usage__count svelte-1m7o0t6"> </span><span class="sky-usage__pct svelte-1m7o0t6"> </span></span></li>'), Vc = /* @__PURE__ */ O('<svg class="sky-usage__band svelte-1m7o0t6" preserveAspectRatio="none" role="img"></svg> <ul class="sky-usage__legend svelte-1m7o0t6"></ul>', 1), qc = /* @__PURE__ */ O('<span class="sky-usage__empty svelte-1m7o0t6">No tokens recorded.</span>'), Wc = /* @__PURE__ */ O('<li class="sky-usage__row svelte-1m7o0t6"><span class="sky-usage__row-label svelte-1m7o0t6"> </span> <span class="sky-usage__bar svelte-1m7o0t6" aria-hidden="true"><span class="svelte-1m7o0t6"></span></span> <span class="sky-usage__row-value svelte-1m7o0t6"> <span class="sky-usage__pct svelte-1m7o0t6"> </span></span></li>'), Kc = /* @__PURE__ */ O('<p class="sky-usage__note svelte-1m7o0t6"> </p>'), Gc = /* @__PURE__ */ O('<section><div class="sky-usage__total svelte-1m7o0t6"><h2 class="sky-usage__heading svelte-1m7o0t6"> </h2> <span class="sky-usage__cost svelte-1m7o0t6"> </span> <span class="sky-usage__tokens svelte-1m7o0t6"> </span></div> <div class="sky-usage__zone svelte-1m7o0t6" data-zone="tokens"><span class="sky-usage__label svelte-1m7o0t6">Tokens by type</span> <!></div> <div class="sky-usage__zone svelte-1m7o0t6" data-zone="cost"><span class="sky-usage__label svelte-1m7o0t6"> </span> <ul class="sky-usage__rows svelte-1m7o0t6"></ul> <!></div></section>');
const Xc = {
  hash: "svelte-1m7o0t6",
  code: `.sky-usage.svelte-1m7o0t6 {display:flex;flex-wrap:wrap;align-items:stretch;gap:var(--ds-space-5) var(--ds-space-10);padding:var(--ds-space-5);border-radius:var(--sky-radius-card-lg);border:var(--ds-border-width) solid var(--ds-color-border);background:var(--ds-color-surface);box-shadow:var(--sky-shadow-raised);}
  @media (min-width: 48rem) {.sky-usage.svelte-1m7o0t6 {padding:var(--ds-space-6) var(--ds-space-7);}
  }.sky-usage__total.svelte-1m7o0t6 {flex:0 1 10.625rem;display:flex;flex-direction:column;gap:var(--ds-space-1);min-width:0;}.sky-usage__heading.svelte-1m7o0t6,
  .sky-usage__label.svelte-1m7o0t6 {margin:0;font-family:var(--ds-font-mono);font-size:var(--sky-text-label);font-weight:var(--ds-font-weight-medium);letter-spacing:var(--sky-tracking-label);text-transform:uppercase;color:var(--ds-color-text-subtle);}.sky-usage__cost.svelte-1m7o0t6 {font-size:2rem;line-height:1.1;font-weight:var(--ds-font-weight-semibold);letter-spacing:-0.03em;font-variant-numeric:tabular-nums;}.sky-usage__tokens.svelte-1m7o0t6 {font-family:var(--ds-font-mono);font-size:var(--sky-text-data);color:var(--ds-color-text-muted);}.sky-usage__zone.svelte-1m7o0t6 {display:flex;flex-direction:column;gap:var(--ds-space-3);min-width:0;}.sky-usage__zone[data-zone='tokens'].svelte-1m7o0t6 {flex:3 1 18.75rem;}.sky-usage__zone[data-zone='cost'].svelte-1m7o0t6 {flex:2 1 16.25rem;}.sky-usage__band.svelte-1m7o0t6 {display:block;width:100%;height:2.125rem;}.sky-usage__legend.svelte-1m7o0t6 {display:grid;grid-template-columns:repeat(auto-fit, minmax(7.375rem, 1fr));gap:var(--ds-space-3) var(--ds-space-4);margin:0;padding:0;list-style:none;}.sky-usage__legend.svelte-1m7o0t6 li:where(.svelte-1m7o0t6) {display:flex;flex-direction:column;gap:3px;min-width:0;}.sky-usage__series.svelte-1m7o0t6 {display:flex;flex-wrap:wrap;align-items:center;gap:var(--ds-space-1) 7px;font-size:var(--sky-text-data);color:var(--ds-color-text-muted);}.sky-usage__swatch.svelte-1m7o0t6 {flex-shrink:0;width:0.5rem;height:0.5rem;border-radius:2px;}.sky-usage__rate.svelte-1m7o0t6 {padding:1px 6px;border-radius:6px;border:var(--ds-border-width) solid var(--sky-color-border-strong);font-family:var(--ds-font-mono);font-size:var(--sky-text-label);}.sky-usage__figure.svelte-1m7o0t6 {display:flex;align-items:baseline;gap:7px;font-family:var(--ds-font-mono);}.sky-usage__count.svelte-1m7o0t6 {font-size:0.84375rem;font-weight:var(--ds-font-weight-semibold);}.sky-usage__pct.svelte-1m7o0t6 {font-size:var(--ds-text-xs);color:var(--ds-color-text-muted);}.sky-usage__rows.svelte-1m7o0t6 {display:flex;flex-direction:column;gap:var(--ds-space-2-5);margin:0;padding:0;list-style:none;}.sky-usage__row.svelte-1m7o0t6 {display:grid;grid-template-columns:minmax(0, 1.2fr) minmax(2.5rem, 1fr) auto;column-gap:var(--ds-space-3);align-items:center;font-family:var(--ds-font-mono);font-size:var(--sky-text-data);}.sky-usage__row-label.svelte-1m7o0t6 {white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}.sky-usage__bar.svelte-1m7o0t6 {display:block;height:6px;border-radius:3px;background:var(--ds-color-overlay);}.sky-usage__bar.svelte-1m7o0t6 span:where(.svelte-1m7o0t6) {display:block;height:100%;border-radius:3px;background:color-mix(in oklab, var(--ds-color-text-muted) 75%, var(--ds-color-text-subtle));}.sky-usage__bar.svelte-1m7o0t6 span[data-tone='accent']:where(.svelte-1m7o0t6) {background:var(--ds-color-accent);}.sky-usage__bar.svelte-1m7o0t6 span[data-tone='claude']:where(.svelte-1m7o0t6) {background:var(--sky-color-agent-claude);}.sky-usage__bar.svelte-1m7o0t6 span[data-tone='codex']:where(.svelte-1m7o0t6) {background:var(--sky-color-agent-codex);}.sky-usage__row-value.svelte-1m7o0t6 {text-align:right;white-space:nowrap;}.sky-usage__note.svelte-1m7o0t6,
  .sky-usage__empty.svelte-1m7o0t6 {margin:0;font-size:var(--sky-text-data);line-height:var(--ds-line-height-normal);color:var(--ds-color-text-muted);}`
};
function Jc(e, t) {
  Ce(t, !0), Ge(e, Xc);
  let r = x(t, "title", 3, "Usage"), n = /* @__PURE__ */ wt(t, jc);
  const s = /* @__PURE__ */ F(() => $d({
    cost: t.cost,
    tokens: t.tokens,
    costRows: t.costRows,
    costBy: t.costBy,
    rates: t.rates
  })), a = /* @__PURE__ */ F(() => bd(Zr.map((T) => ({ key: T.key, value: t.tokens[T.key] })))), o = (T) => {
    const p = Zr.find((C) => C.key === T);
    return od(`var(${p?.token ?? "--ds-color-accent"})`);
  };
  var i = Gc();
  _e(
    i,
    () => ({
      ...n,
      class: "sky-usage",
      "aria-label": n["aria-label"] ?? r()
    }),
    void 0,
    void 0,
    void 0,
    "svelte-1m7o0t6"
  );
  var l = z(i), f = z(l), d = ne(f, !0), v = E(f, 2), h = ne(v, !0), _ = E(v, 2), u = ne(_, !0);
  S(l);
  var y = E(l, 2), g = E(z(y), 2);
  {
    var b = (T) => {
      var p = Vc(), C = re(p);
      kt(C, 21, () => c(a).segments, (Q) => Q.key, (Q, G) => {
        const ie = /* @__PURE__ */ F(() => o(c(G).key));
        var le = Bc(), fe = re(le);
        let de;
        var me = E(fe);
        let Te;
        var ee = E(me);
        let te;
        W(() => {
          L(fe, "d", c(G).paths.side), de = bt(fe, "", de, { fill: c(ie).side }), L(me, "d", c(G).paths.top), Te = bt(me, "", Te, { fill: c(ie).top }), L(ee, "d", c(G).paths.front), te = bt(ee, "", te, { fill: c(ie).front });
        }), k(Q, le);
      }), S(C);
      var K = E(C, 2);
      kt(K, 21, () => c(s).series, (Q) => Q.key, (Q, G) => {
        var ie = Yc(), le = z(ie), fe = z(le);
        let de;
        var me = E(fe), Te = E(me);
        {
          var ee = (ce) => {
            var ge = Uc(), Ie = ne(ge, !0);
            W(() => J(Ie, c(G).rate)), k(ce, ge);
          };
          U(Te, (ce) => {
            c(G).rate && ce(ee);
          });
        }
        S(le);
        var te = E(le, 2), se = z(te), Xe = ne(se, !0), we = E(se), ye = ne(we, !0);
        S(te), S(ie), W(() => {
          de = bt(fe, "", de, { background: `var(${c(G).token})` }), J(me, `${c(G).label ?? ""} `), J(Xe, c(G).display), J(ye, c(G).percent);
        }), k(Q, ie);
      }), S(K), W(() => {
        L(C, "viewBox", c(a).viewBox), L(C, "aria-label", c(s).bandLabel);
      }), k(T, p);
    }, A = (T) => {
      var p = qc();
      k(T, p);
    };
    U(g, (T) => {
      c(a).segments.length ? T(b) : T(A, -1);
    });
  }
  S(y);
  var R = E(y, 2), w = z(R), q = ne(w), N = E(w, 2);
  kt(N, 21, () => c(s).costRows, dl, (T, p) => {
    var C = Wc(), K = z(C), Q = ne(K, !0), G = E(K, 2), ie = z(G);
    let le;
    S(G);
    var fe = E(G, 2), de = z(fe), me = E(de), Te = ne(me, !0);
    S(fe), S(C), W(() => {
      J(Q, c(p).label), L(ie, "data-tone", c(p).tone), le = bt(ie, "", le, { width: `${c(p).fill}%` }), J(de, `${c(p).display ?? ""} `), J(Te, c(p).percent);
    }), k(T, C);
  }), S(N);
  var M = E(N, 2);
  {
    var H = (T) => {
      var p = Kc(), C = ne(p, !0);
      W(() => J(C, t.note)), k(T, p);
    };
    U(M, (T) => {
      t.note && T(H);
    });
  }
  S(R), S(i), W(() => {
    J(d, r()), J(h, c(s).cost), J(u, c(s).tokensLabel), J(q, `Cost by ${t.costBy ?? ""}`);
  }), k(e, i), $e();
}
function bo(e, t) {
  Ce(t, !0);
  let r = x(t, "cost", 7), n = x(t, "tokens", 7), s = x(t, "costRows", 23, () => []), a = x(t, "costBy", 7, "model"), o = x(t, "note", 7), i = x(t, "rates", 7), l = x(t, "heading", 7);
  const f = Ot(void 0, { block: !0 });
  var d = {
    get cost() {
      return r();
    },
    set cost(u) {
      r(u), I();
    },
    get tokens() {
      return n();
    },
    set tokens(u) {
      n(u), I();
    },
    get costRows() {
      return s();
    },
    set costRows(u = []) {
      s(u), I();
    },
    get costBy() {
      return a();
    },
    set costBy(u = "model") {
      a(u), I();
    },
    get note() {
      return o();
    },
    set note(u) {
      o(u), I();
    },
    get rates() {
      return i();
    },
    set rates(u) {
      i(u), I();
    },
    get heading() {
      return l();
    },
    set heading(u) {
      l(u), I();
    }
  }, v = ke(), h = re(v);
  {
    var _ = (u) => {
      Jc(u, {
        get cost() {
          return r();
        },
        get tokens() {
          return n();
        },
        get costRows() {
          return s();
        },
        get costBy() {
          return a();
        },
        get note() {
          return o();
        },
        get rates() {
          return i();
        },
        get title() {
          return l();
        },
        [Rt()]: (y) => (f || We)(y)
      });
    };
    U(h, (u) => {
      n() && u(_);
    });
  }
  return k(e, v), $e(d);
}
customElements.define("sky-usage-meter", Lt(
  bo,
  {
    cost: { type: "String" },
    tokens: { type: "Object" },
    costRows: { attribute: "cost-rows", type: "Array" },
    costBy: { attribute: "cost-by", type: "String" },
    note: { type: "String" },
    rates: { type: "Object" },
    heading: { type: "String" }
  },
  [],
  [],
  { mode: "open" }
));
const Zc = {
  "sky-badge": io.element,
  "sky-button": lo.element,
  "sky-card": co.element,
  "sky-skyline": _o.element,
  "sky-stat": yo.element,
  "sky-status-badge": go.element,
  "sky-tag": po.element,
  "sky-usage-meter": bo.element
};
function eu(e = customElements) {
  for (const [t, r] of Object.entries(Zc))
    r && !e.get(t) && e.define(t, r);
}
export {
  eu as defineSkylineElements,
  Zc as skylineElements
};
//# sourceMappingURL=skyline-elements.js.map
