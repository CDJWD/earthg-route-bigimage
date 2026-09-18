#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""路线服务 → BigImage 路线图。

用法示例:
  python route_to_bigimage.py --preset route --from 双流机场 --to 天府机场
  python route_to_bigimage.py --preset electronic --from 双流机场 --to 天府机场
  python route_to_bigimage.py --start 103.9467,30.5785 --end 104.4445,30.3190 --title "双流→天府"

外网: map.earthg.cn:7023（算路）+ map.earthg.cn:8311（BigImage），不用内网。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
PLACES_PATH = os.path.join(SKILL_DIR, "places.json")

ROUTE_URL = os.environ.get("ROUTE_URL", "https://map.earthg.cn:7023/api/route")
# 外网专用：只用 map.earthg.cn:8311，不用内网
BIGIMAGE_HOST = os.environ.get("BIGIMAGE_HOST", "https://map.earthg.cn:8311").rstrip("/")
# 可选：服务端「瓦片收费=false」时可不传；收费开启时 bigimage GET 需要有效 tk
TK = os.environ.get("BIGIMAGE_TK", "").strip()

CTX = ssl._create_unverified_context()

PRESETS = {
    # 影像上叠用户信息 → 不要注记
    "route": {"basemap": "google", "label": "none"},
    # 只要区域概况 → 叠注记
    "region": {"basemap": "google", "label": "gaode"},
    # 电子地图，不要影像
    "electronic": {"basemap": "GaoDeElectronicImage", "label": "none"},
}

# 7023：输入/输出均为 WGS84（以服务方说明为准）
DEFAULT_ROUTE_CRS = "wgs84"


def http_json(method: str, url: str, body: Optional[dict] = None, timeout: int = 90) -> Any:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, context=CTX, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_bytes(method: str, url: str, data: Optional[bytes] = None, headers: Optional[dict] = None, timeout: int = 180) -> bytes:
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(req, context=CTX, timeout=timeout) as r:
        return r.read()


def load_places() -> Dict[str, List[float]]:
    if not os.path.isfile(PLACES_PATH):
        return {}
    with open(PLACES_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    return {str(k).strip(): list(v) for k, v in raw.items()}


def parse_lonlat(text: str) -> Tuple[float, float]:
    parts = re.split(r"[,，\s]+", text.strip())
    if len(parts) != 2:
        raise ValueError(f"坐标格式应为 lon,lat：{text}")
    return float(parts[0]), float(parts[1])


def resolve_place(name: Optional[str], lonlat: Optional[str], places: Dict[str, List[float]]) -> Tuple[float, float, str]:
    if lonlat:
        lon, lat = parse_lonlat(lonlat)
        return lon, lat, name or f"{lon},{lat}"
    if not name:
        raise ValueError("需要地名或 lon,lat")
    key = name.strip()
    if key in places:
        lon, lat = places[key]
        return float(lon), float(lat), key
    # 模糊包含匹配
    for k, v in places.items():
        if key in k or k in key:
            return float(v[0]), float(v[1]), k
    raise KeyError(
        f"未知地名「{key}」。请用 --start/--end 传 lon,lat，或在 places.json 中补充。"
    )


# --- CRS: 7023 路网为 GCJ-02；BigImage 画布为 WGS84 ---
def _out_of_china(lon: float, lat: float) -> bool:
    return not (72.004 <= lon <= 137.8347 and 0.8293 <= lat <= 55.8271)


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * (abs(x) ** 0.5)
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * (abs(x) ** 0.5)
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lon: float, lat: float) -> Tuple[float, float]:
    """与 Common.ProG.ConvertGPS.gps84_To_Gcj02 一致。"""
    if _out_of_china(lon, lat):
        return lon, lat
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - 0.00669342162296594323 * magic * magic
    sqrtmagic = math.sqrt(magic)
    a = 6378245.0
    dlat = (dlat * 180.0) / ((a * (1 - 0.00669342162296594323)) / (magic * sqrtmagic) * math.pi)
    dlon = (dlon * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
    return lon + dlon, lat + dlat


def gcj02_to_wgs84(lon: float, lat: float) -> Tuple[float, float]:
    """与 Common.ProG.ConvertGPS.gcj02_To_Gps84 一致（与 BigImage 高德 Warp 互逆）。"""
    t_lon, t_lat = wgs84_to_gcj02(lon, lat)
    return lon * 2 - t_lon, lat * 2 - t_lat


def convert_route_geojson_to_wgs84(route: dict) -> dict:
    """把 7023 返回的 GCJ 几何转到 WGS84，供 BigImage 叠加。"""
    out = dict(route)
    if isinstance(out.get("start"), dict):
        s = dict(out["start"])
        lon, lat = gcj02_to_wgs84(float(s["lon"]), float(s["lat"]))
        s["lon"], s["lat"] = lon, lat
        out["start"] = s
    if isinstance(out.get("end"), dict):
        e = dict(out["end"])
        lon, lat = gcj02_to_wgs84(float(e["lon"]), float(e["lat"]))
        e["lon"], e["lat"] = lon, lat
        out["end"] = e

    gj = out.get("geojson")
    if not isinstance(gj, dict):
        return out
    feats = []
    for feat in gj.get("features") or []:
        f = dict(feat)
        geom = dict(f.get("geometry") or {})
        coords = geom.get("coordinates")
        if geom.get("type") == "LineString" and coords:
            geom["coordinates"] = [[*gcj02_to_wgs84(float(c[0]), float(c[1]))] for c in coords]
        f["geometry"] = geom
        feats.append(f)
    out["geojson"] = {"type": "FeatureCollection", "features": feats}
    return out


def pick_layer(span_deg: float, target_px: int = 1800) -> int:
    """按经纬度跨度估 layer，使大致宽度接近 target_px。"""
    span = max(span_deg, 1e-6)
    for layer in range(18, 8, -1):
        res = 360.0 / (2 ** layer) / 256.0
        if span / res <= target_px * 1.35:
            return layer
    return 10


def build_draw_geojson(
    route: dict,
    start_title: str,
    end_title: str,
    stroke: str = "#FFCC00",
    stroke_width: float = 6,
) -> dict:
    src = route.get("geojson") or {}
    coords_all: List[List[float]] = []
    for feat in src.get("features") or []:
        geom = feat.get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates") or []
        if len(coords) >= 2:
            coords_all.extend(coords)
    if not coords_all:
        raise RuntimeError("路线 GeoJSON 无 LineString")

    merged: List[List[float]] = []
    for c in coords_all:
        if not merged or abs(merged[-1][0] - c[0]) > 1e-9 or abs(merged[-1][1] - c[1]) > 1e-9:
            merged.append(c)

    start = route.get("start") or {}
    end = route.get("end") or {}
    slon = float(start.get("lon", merged[0][0]))
    slat = float(start.get("lat", merged[0][1]))
    elon = float(end.get("lon", merged[-1][0]))
    elat = float(end.get("lat", merged[-1][1]))

    features_out: List[dict] = [
        {
            "type": "Feature",
            "properties": {
                "title": f"{start_title} → {end_title}",
                "stroke": stroke,
                "stroke-width": stroke_width,
                "stroke-opacity": 0.95,
                "note": f"{route.get('total_length_km')} km / {route.get('total_time_min')} min",
            },
            "geometry": {"type": "LineString", "coordinates": merged},
        },
        {
            "type": "Feature",
            "properties": {"title": start_title, "stroke": "#00FF66", "stroke-width": 10},
            "geometry": {"type": "Point", "coordinates": [slon, slat]},
        },
        {
            "type": "Feature",
            "properties": {"title": end_title, "stroke": "#FF3366", "stroke-width": 10},
            "geometry": {"type": "Point", "coordinates": [elon, elat]},
        },
    ]
    return {"type": "FeatureCollection", "features": features_out}


def bounds_of_geojson(gj: dict, pad_ratio: float = 0.08) -> Tuple[float, float, float, float]:
    xs: List[float] = []
    ys: List[float] = []

    def walk(coords):
        if not coords:
            return
        if isinstance(coords[0], (int, float)):
            xs.append(float(coords[0]))
            ys.append(float(coords[1]))
            return
        for c in coords:
            walk(c)

    for f in gj.get("features") or []:
        walk((f.get("geometry") or {}).get("coordinates"))
    if not xs:
        raise RuntimeError("GeoJSON 无坐标")
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    dx = max(maxx - minx, 0.01)
    dy = max(maxy - miny, 0.01)
    return (
        minx - dx * pad_ratio,
        maxx + dx * pad_ratio,
        miny - dy * pad_ratio,
        maxy + dy * pad_ratio,
    )


def tk_qs() -> str:
    return f"&tk={urllib.parse.quote(TK)}" if TK else ""


def pick_bigimage_host() -> str:
    host = BIGIMAGE_HOST
    if "192.168." in host or host.startswith("http://10."):
        raise RuntimeError(f"禁止内网 BigImage 地址，请用 https://map.earthg.cn:8311，当前={host}")
    try:
        url = f"{host}/bigimage?l1=104.06&l2=104.07&b1=30.65&b2=30.66&layer=15{tk_qs()}"
        http_bytes("GET", url, timeout=30)
        return host
    except Exception as e:
        raise RuntimeError(f"无法连接 BigImage：{host}；错误：{e}") from e


def submit_and_download(
    host: str,
    geojson: dict,
    name: str,
    layer: int,
    label: str,
    grid: str,
    out_path: str,
    title: str,
    basemap: str = "google",
) -> str:
    qs_dict = {
        "name": name,
        "layer": str(layer),
        "format": "geojson",
        "label": label,
        "grid": grid,
        "title": title,
        "basemap": basemap,
    }
    if TK:
        qs_dict["tk"] = TK
    qs = urllib.parse.urlencode(qs_dict)
    body = json.dumps(geojson, ensure_ascii=False).encode("utf-8")
    post_url = f"{host}/bigimage?{qs}"
    resp = http_bytes(
        "POST",
        post_url,
        data=body,
        headers={"Content-Type": "application/geo+json; charset=utf-8"},
        timeout=120,
    ).decode("utf-8", "ignore")
    print("POST", resp, flush=True)
    ok = ("提交完成" in resp) or resp.startswith("1,") or resp.strip() == "1"
    if (not ok) or resp.startswith("0,") or ("失败" in resp):
        raise RuntimeError(f"BigImage POST 失败: {resp}")

    for i in range(90):
        time.sleep(2)
        st = http_bytes(
            "GET", f"{host}/bigimage?method=getstate&name={urllib.parse.quote(name)}{tk_qs()}", timeout=60
        ).decode("utf-8", "ignore")
        if i % 5 == 0:
            print("state", st[:120], flush=True)
        data = http_bytes(
            "GET", f"{host}/bigimage?method=getfile&name={urllib.parse.quote(name)}{tk_qs()}", timeout=120
        )
        if data[:2] == b"\xff\xd8" and len(data) > 2000:
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(data)
            return out_path
        if "失败" in st or "error" in st.lower():
            raise RuntimeError(f"出图失败: {st}")
    raise TimeoutError("等待 BigImage 超时")


def main() -> int:
    ap = argparse.ArgumentParser(description="路线计算 + BigImage 出图（外网 7023 + 8311）")
    ap.add_argument("--from", dest="from_name", help="起点地名")
    ap.add_argument("--to", dest="to_name", help="终点地名")
    ap.add_argument("--start", help="起点 lon,lat（WGS84）")
    ap.add_argument("--end", help="终点 lon,lat（WGS84）")
    ap.add_argument("--mode", default="fastest", help="路线 mode，默认 fastest")
    ap.add_argument("--title", default="", help="图标题")
    ap.add_argument(
        "--preset",
        default="route",
        choices=list(PRESETS.keys()),
        help="route=影像叠路线无注记；region=影像+注记；electronic=高德电子图",
    )
    ap.add_argument(
        "--basemap",
        default="",
        choices=["", "google", "gaode", "GaoDeElectronicImage", "electronic"],
        help="覆盖 preset：google=影像；GaoDeElectronicImage=电子图",
    )
    ap.add_argument(
        "--label",
        default="",
        choices=["", "gaode", "tianditu", "none"],
        help="覆盖 preset；影像叠用户信息时应用 none",
    )
    ap.add_argument(
        "--route-crs",
        default=DEFAULT_ROUTE_CRS,
        choices=["gcj02", "wgs84"],
        help="7023 坐标系：默认 wgs84（服务收发均为 WGS84）；仅当确认返回 GCJ 时用 gcj02",
    )
    ap.add_argument("--grid", default="lb", choices=["lb", "xy", "none", ""])
    ap.add_argument("--layer", type=int, default=0, help="瓦片层级；0=按跨度自动")
    ap.add_argument("--stroke", default="#00E5FF")
    ap.add_argument("--stroke-width", type=float, default=6)
    ap.add_argument("--out", default="", help="输出 jpg 路径")
    ap.add_argument("--outdir", default="", help="输出目录，默认 bigimage_test")
    args = ap.parse_args()

    places = load_places()
    slon, slat, sname = resolve_place(args.from_name, args.start, places)
    elon, elat, ename = resolve_place(args.to_name, args.end, places)
    title = args.title or f"{sname} → {ename}"

    preset = PRESETS[args.preset]
    basemap = preset["basemap"]
    label = preset["label"]

    if args.basemap:
        basemap_key = args.basemap.lower().replace("_", "").replace("-", "")
        if basemap_key in ("gaode", "gaodeelectronicimage", "electronic", "amap", "vec"):
            basemap = "GaoDeElectronicImage"
            if not args.label:
                label = "none"
        else:
            basemap = "google"

    if args.label:
        label = args.label
    elif basemap == "GaoDeElectronicImage":
        label = "none"

    print(f"route {sname} ({slon},{slat}) -> {ename} ({elon},{elat})", flush=True)
    print(f"preset={args.preset} basemap={basemap} label={label} route_crs={args.route_crs}", flush=True)

    # places/输入为 WGS84；7023 路网按 GCJ 消费时先转再算路
    if args.route_crs == "gcj02":
        req_s = wgs84_to_gcj02(slon, slat)
        req_e = wgs84_to_gcj02(elon, elat)
        print(f"route-req GCJ {req_s} -> {req_e}", flush=True)
    else:
        req_s, req_e = (slon, slat), (elon, elat)

    route = http_json(
        "POST",
        ROUTE_URL,
        {"start": [req_s[0], req_s[1]], "end": [req_e[0], req_e[1]], "mode": args.mode},
        timeout=90,
    )
    if not route.get("ok"):
        raise RuntimeError(f"路线失败: {route}")
    print(
        f"ok km={route.get('total_length_km')} min={route.get('total_time_min')} engine={route.get('engine')}",
        flush=True,
    )

    # BigImage 画布为 WGS84：GCJ 几何需转回再叠加
    if args.route_crs == "gcj02":
        route = convert_route_geojson_to_wgs84(route)
        print("converted route geometry GCJ02 → WGS84 for BigImage", flush=True)

    draw = build_draw_geojson(route, sname, ename, stroke=args.stroke, stroke_width=args.stroke_width)
    l1, l2, b1, b2 = bounds_of_geojson(draw)
    span = max(l2 - l1, b2 - b1)
    layer = args.layer or pick_layer(span)
    print(f"extent {l1:.5f},{b1:.5f} - {l2:.5f},{b2:.5f} layer={layer}", flush=True)

    host = pick_bigimage_host()
    print("bigimage", host, flush=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"route{stamp.replace('_','')[-10:]}"
    repo_test = os.path.abspath(os.path.join(SKILL_DIR, "..", "..", "..", "bigimage_test"))
    outdir = os.path.abspath(args.outdir or (repo_test if os.path.isdir(repo_test) else os.getcwd()))
    out = args.out or os.path.join(outdir, f"route_{stamp}.jpg")

    grid = "" if args.grid in ("none", "") else args.grid
    path = submit_and_download(host, draw, name, layer, label, grid, out, title, basemap=basemap)
    meta = {
        "ok": True,
        "title": title,
        "preset": args.preset,
        "start": {"name": sname, "lon": slon, "lat": slat},
        "end": {"name": ename, "lon": elon, "lat": elat},
        "km": route.get("total_length_km"),
        "min": route.get("total_time_min"),
        "layer": layer,
        "basemap": basemap,
        "label": label,
        "host": host,
        "image": path,
    }
    print(json.dumps(meta, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("ERROR", e, file=sys.stderr, flush=True)
        sys.exit(1)
