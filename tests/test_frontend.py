"""Static frontend smoke checks: files exist, wire to the API routes,
and carry no legacy Google-Maps dependency."""
import os
import unittest

STATIC = os.path.join(os.path.dirname(__file__), "..", "src",
                      "leaflogger", "static")

ROUTES = ["/trips", "/summary", "/soc", "/thermal", "/table",
          "/upload", "/ignore", "/track", "/trip", "/records"]


class FrontendTest(unittest.TestCase):
    def test_files_exist(self):
        for name in ("index.html", "app.js", "styles.css"):
            self.assertTrue(
                os.path.isfile(os.path.join(STATIC, name)), name)

    def test_app_js_hits_all_routes(self):
        js = open(os.path.join(STATIC, "app.js")).read()
        for route in ROUTES:
            self.assertIn(route, js, route)

    def test_no_google_maps(self):
        for name in ("index.html", "app.js"):
            body = open(os.path.join(STATIC, name)).read()
            self.assertNotIn("maps.googleapis.com", body, name)
            self.assertNotIn("google.maps", body, name)

    def test_leaflet_pinned(self):
        html = open(os.path.join(STATIC, "index.html")).read()
        self.assertIn("leaflet@1.9.4", html)

    def test_interactive_ids_wired(self):
        html = open(os.path.join(STATIC, "index.html")).read()
        js = open(os.path.join(STATIC, "app.js")).read()
        for element_id in ("resetRange", "rangeLabel", "expandMap",
                           "mapLegend", "unitsSelect", "uploadForm",
                           "fromBox", "toBox", "darkToggle",
                           "deleteTrip", "deleteAll", "miHead", "effHead"):
            self.assertIn(f'id="{element_id}"', html, element_id)
        # mapLegend is static (no JS reference); the rest must be wired.
        for element_id in ("resetRange", "rangeLabel", "expandMap",
                           "unitsSelect", "uploadForm",
                           "fromBox", "toBox", "darkToggle",
                           "deleteTrip", "deleteAll", "miHead", "effHead"):
            self.assertIn(element_id, js, element_id)

    def test_dark_theme_css(self):
        css = open(os.path.join(STATIC, "styles.css")).read()
        self.assertIn("body.dark", css)
        self.assertIn("scroll-margin-top", css)

    def test_absolute_node_numbering(self):
        js = open(os.path.join(STATIC, "app.js")).read()
        self.assertIn("absIndexByTs", js)

    def test_strict_slider_gap(self):
        # Sliders snap per point (positions are row indices): the gap is a
        # strict s < e halt, no quantization mapping remains.
        js = open(os.path.join(STATIC, "app.js")).read()
        self.assertIn("haltHandles", js)
        self.assertIn("setSliderRange", js)
        self.assertNotIn("effectiveIndices", js)
        self.assertNotIn("rowPair", js)

    def test_cumulative_columns(self):
        html = open(os.path.join(STATIC, "index.html")).read()
        self.assertIn('<th id="miHead">Mi</th>', html)
        self.assertIn('<th id="effHead">mi/kWh</th>', html)
        # Elev (fixed) is dead data: nothing ever wrote it.
        self.assertNotIn("Elev (fixed)", html)

    def test_dual_slider_bar(self):
        html = open(os.path.join(STATIC, "index.html")).read()
        js = open(os.path.join(STATIC, "app.js")).read()
        for element_id in ("dualbar", "dualtrack", "dualfill"):
            self.assertIn(f'id="{element_id}"', html, element_id)
        self.assertIn("updateSliderFill", js)
        # click-to-flip stacking was removed as overcomplicated; the
        # strict per-point gap keeps the thumbs separable instead.
        self.assertNotIn("maybeFlip", js)
        self.assertNotIn("noteDown", js)
        css = open(os.path.join(STATIC, "styles.css")).read()
        self.assertIn("pointer-events: none", css)
        self.assertIn("#sliderEnd::-webkit-slider-thumb", css)

    def test_range_boxes_are_point_numbers(self):
        html = open(os.path.join(STATIC, "index.html")).read()
        self.assertIn('type="number" id="fromBox"', html)
        self.assertIn('type="number" id="toBox"', html)

    def test_no_keyed_tile_provider(self):
        js = open(os.path.join(STATIC, "app.js")).read()
        self.assertNotIn("cartocdn", js)

    def test_labels_css_present(self):
        css = open(os.path.join(STATIC, "styles.css")).read()
        self.assertIn(".labels", css)


if __name__ == "__main__":
    unittest.main()
