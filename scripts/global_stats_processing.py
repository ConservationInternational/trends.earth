from __future__ import annotations

import multiprocessing
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
from osgeo import gdal, ogr, osr
from shapely import wkb as shapely_wkb
from tqdm.auto import tqdm

TaskArgs = tuple[str, bytes, int, str, str, np.ndarray, float | None]

MAX_CHUNK_COLS = 2048
MAX_CHUNK_ROWS = 2048


def process_country_band_task(args: TaskArgs) -> list[dict] | None:
    """Process a single (country, band) task in a worker process."""
    (
        iso3cd,
        geom_wkb,
        band_num,
        band_name,
        raster_path,
        pixel_areas_by_row,
        nodata_val,
    ) = args

    try:
        gdal.UseExceptions()
        ds_local = gdal.Open(raster_path, gdal.GA_ReadOnly)
        if ds_local is None:
            raise RuntimeError(f"Unable to open raster '{raster_path}' in worker")

        try:
            band = ds_local.GetRasterBand(band_num)
            gt_local = ds_local.GetGeoTransform()

            geom = shapely_wkb.loads(geom_wkb)
            window = _calc_pixel_window(
                geom, gt_local, ds_local.RasterXSize, ds_local.RasterYSize
            )
            if window is None:
                return None

            ul_x, ul_y, lr_x, lr_y, win_xsize, win_ysize = window
            win_gt = (
                gt_local[0] + ul_x * gt_local[1],
                gt_local[1],
                0,
                gt_local[3] + ul_y * gt_local[5],
                0,
                gt_local[5],
            )

            block_xsize, block_ysize = band.GetBlockSize()
            chunk_cols = _compute_chunk_size(win_xsize, block_xsize, MAX_CHUNK_COLS)
            chunk_rows = _compute_chunk_size(win_ysize, block_ysize, MAX_CHUNK_ROWS)

            aggregated_pixel_count = 0
            aggregated_total_area = 0.0
            aggregated_total_area_including_nodata = 0.0
            value_stats: dict[int, list[float]] = {}

            # Process the raster window in tiles to keep memory usage bounded.
            for y_start in range(ul_y, lr_y, chunk_rows):
                y_end = min(y_start + chunk_rows, lr_y)
                chunk_height = y_end - y_start
                pixel_areas_chunk = np.ascontiguousarray(
                    pixel_areas_by_row[y_start:y_end], dtype=np.float64
                )

                for x_start in range(ul_x, lr_x, chunk_cols):
                    x_end = min(x_start + chunk_cols, lr_x)
                    chunk_width = x_end - x_start

                    data_chunk = band.ReadAsArray(
                        x_start, y_start, chunk_width, chunk_height
                    )
                    if data_chunk is None:
                        raise RuntimeError(f"Failed to read raster data for {iso3cd}")

                    chunk_gt = (
                        win_gt[0] + (x_start - ul_x) * win_gt[1],
                        win_gt[1],
                        0,
                        win_gt[3] + (y_start - ul_y) * win_gt[5],
                        0,
                        win_gt[5],
                    )

                    mask_chunk = _create_geom_mask(
                        geom,
                        chunk_width,
                        chunk_height,
                        chunk_gt,
                        ds_local.GetProjection(),
                    )

                    if not mask_chunk.any():
                        continue

                    (
                        chunk_pixel_count,
                        chunk_total_area,
                        chunk_total_area_including_nodata,
                        unique_values,
                        value_counts,
                        value_areas,
                    ) = _calculate_zonal_stats_optimized_worker(
                        np.ascontiguousarray(data_chunk),
                        mask_chunk,
                        pixel_areas_chunk,
                        nodata_val,
                    )

                    if chunk_total_area_including_nodata == 0:
                        continue

                    aggregated_pixel_count += chunk_pixel_count
                    aggregated_total_area += chunk_total_area
                    aggregated_total_area_including_nodata += (
                        chunk_total_area_including_nodata
                    )

                    for idx, value in enumerate(unique_values):
                        stats = value_stats.setdefault(int(value), [0.0, 0.0])
                        stats[0] += float(value_counts[idx])
                        stats[1] += float(value_areas[idx])

            if (
                aggregated_pixel_count == 0
                and aggregated_total_area_including_nodata == 0
            ):
                return None

            unique_values, value_counts, value_areas = _collapse_value_stats(
                value_stats
            )

            return _format_results(
                iso3cd,
                band_num,
                band_name,
                aggregated_total_area,
                aggregated_total_area_including_nodata,
                unique_values,
                value_counts,
                value_areas,
            )
        finally:
            ds_local = None

    except Exception as exc:  # pragma: no cover - exercised via multiprocessing
        raise RuntimeError(
            f"Worker failed for {iso3cd}, band {band_num} ({band_name}): {exc}"
        ) from exc


def run_parallel_processing(
    tasks: Sequence[TaskArgs],
    total_iterations: int,
    max_workers: int | None = None,
    description: str = "Processing",
) -> list[dict]:
    """Execute all tasks in parallel and return aggregated statistics."""
    if not tasks:
        return []

    workers = max_workers or multiprocessing.cpu_count()
    results: list[dict] = []

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(process_country_band_task, task): task for task in tasks
        }

        with tqdm(total=total_iterations, desc=description) as pbar:
            for future in as_completed(futures):
                iso3cd, _, band_num, band_name, _, _, _ = futures[future]

                try:
                    stats_list = future.result()
                    if stats_list is not None:
                        results.extend(stats_list)
                    else:
                        print(
                            f"Warning: No valid pixels found for {iso3cd}, band {band_num} ({band_name})"
                        )
                except Exception:
                    # Propagate error after logging context for easier debugging
                    print(f"\nError processing {iso3cd}, band {band_num} ({band_name})")
                    raise
                finally:
                    pbar.update(1)

    return results


def _calculate_zonal_stats_optimized_worker(
    data, mask, pixel_areas_by_row, nodata_value
):
    """Calculate zonal statistics for a masked raster window in a single pass."""
    if data.shape[0] != pixel_areas_by_row.shape[0]:
        raise ValueError("Row counts for data and pixel areas do not match")

    mask = mask.astype(bool, copy=False)
    row_pixel_counts = mask.sum(axis=1, dtype=np.int64)
    total_area_including_nodata = float(np.dot(row_pixel_counts, pixel_areas_by_row))

    if total_area_including_nodata == 0.0:
        return (
            0,
            0.0,
            0.0,
            np.empty(0, dtype=np.int32),
            np.empty(0, dtype=np.int64),
            np.empty(0, dtype=np.float64),
        )

    if nodata_value is None:
        valid_mask = mask
    else:
        valid_mask = mask & (data != nodata_value)

    pixel_count = int(valid_mask.sum())
    row_valid_counts = valid_mask.sum(axis=1, dtype=np.int64)
    total_area = float(np.dot(row_valid_counts, pixel_areas_by_row))

    if pixel_count == 0:
        return (
            pixel_count,
            total_area,
            total_area_including_nodata,
            np.empty(0, dtype=np.int32),
            np.empty(0, dtype=np.int64),
            np.empty(0, dtype=np.float64),
        )

    row_indices, col_indices = np.nonzero(valid_mask)
    valid_values = data[row_indices, col_indices].astype(np.int32, copy=False)
    pixel_weights = pixel_areas_by_row[row_indices].astype(np.float64, copy=False)

    unique_values, inverse = np.unique(valid_values, return_inverse=True)
    value_counts = np.bincount(inverse, minlength=unique_values.size).astype(
        np.int64, copy=False
    )
    value_areas = np.bincount(
        inverse, weights=pixel_weights, minlength=unique_values.size
    ).astype(np.float64, copy=False)

    return (
        pixel_count,
        total_area,
        total_area_including_nodata,
        unique_values,
        value_counts,
        value_areas,
    )


def _collapse_value_stats(value_stats: dict[int, list[float]]):
    """Convert aggregated value statistics into sorted numpy arrays."""
    if not value_stats:
        return (
            np.empty(0, dtype=np.int32),
            np.empty(0, dtype=np.int64),
            np.empty(0, dtype=np.float64),
        )

    sorted_items = sorted(value_stats.items())
    unique_values = np.array([item[0] for item in sorted_items], dtype=np.int32)
    value_counts = np.array(
        [round(item[1][0]) for item in sorted_items], dtype=np.int64
    )
    value_areas = np.array(
        [float(item[1][1]) for item in sorted_items], dtype=np.float64
    )
    return unique_values, value_counts, value_areas


def _calc_pixel_window(geom, gt_local, raster_xsize, raster_ysize):
    """Compute pixel window bounds for the given geometry."""
    minx, miny, maxx, maxy = geom.bounds

    ul_x = int((minx - gt_local[0]) / gt_local[1])
    ul_y = int((maxy - gt_local[3]) / gt_local[5])
    lr_x = int((maxx - gt_local[0]) / gt_local[1]) + 1
    lr_y = int((miny - gt_local[3]) / gt_local[5]) + 1

    ul_x = max(0, ul_x)
    ul_y = max(0, ul_y)
    lr_x = min(raster_xsize, lr_x)
    lr_y = min(raster_ysize, lr_y)

    win_xsize = lr_x - ul_x
    win_ysize = lr_y - ul_y
    if win_xsize <= 0 or win_ysize <= 0:
        return None

    return ul_x, ul_y, lr_x, lr_y, win_xsize, win_ysize


def _create_geom_mask(geom, win_xsize, win_ysize, win_gt, projection):
    """Rasterize geometry into a boolean mask for the given window."""
    mem_driver = gdal.GetDriverByName("MEM")
    mem_ds = mem_driver.Create("", win_xsize, win_ysize, 1, gdal.GDT_Byte)
    mem_ds.SetGeoTransform(win_gt)
    mem_ds.SetProjection(projection)

    mem_band = mem_ds.GetRasterBand(1)
    mem_band.Fill(0)

    ogr_geom = ogr.CreateGeometryFromWkb(geom.wkb)
    mem_vec_driver = ogr.GetDriverByName("MEM")
    mem_vec_ds = mem_vec_driver.CreateDataSource("")
    mem_vec_layer = mem_vec_ds.CreateLayer(
        "poly", srs=osr.SpatialReference(wkt=projection)
    )
    mem_vec_feature = ogr.Feature(mem_vec_layer.GetLayerDefn())
    mem_vec_feature.SetGeometry(ogr_geom)
    mem_vec_layer.CreateFeature(mem_vec_feature)

    gdal.RasterizeLayer(mem_ds, [1], mem_vec_layer, burn_values=[1])
    mask = mem_band.ReadAsArray().astype(bool)

    mem_ds = None
    mem_vec_ds = None

    return mask


def _compute_chunk_size(window_size: int, block_size: int, max_chunk_size: int) -> int:
    """Choose a chunk size that respects driver block sizes and memory limits."""
    if window_size <= 0:
        return 0

    chunk = min(max_chunk_size, window_size)
    if block_size > 0:
        chunk = max(chunk, block_size)

    return min(chunk, window_size)


def _format_results(
    iso3cd: str,
    band_num: int,
    band_name: str,
    total_area: float,
    total_area_including_nodata: float,
    unique_values,
    value_counts,
    value_areas,
) -> list[dict]:
    """Convert raw statistics into the expected list-of-dicts structure."""
    base = {
        "iso3cd": iso3cd,
        "band_number": band_num,
        "band_name": band_name,
        "total_area_km2": total_area / 1e6,
        "total_area_including_nodata_km2": total_area_including_nodata / 1e6,
    }

    results: list[dict] = []
    for idx in range(len(unique_values)):
        row = base.copy()
        row["value"] = int(unique_values[idx])
        row["pixel_count"] = int(value_counts[idx])
        if total_area_including_nodata > 0:
            row["percent"] = (value_areas[idx] / total_area_including_nodata) * 100
        else:
            row["percent"] = 0.0
        row["area_km2"] = value_areas[idx] / 1e6
        results.append(row)

    return results


if __name__ == "__main__":
    print(
        "This module provides multiprocessing helpers for the global statistics notebook. "
        "Import and call 'run_parallel_processing' from your driver script or notebook."
    )
