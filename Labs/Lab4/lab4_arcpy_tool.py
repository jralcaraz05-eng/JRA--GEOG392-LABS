"""
lab4_arcpy_tool.py

ArcPy script-tool friendly script for Lab 04.

Parameters (script-tool order / GetParameterAsText):
 0 - Input GDB folder (workspace) or folder containing input GDB (string)
 1 - CSV path or table name inside the GDB (optional) (string)
 2 - Output FileGDB full path (optional). If empty, a GDB named 'Lab4_Output.gdb' will be created next to the input GDB.
 3 - Buffer distance in meters (optional, default 150)
 4 - Force create sample data (Boolean: 'true'/'false')

This script will:
 - locate the garages/garagepoints feature class or create it from CSV when needed
 - locate the Structures feature class
 - create an output FileGDB if missing
 - project both inputs to a metric CRS (EPSG:3857) to safely buffer in meters
 - buffer garages by the given distance (meters)
 - intersect the buffer with Structures
 - write 4 outputs into the output GDB:
     GaragePoints_PRJ, Structures_PRJ, Garage_Buffer_<dist>m, Garage_Structures_Intersect

This file is safe to add as a script tool in ArcGIS Pro toolbox (set parameter types as: Workspace, String, Workspace, Double, Boolean).

"""
from __future__ import print_function
import arcpy
import os
import sys
import re


def _find_candidate_featureclass(workspace, names):
    arcpy.env.workspace = workspace
    for n in names:
        if arcpy.Exists(os.path.join(workspace, n)):
            return n
    # try case-insensitive match
    fcs = arcpy.ListFeatureClasses()
    if fcs:
        for n in names:
            for f in fcs:
                if f.lower() == n.lower():
                    return f
    return None


def _detect_xy_fields(table):
    fields = arcpy.ListFields(table)
    names = [f.name for f in fields]
    # look for common names
    x_candidates = [n for n in names if re.search(r"(^x$|lon|long|longitude)", n, re.I)]
    y_candidates = [n for n in names if re.search(r"(^y$|lat|latitude)", n, re.I)]
    # fallback: numeric fields
    if not x_candidates or not y_candidates:
        num_fields = [f.name for f in fields if f.type in ('Double','Single','Integer','SmallInteger')]
        if len(num_fields) >= 2:
            return num_fields[0], num_fields[1]
        return None, None
    return x_candidates[0], y_candidates[0]


def create_output_gdb(out_gdb_path):
    if arcpy.Exists(out_gdb_path):
        arcpy.AddMessage(f"Output GDB already exists: {out_gdb_path}")
        return out_gdb_path
    folder = os.path.dirname(out_gdb_path)
    name = os.path.basename(out_gdb_path)
    # name must be without .gdb extension for CreateFileGDB
    name_no_ext = name
    if name.lower().endswith('.gdb'):
        name_no_ext = os.path.splitext(name)[0]
    arcpy.management.CreateFileGDB(folder, name_no_ext)
    arcpy.AddMessage(f"Created FileGDB: {out_gdb_path}")
    return out_gdb_path


def project_feature(input_fc, out_fc, target_sr):
    if arcpy.Exists(out_fc):
        arcpy.AddMessage(f"Projected feature already exists: {out_fc}")
        return out_fc
    arcpy.management.Project(input_fc, out_fc, target_sr)
    arcpy.AddMessage(f"Projected {input_fc} -> {out_fc}")
    return out_fc


def main(in_gdb, csv_or_table, out_gdb, buffer_meters, force_sample):
    try:
        # Normalize
        in_gdb = in_gdb.strip()
        csv_or_table = csv_or_table.strip() if csv_or_table else ''
        out_gdb = out_gdb.strip() if out_gdb else ''
        buffer_meters = float(buffer_meters) if buffer_meters not in (None, '', 'None') else 150.0
        force_sample = str(force_sample).lower() in ('true','1','yes')

        # Resolve input GDB path
        if not arcpy.Exists(in_gdb):
            raise ValueError(f"Input geodatabase does not exist: {in_gdb}")

        arcpy.env.workspace = in_gdb

        # Identify garages / points
        garage_fc = _find_candidate_featureclass(in_gdb, ['GaragePoints', 'garagepoints', 'garages', 'Garages'])
        if garage_fc:
            arcpy.AddMessage(f"Found garages featureclass: {garage_fc}")
            garage_fc_path = os.path.join(in_gdb, garage_fc)
        else:
            # try csv path
            if csv_or_table and os.path.exists(csv_or_table):
                # attempt to convert CSV to points
                x_field, y_field = _detect_xy_fields(csv_or_table)
                if not x_field or not y_field:
                    raise ValueError('Unable to detect X/Y fields in CSV. Please provide CSV with X/Y or Lon/Lat fields.')
                garage_fc_path = os.path.join(in_gdb, 'GaragePoints')
                arcpy.management.XYTableToPoint(csv_or_table, garage_fc_path, x_field, y_field)
                arcpy.AddMessage(f"Converted CSV -> {garage_fc_path} using X={x_field}, Y={y_field}")
            else:
                raise ValueError('Could not find garage point feature class in GDB and no valid CSV provided.')

        # Identify Structures
        structures_fc = _find_candidate_featureclass(in_gdb, ['Structures', 'structures'])
        if not structures_fc:
            raise ValueError('Could not find Structures feature class in input GDB')
        structures_fc_path = os.path.join(in_gdb, structures_fc)
        arcpy.AddMessage(f"Found structures featureclass: {structures_fc}")

        # prepare output GDB
        if not out_gdb:
            # create in same folder as input GDB
            in_folder = os.path.dirname(in_gdb)
            out_gdb = os.path.join(in_folder, 'Lab4_Output.gdb')

        create_output_gdb(out_gdb)

        # Project to metric CRS for buffering
        target_sr = arcpy.SpatialReference(3857)  # Web Mercator (meters)

        garage_prj = os.path.join(out_gdb, 'GaragePoints_PRJ')
        structures_prj = os.path.join(out_gdb, 'Structures_PRJ')

        project_feature(garage_fc_path, garage_prj, target_sr)
        project_feature(structures_fc_path, structures_prj, target_sr)

        # Buffer
        buffer_name = f"Garage_Buffer_{int(buffer_meters)}m"
        buffer_fc = os.path.join(out_gdb, buffer_name)
        if not arcpy.Exists(buffer_fc):
            arcpy.analysis.Buffer(garage_prj, buffer_fc, f"{buffer_meters} Meters", line_side='FULL', line_end_type='ROUND', dissolve_option='NONE')
            arcpy.AddMessage(f"Buffered {garage_prj} -> {buffer_fc} by {buffer_meters} meters")
        else:
            arcpy.AddMessage(f"Buffer already exists: {buffer_fc}")

        # Intersect
        intersect_fc = os.path.join(out_gdb, 'Garage_Structures_Intersect')
        if not arcpy.Exists(intersect_fc):
            arcpy.analysis.Intersect([buffer_fc, structures_prj], intersect_fc, join_attributes='ALL')
            arcpy.AddMessage(f"Intersected {buffer_fc} and {structures_prj} -> {intersect_fc}")
        else:
            arcpy.AddMessage(f"Intersection already exists: {intersect_fc}")

        arcpy.AddMessage("Lab4 processing completed. Outputs written to: {}".format(out_gdb))
        arcpy.AddMessage("Outputs: GaragePoints_PRJ, Structures_PRJ, {} , Garage_Structures_Intersect".format(buffer_name))

        return 0

    except Exception as e:
        arcpy.AddError(str(e))
        arcpy.AddMessage('Traceback available in Python window or logs')
        return 1


if __name__ == '__main__':
    # Try to use ArcGIS parameter mechanism first (script tool)
    try:
        in_gdb = arcpy.GetParameterAsText(0)
        csv_or_table = arcpy.GetParameterAsText(1)
        out_gdb = arcpy.GetParameterAsText(2)
        buffer_meters = arcpy.GetParameterAsText(3)
        force_sample = arcpy.GetParameterAsText(4)
        sys.exit(main(in_gdb, csv_or_table, out_gdb, buffer_meters or 150, force_sample or 'false'))
    except Exception:
        # Fallback: allow running as `python lab4_arcpy_tool.py <in_gdb> <csv_or_table> <out_gdb> <buffer_meters>`
        argv = sys.argv[1:]
        in_gdb = argv[0] if len(argv) > 0 else ''
        csv_or_table = argv[1] if len(argv) > 1 else ''
        out_gdb = argv[2] if len(argv) > 2 else ''
        buffer_meters = argv[3] if len(argv) > 3 else 150
        force_sample = argv[4] if len(argv) > 4 else 'false'
        sys.exit(main(in_gdb, csv_or_table, out_gdb, buffer_meters, force_sample))
