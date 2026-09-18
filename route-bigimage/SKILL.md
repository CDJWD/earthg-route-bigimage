---
name: route-bigimage
description: >-
  用地图路线服务与 BigImage 生成路线大图（地名或 lon/lat → 算路 → GeoJSON 叠加出图）。
  Use when the user asks for a route map, path map, 路线图, 导航图, or examples like
  双流机场到天府机场, A到B路线图, or combining map.earthg.cn:7023 routing with BigImage.
  Supports google imagery vs GaoDeElectronicImage; label rules for overlay vs region.
---

# 路线图（Route + BigImage）

外网调用两个服务（**禁止内网 IP**）：

| 服务 | 地址 |
|------|------|
| 算路 | `https://map.earthg.cn:7023/api/route` |
| 出图 | `https://map.earthg.cn:8311/bigimage` |

## 底图 / 注记规矩（必遵）

| 用户意图 | basemap | label | 说明 |
|----------|---------|-------|------|
| 影像上叠路线/框/点等**用户信息** | `google` | **`none`** | 注记会抢视觉，默认关掉 |
| **只要某一区域概况**（少或无用户矢量） | `google` | `gaode`（或 `tianditu`） | 需要地名路网注记时再叠 |
| **不要影像、要电子地图** | **`GaoDeElectronicImage`** | **`none`** | 电子图自带注记，勿再叠 label |

Agent 决策：

1. 用户说「电子图 / 不要影像 / 矢量底图」→ `--basemap GaoDeElectronicImage`（`label=none`）
2. 用户要路线图、框选、标注叠在影像上 → `--basemap google --label none`
3. 用户只要看某片区域长什么样、需要路名地名 → `--basemap google --label gaode`
4. 用户未指定时：有路线/矢量叠加 → 影像 + `label=none`；纯区域浏览 → 影像 + `label=gaode`

## 用户可选选项

向用户确认或从话术推断后，写入脚本参数：

| 选项 | 取值 | 对应参数 |
|------|------|----------|
| 底图 | 影像 / 电子图 | `--basemap google` 或 `--basemap GaoDeElectronicImage` |
| 注记 | 关 / 高德 / 天地图 | `--label none` / `gaode` / `tianditu` |
| 图廓网 | 经纬网 / 方里网 / 无 | `--grid lb` / `xy` / `none` |
| 起终点 | 地名或坐标 | `--from/--to` 或 `--start/--end lon,lat` |

预设（也可直接用 `--preset`）：

```bash
# 路线叠影像（默认规矩：无注记）
python .cursor/skills/route-bigimage/scripts/route_to_bigimage.py --preset route --from 双流机场 --to 天府机场

# 区域概况（影像+注记）
python .cursor/skills/route-bigimage/scripts/route_to_bigimage.py --preset region --from 天府广场 --to 春熙路

# 电子底图路线
python .cursor/skills/route-bigimage/scripts/route_to_bigimage.py --preset electronic --from 双流机场 --to 天府机场
```

| `--preset` | 等价 |
|------------|------|
| `route` | `basemap=google` + `label=none` |
| `region` | `basemap=google` + `label=gaode` |
| `electronic` | `basemap=GaoDeElectronicImage` + `label=none` |

其它常用参数：`--mode`（算路）、`--layer`、`--grid`、`--out`。

环境变量（仅外网）：

- `ROUTE_URL` 默认 `https://map.earthg.cn:7023/api/route`
- `BIGIMAGE_HOST` 默认 `https://map.earthg.cn:8311`
- `BIGIMAGE_TK` **必填**（出图凭证，用环境变量配置，不要写入代码库）

## 手工流程

1. 地名查 [places.json](places.json)，否则 `lon,lat`（经度在前）
2. `POST https://map.earthg.cn:7023/api/route` → `geojson`
3. 合并线 + 起终点 Point → GeoJSON（`stroke` / `title`）
4. `POST https://map.earthg.cn:8311/bigimage?tk=...&basemap=...&label=...&grid=lb&format=geojson`
5. 轮询 `method=getstate` → `method=getfile`

## 坐标系（重要）

| 环节 | 坐标系 |
|------|--------|
| `places.json` / 用户 lon,lat | **WGS84** |
| `map.earthg.cn:7023` 请求与返回几何 | **WGS84**（服务方确认） |
| BigImage `8311` 画布 / 谷歌影像 | **WGS84** |
| `GaoDeElectronicImage` 底图 | 服务端内部 GCJ→WGS 对齐后再画 |

默认 `--route-crs wgs84`：直接把 7023 几何叠到 BigImage，不做火星坐标转换。  
若个别环境返回 GCJ，再用 `--route-crs gcj02`（请求前 WGS→GCJ，出图前 GCJ→WGS）。

## 约定

- Skill / 脚本只访问 `map.earthg.cn:7023` 与 `map.earthg.cn:8311`，不用 `192.168.*`
- 高德底图/注记由 8311 内部做 GCJ 对齐；用户矢量在叠影像前须已是 WGS84
- 出图前确认已设置环境变量 `BIGIMAGE_TK`（勿把 tk 写进仓库）

## 关于

- **产品 / 服务**：EarthG 地图（[map.earthg.cn](https://map.earthg.cn)）
- **维护**：[CDJWD](https://github.com/CDJWD) · 仓库 [earthg-route-bigimage](https://github.com/CDJWD/earthg-route-bigimage)
- 算路 `:7023` · BigImage 出图 `:8311`
