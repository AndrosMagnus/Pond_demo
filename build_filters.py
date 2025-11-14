import json
import gzip
from pathlib import Path
from typing import Dict, Any, Literal

from pmtiles.reader import MemorySource, all_tiles
import mapbox_vector_tile

PMTILES_PATH = Path("piscinas.pmtiles")
OUTPUT_PATH = Path("pond_filters.json")
LAYER_NAME = "piscinas_merged"


class Node:
    __slots__ = (
        "name",
        "count",
        "area",
        "bbox",
        "sum_lng",
        "sum_lat",
        "has_center",
        "regions",
        "places",
    )

    def __init__(self, name: str, level: Literal["country", "region", "place"]):
        self.name = name
        self.count = 0
        self.area = 0.0
        self.bbox = None  # type: ignore[var-annotated]
        self.sum_lng = 0.0
        self.sum_lat = 0.0
        self.has_center = 0
        self.regions: Dict[str, Node] = {} if level == "country" else {}
        self.places: Dict[str, Node] = {} if level == "region" else {}


def update_node(node: Node, lat: float | None, lng: float | None, area: float | None) -> None:
    node.count += 1
    if area is not None:
        node.area += area
    if lat is None or lng is None:
        return

    node.sum_lat += lat
    node.sum_lng += lng
    node.has_center += 1

    if node.bbox is None:
        node.bbox = [lng, lat, lng, lat]
    else:
        node.bbox[0] = min(node.bbox[0], lng)
        node.bbox[1] = min(node.bbox[1], lat)
        node.bbox[2] = max(node.bbox[2], lng)
        node.bbox[3] = max(node.bbox[3], lat)


def build_filters() -> Dict[str, Any]:
    buf = PMTILES_PATH.read_bytes()
    get_bytes = MemorySource(buf)

    countries: Dict[str, Node] = {}

    for (_, _, _), raw_tile in all_tiles(get_bytes):
        try:
            tile = mapbox_vector_tile.decode(gzip.decompress(raw_tile))
        except Exception:
            continue

        layer = tile.get(LAYER_NAME)
        if not layer:
            continue

        for feature in layer.get("features", []):
            props = feature.get("properties") or {}
            country = (props.get("country") or "").strip() or "Sin país"
            region = (props.get("region") or props.get("district") or "").strip() or "Sin región"
            place = (props.get("place") or props.get("label") or "").strip() or "Sin lugar"

            lat = props.get("centroid_lat") or props.get("lat")
            lng = props.get("centroid_lng") or props.get("lng")
            area = props.get("area") or props.get("area_ha")

            try:
                lat = float(lat) if lat is not None else None
            except (TypeError, ValueError):
                lat = None
            try:
                lng = float(lng) if lng is not None else None
            except (TypeError, ValueError):
                lng = None
            try:
                area = float(area) if area is not None else None
            except (TypeError, ValueError):
                area = None

            country_node = countries.setdefault(country, Node(country, "country"))
            regions = country_node.regions
            region_node = regions.setdefault(region, Node(region, "region"))
            places = region_node.places
            place_node = places.setdefault(place, Node(place, "place"))

            update_node(country_node, lat, lng, area)
            update_node(region_node, lat, lng, area)
            update_node(place_node, lat, lng, area)

    def serialize(node: Node, level: Literal["country", "region", "place"]) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "name": node.name,
            "count": node.count,
            "area": round(node.area, 6),
        }
        if node.bbox:
            data["bbox"] = [round(v, 6) for v in node.bbox]
        if node.has_center:
            data["center"] = [
                round(node.sum_lng / node.has_center, 6),
                round(node.sum_lat / node.has_center, 6),
            ]

        if level == "country":
            data["regions"] = {
                name: serialize(child, "region")
                for name, child in sorted(node.regions.items())
            }
        elif level == "region":
            data["places"] = {
                name: serialize(child, "place")
                for name, child in sorted(node.places.items())
            }

        return data

    return {
        "generated_from": PMTILES_PATH.name,
        "layer": LAYER_NAME,
        "countries": {
            name: serialize(node, "country")
            for name, node in sorted(countries.items())
        },
    }


def main() -> None:
    filters = build_filters()
    OUTPUT_PATH.write_text(json.dumps(filters, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} with {len(filters['countries'])} countries.")


if __name__ == "__main__":
    main()
