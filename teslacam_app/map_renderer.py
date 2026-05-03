"""Inline Leaflet map generation for Tesla event locations."""

from __future__ import annotations

import html
from pathlib import Path
from string import Template
from textwrap import dedent


MAP_TEMPLATE = Template(
    dedent(
        """\
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0" />
            <title>Tesla Event Map</title>
            <style>
                $leaflet_css
            </style>
            <style>
                html, body {
                    height: 100%;
                    margin: 0;
                }

                body {
                    background: #0f1720;
                    color: #f4f7fb;
                    font-family: "Segoe UI", Tahoma, sans-serif;
                    overflow: hidden;
                }

                #map {
                    height: 100%;
                    width: 100%;
                    background:
                        radial-gradient(circle at top, rgba(53, 110, 196, 0.25), transparent 52%),
                        linear-gradient(180deg, #16202d 0%, #0f1720 100%);
                }

                .map-banner {
                    position: absolute;
                    top: 12px;
                    left: 12px;
                    z-index: 900;
                    display: none;
                    max-width: min(92%, 320px);
                    padding: 10px 12px;
                    border-radius: 10px;
                    background: rgba(15, 23, 32, 0.88);
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
                    font-size: 13px;
                    line-height: 1.4;
                }

                .coords-card {
                    position: absolute;
                    right: 12px;
                    bottom: 34px;
                    z-index: 900;
                    min-width: 160px;
                    max-width: min(58%, 220px);
                    padding: 10px 12px;
                    border-radius: 12px;
                    background: rgba(15, 23, 32, 0.84);
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.24);
                    backdrop-filter: blur(6px);
                }

                .coords-card__label {
                    margin: 0 0 6px;
                    color: #9cb5cd;
                    font-size: 11px;
                    font-weight: 700;
                    letter-spacing: 0.08em;
                    text-transform: uppercase;
                }

                .coords-card__value {
                    margin: 0;
                    font-size: 14px;
                    line-height: 1.45;
                    overflow-wrap: anywhere;
                }

                .leaflet-container {
                    background: transparent;
                    font: inherit;
                }

                .leaflet-popup-content {
                    max-width: 220px;
                    line-height: 1.35;
                }

                @media (max-width: 430px), (max-height: 230px) {
                    .map-banner {
                        top: 8px;
                        left: 8px;
                        max-width: calc(100% - 16px);
                        padding: 7px 9px;
                        font-size: 12px;
                    }

                    .coords-card {
                        right: 8px;
                        bottom: 30px;
                        min-width: 0;
                        max-width: 54%;
                        padding: 7px 9px;
                        border-radius: 10px;
                    }

                    .coords-card__label {
                        margin-bottom: 4px;
                        font-size: 9px;
                    }

                    .coords-card__value {
                        font-size: 12px;
                        line-height: 1.25;
                    }
                }
            </style>
        </head>
        <body>
            <div id="map"></div>
            <div id="tile-status" class="map-banner">
                Online map tiles are unavailable right now. The event marker and coordinates are still shown.
            </div>
            <div class="coords-card">
                <p class="coords-card__label">Event Coordinates</p>
                <p class="coords-card__value">$location_label</p>
                <p class="coords-card__value">Lat $latitude_label</p>
                <p class="coords-card__value">Lon $longitude_label</p>
            </div>

            <script>
                $leaflet_js
            </script>
            <script>
                const eventLocation = [$latitude, $longitude];
                const tileStatus = document.getElementById("tile-status");

                const map = L.map("map", {
                    zoomControl: true,
                    attributionControl: true,
                }).setView(eventLocation, 16);

                const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
                    maxZoom: 19,
                    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
                });

                let tileFailureCount = 0;
                tiles.on("tileerror", function () {
                    tileFailureCount += 1;
                    if (tileFailureCount > 0) {
                        tileStatus.style.display = "block";
                    }
                });
                tiles.on("load", function () {
                    tileFailureCount = 0;
                    tileStatus.style.display = "none";
                });
                tiles.addTo(map);

                const eventMarker = L.circleMarker(eventLocation, {
                    color: "#d62828",
                    fillColor: "#d62828",
                    fillOpacity: 0.9,
                    radius: 10,
                    weight: 3,
                }).addTo(map).bindPopup("$popup_label");

                if (window.innerWidth > 430 && window.innerHeight > 230) {
                    eventMarker.openPopup();
                }
            </script>
        </body>
        </html>
        """
    )
)


class LeafletMapRenderer:
    """Render a self-contained Leaflet map for ``QWebEngineView``.

    Parameters
    ----------
    base_dir:
        Project directory containing the bundled ``leaflet`` assets.
    """

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir).resolve()
        self.leaflet_dir = self.base_dir / "leaflet"

    def render_html(
        self,
        gps_coords: dict[str, float],
        *,
        location_label: str | None = None,
        popup_label: str | None = None,
    ) -> str:
        """Build the HTML document for one event location.

        Parameters
        ----------
        gps_coords:
            Mapping containing ``lat`` and ``lon`` float values.
        location_label:
            Short label used by the coordinate card.
        popup_label:
            Optional marker popup text for wider map panes.

        Returns
        -------
        str
            Complete HTML document that can be passed to
            ``QWebEngineView.setHtml``.
        """

        latitude = gps_coords.get("lat")
        longitude = gps_coords.get("lon")
        if latitude is None or longitude is None:
            raise ValueError("GPS coordinates must contain 'lat' and 'lon'")

        leaflet_js, leaflet_css = self._leaflet_assets()
        safe_location_label = html.escape(location_label or "Tesla Event")
        safe_popup_label = self._escape_javascript_text(popup_label or location_label or "Tesla Event")
        return MAP_TEMPLATE.substitute(
            leaflet_js=leaflet_js,
            leaflet_css=leaflet_css,
            latitude=f"{float(latitude):.6f}",
            longitude=f"{float(longitude):.6f}",
            latitude_label=f"{float(latitude):.6f}",
            longitude_label=f"{float(longitude):.6f}",
            location_label=safe_location_label,
            popup_label=safe_popup_label,
        )

    def _leaflet_assets(self) -> tuple[str, str]:
        """Load bundled Leaflet JavaScript and CSS from the project tree."""

        leaflet_js_path = self.leaflet_dir / "leaflet.js"
        leaflet_css_path = self.leaflet_dir / "leaflet.css"

        missing_assets = [
            str(path.name)
            for path in (leaflet_js_path, leaflet_css_path)
            if not path.exists()
        ]
        if missing_assets:
            missing_text = ", ".join(missing_assets)
            raise FileNotFoundError(
                f"Missing Leaflet assets in {self.leaflet_dir}: {missing_text}"
            )

        return (
            leaflet_js_path.read_text(encoding="utf-8"),
            leaflet_css_path.read_text(encoding="utf-8"),
        )

    @staticmethod
    def _escape_javascript_text(value: str) -> str:
        """Escape a short text value for use inside a JavaScript string."""

        return (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("'", "\\'")
            .replace("\n", " ")
        )
