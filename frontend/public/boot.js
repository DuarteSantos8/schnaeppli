// Applies the saved appearance before the first paint, so there's no flash of the
// wrong theme. Kept outside the bundle (and not inline, for the CSP).
(function () {
  try {
    var p = JSON.parse(localStorage.getItem("schnaeppli.ui") || "{}");
    var r = document.documentElement;
    var dark = p.theme === "dark" || (p.theme !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
    r.dataset.theme = dark ? "dark" : "light";
    if (p.accent) r.dataset.accent = p.accent;
    if (p.density) r.dataset.density = p.density;
    if (p.text_size) r.dataset.text = p.text_size;
    if (p.reduce_motion) r.dataset.motion = "reduce";
    var m = document.querySelector('meta[name="theme-color"]');
    if (m) m.setAttribute("content", dark ? "#121211" : "#f4f3f1");
  } catch (e) {}
})();
