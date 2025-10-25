"""
Replicate the ArcPy lab workflow using GeoPandas/Shapely.

Steps:
- Locate an input geodatabase (.gdb) or fall back to creating sample input when --cwd-safe is used.
- Read layers: GaragePoints, LandUse, Structures, Trees (if available).
- Load provided CSV (if any) as a table in outputs folder.
- Reproject Structures to GaragePoints CRS (or pick a projected CRS if geographic).
- Buffer GaragePoints by 150 meters.
- Intersect buffer with Structures.
- Write outputs to a GeoPackage (`outputs/Lab4_Output.gpkg`).

Usage:
    python lab4_geopandas.py [--input INPUT_GDB_OR_FOLDER] [--output OUTPUT_GPKG] [--cwd-safe]

"""
from __future__ import annotations
import os
import argparse
import json
from typing import Optional

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, Polygon
from pyproj import CRS

# Defaults
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_INPUT = None  # auto-detect
OUTPUT_DIR = os.path.join(SCRIPT_DIR, 'outputs')
DEFAULT_OUTPUT = os.path.join(OUTPUT_DIR, 'Lab4_Output.gpkg')
LAYERS_TO_KEEP = ["GaragePoints", "LandUse", "Structures", "Trees"]
CSV_BASENAME = 'garages.csv'


def find_first_gdb_or_folder(base_dir: str) -> Optional[str]:
    # Look for .gdb directories
    for f in os.listdir(base_dir):
        if f.lower().endswith('.gdb') and os.path.isdir(os.path.join(base_dir, f)):
            return os.path.join(base_dir, f)
    # look for geopackage
    for f in os.listdir(base_dir):
        if f.lower().endswith('.gpkg'):
            return os.path.join(base_dir, f)
    return None


def create_sample_inputs(base_dir: str) -> dict:
    """Create sample GaragePoints (points) and Structures (polygons) and a CSV table."""
    data_dir = os.path.join(base_dir, 'lab4_sample')
    os.makedirs(data_dir, exist_ok=True)

    # Create sample points (two garages)
    garages = gpd.GeoDataFrame({
        'id': ['G1', 'G2'],
        'capacity': [20, 30]
    }, geometry=[Point(-96.5, 30.5), Point(-96.495, 30.505)], crs='EPSG:4326')

    # Create sample structures (two polygons)
    poly1 = Polygon([(-96.501, 30.499), (-96.492, 30.499), (-96.492, 30.508), (-96.501, 30.508), (-96.501, 30.499)])
    poly2 = Polygon([(-96.4955, 30.502), (-96.486, 30.502), (-96.486, 30.511), (-96.4955, 30.511), (-96.4955, 30.502)])
    structures = gpd.GeoDataFrame({'id': ['S1', 'S2']}, geometry=[poly1, poly2], crs='EPSG:4326')

    # Write to a GeoPackage so we can read layers by name
    sample_gpkg = os.path.join(data_dir, 'lab4_input.gpkg')
    garages.to_file(sample_gpkg, layer='GaragePoints', driver='GPKG')
    structures.to_file(sample_gpkg, layer='Structures', driver='GPKG')

    # CSV table
    csv_path = os.path.join(data_dir, CSV_BASENAME)
    garages[['id','capacity']].to_csv(csv_path, index=False)

    return {'gpkg': sample_gpkg, 'csv': csv_path}


def read_layer_safe(source_path: str, layer_name: str) -> Optional[gpd.GeoDataFrame]:
    try:
        gdf = gpd.read_file(source_path, layer=layer_name)
        return gdf
    except Exception as e:
        print(f"Warning: could not read layer {layer_name} from {source_path}: {e}")
        return None


def ensure_projected_for_buffer(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Return a GeoDataFrame in a projected CRS suitable for meter-based buffer.
    If gdf is geographic, estimate a UTM CRS from centroid and project.
    """
    if gdf is None or gdf.empty:
        return gdf
    crs = gdf.crs
    if crs is None or crs.is_geographic:
        # estimate UTM by centroid of the combined geometry
        centroid = gdf.unary_union.centroid
        try:
            utm_crs = CRS.from_user_input(CRS.estimate_utm_crs(centroid.y, centroid.x))
        except Exception:
            # fallback to Web Mercator (units in meters)
            utm_crs = CRS.from_epsg(3857)
        return gdf.to_crs(utm_crs)
    return gdf


def main():
    parser = argparse.ArgumentParser(description='Lab4: convert ArcPy workflow to GeoPandas')
    parser.add_argument('--input', '-i', help='Input .gdb or .gpkg or folder with data', default=DEFAULT_INPUT)
    parser.add_argument('--output', '-o', help='Output GeoPackage path', default=DEFAULT_OUTPUT)
    parser.add_argument('--cwd-safe', action='store_true', help='Create sample inputs if no input found')
    parser.add_argument('--force-sample', action='store_true', help='Force creation of sample inputs even if input detected')
    args = parser.parse_args()

    base_dir = SCRIPT_DIR
    input_src = args.input
    output_path = args.output
    cwd_safe = args.cwd_safe

    force_sample = args.force_sample

    if force_sample:
        print('Force-sample requested: creating sample inputs...')
        sample = create_sample_inputs(base_dir)
        input_src = sample['gpkg']
        csv_path = sample['csv']
    elif input_src is None:
        found = find_first_gdb_or_folder(base_dir)
        if found:
            input_src = found
            print(f"Auto-detected input source: {input_src}")
        else:
            if cwd_safe:
                print("No input GDB/GPKG found; creating sample inputs (cwd-safe)...")
                sample = create_sample_inputs(base_dir)
                input_src = sample['gpkg']
                csv_path = sample['csv']
            else:
                print("No input geodatabase found and --cwd-safe not set. Exiting.")
                return
    else:
        csv_path = os.path.join(base_dir, CSV_BASENAME) if os.path.exists(os.path.join(base_dir, CSV_BASENAME)) else None

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    print(f"Reading layers from: {input_src}")

    # Read GaragePoints and Structures (if present)
    garage_gdf = read_layer_safe(input_src, 'GaragePoints')
    structures_gdf = read_layer_safe(input_src, 'Structures')

    # If Structures missing but layer named differently, attempt to read first layer
    if garage_gdf is None and structures_gdf is None:
        print("No GaragePoints or Structures layers found in input. Listing available layers (if supported):")
        try:
            import fiona
            layers = fiona.listlayers(input_src)
            print(layers)
        except Exception as e:
            print('Could not list layers:', e)
        print('Exiting.')
        return

    # If garage present, use its CRS as target; else use structures CRS
    target_crs = None
    if garage_gdf is not None and garage_gdf.crs is not None:
        target_crs = garage_gdf.crs
    elif structures_gdf is not None and structures_gdf.crs is not None:
        target_crs = structures_gdf.crs

    print('CRS before reprojection:')
    if garage_gdf is not None:
        print('  GaragePoints CRS:', garage_gdf.crs)
    if structures_gdf is not None:
        print('  Structures CRS:', structures_gdf.crs)

    # Reproject both to target_crs (or ensure projected for buffer)
    if target_crs is not None:
        if garage_gdf is not None and garage_gdf.crs != target_crs:
            garage_gdf = garage_gdf.to_crs(target_crs)
        if structures_gdf is not None and structures_gdf.crs != target_crs:
            structures_gdf = structures_gdf.to_crs(target_crs)

    print('After aligning CRS:')
    if garage_gdf is not None:
        print('  GaragePoints CRS:', garage_gdf.crs)
    if structures_gdf is not None:
        print('  Structures CRS:', structures_gdf.crs)

    # Prepare projected versions for buffer operation (in meters)
    if garage_gdf is not None:
        garage_proj = ensure_projected_for_buffer(garage_gdf)
    else:
        garage_proj = None
    if structures_gdf is not None:
        # structures must be in same CRS as garage_proj for intersection; reproject if necessary
        if garage_proj is not None:
            structures_proj = structures_gdf.to_crs(garage_proj.crs)
        else:
            structures_proj = ensure_projected_for_buffer(structures_gdf)
    else:
        structures_proj = None

    # Buffer analysis: 150 meters
    buffer_m = 150
    if garage_proj is not None and not garage_proj.empty:
        garage_buffer = garage_proj.copy()
        garage_buffer['geometry'] = garage_buffer.geometry.buffer(buffer_m)
    else:
        garage_buffer = None

    # Intersect analysis: buffer with structures
    if garage_buffer is not None and structures_proj is not None and not structures_proj.empty:
        intersect_gdf = gpd.overlay(structures_proj, garage_buffer, how='intersection')
    else:
        intersect_gdf = gpd.GeoDataFrame(columns=['geometry'], crs=(garage_buffer.crs if garage_buffer is not None else None))

    # Save outputs to GeoPackage
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    print(f"Writing outputs to {output_path}")
    driver = 'GPKG'
    try:
        if garage_proj is not None:
            garage_proj.to_file(output_path, layer='GaragePoints_PRJ', driver=driver)
        if structures_proj is not None:
            structures_proj.to_file(output_path, layer='Structures_PRJ', driver=driver)
        if garage_buffer is not None:
            garage_buffer.to_file(output_path, layer='Garage_Buffer_150m', driver=driver)
        if intersect_gdf is not None and not intersect_gdf.empty:
            intersect_gdf.to_file(output_path, layer='Garage_Structures_Intersect', driver=driver)
    except Exception as e:
        print('Error writing outputs:', e)

    # Also copy CSV if it exists
    if 'csv_path' in locals() and csv_path and os.path.exists(csv_path):
        out_csv = os.path.join(os.path.dirname(output_path), os.path.basename(csv_path))
        pd.read_csv(csv_path).to_csv(out_csv, index=False)
        print('Copied CSV to outputs:', out_csv)

    print('Done. Created layers:')
    print(' - GaragePoints_PRJ' if garage_proj is not None else '')
    print(' - Structures_PRJ' if structures_proj is not None else '')
    print(' - Garage_Buffer_150m' if garage_buffer is not None else '')
    print(' - Garage_Structures_Intersect' if intersect_gdf is not None and not intersect_gdf.empty else '')


if __name__ == '__main__':
    main()
