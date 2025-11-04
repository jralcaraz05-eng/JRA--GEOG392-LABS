
# Author: Justin Alcaraz (Texas A&M University)
# Course: GEOG 390 / Lab 5 — Buffer + Clip around a chosen building

import arcpy
import os
import sys

arcpy.env.overwriteOutput = True  # Allow overwriting outputs for easier testing

def ask(prompt):
    """Tiny helper so I don't accept empty strings from the console."""
    v = input(prompt).strip()
    if not v:
        print("Error: a value is required for:", prompt)
        sys.exit(1)
    return v

def assert_exists(path, label):
    """Fail early if a required path is missing."""
    # arcpy.Exists works for gdb/feature classes; os.path.exists for files/folders.
    ok = arcpy.Exists(path) or os.path.exists(path)
    if not ok:
        print(f"error: {label} not found -> {path}")
        sys.exit(2)

def main():
    print("== GEOG 390 · Lab 5 console tool ==\n")

    # --- Inputs 4 rubric  ---
    GDB_Folder         = ask("GDB Folder (folder that will contain Lab5.gdb): ")
    GDB_Name           = ask("GDB Name (e.g., Lab5.gdb): ")
    Garage_CSV_File    = ask("Garages CSV file (full path): ")
    Garage_Layer_Name  = ask("Garage layer name (e.g., garages): ")
    Campus_GDB         = ask("Campus GDB (full path to Campus.gdb): ")
    Selected_Name      = ask("Selected Building/Garage Name (matches 'BldgName' in Structures): ")
    Buffer_Radius      = ask("Buffer radius with units (e.g., 150 Meters): ")

    # Normalize paths once.
    GDB_Folder   = os.path.abspath(GDB_Folder)
    GDB_Full     = os.path.join(GDB_Folder, GDB_Name)
    structures_fc = os.path.join(Campus_GDB, "Structures")

    # --- Basic path checks so I fail with a message ---
    assert_exists(GDB_Folder, "GDB folder")
    assert_exists(Campus_GDB, "Campus.gdb")
    # CSV is optional for the lab logic, but I check and warn if missing.
    csv_present = os.path.exists(Garage_CSV_File)

    # --- 1) Create the GDB if needed ---
    if not arcpy.Exists(GDB_Full):
        arcpy.management.CreateFileGDB(GDB_Folder, GDB_Name)

    # --- 2) Import garages.csv as points (best-effort X/Y detection) ---
    if csv_present:
        sr = arcpy.SpatialReference(4326)  # reasonable default for CSVs
        candidate_xy = [("X","Y"), ("Lon","Lat"), ("Longitude","Latitude"), ("long","lat")]
        xy_layer = None
        used_x = used_y = None
        for x_field, y_field in candidate_xy:
            try:
                xy_layer = arcpy.management.MakeXYEventLayer(
                    in_table=Garage_CSV_File,
                    in_x_field=x_field,
                    in_y_field=y_field,
                    out_layer=Garage_Layer_Name + "_xy",
                    spatial_reference=sr
                )
                used_x, used_y = x_field, y_field
                break
            except Exception:
                xy_layer = None  

        if xy_layer:
            arcpy.conversion.FeatureClassToGeodatabase(
                Input_Features=xy_layer,
                Output_Geodatabase=GDB_Full
            )
            print(f"CSV imported using X='{used_x}', Y='{used_y}'")
        else:
            print("Note: CSV present but X/Y headers not detected (skipping import).")
    else:
        print("Note: CSV not found; skipping garages import. (Buffer/Clip still runs.)")

    # --- 3) Verify Structures and BldgName ---
    assert_exists(structures_fc, "Structures feature class")
    fields = [f.name for f in arcpy.ListFields(structures_fc)]
    if "BldgName" not in fields:
        print("error: field 'BldgName' not found in Structures. Check your data schema.")
        sys.exit(2)

    # Build a safe where clause
    safe_name = Selected_Name.replace("'", "''")
    where_clause = f"BldgName = '{safe_name}'"

    # Existence check for the selected name
    found = False
    with arcpy.da.SearchCursor(structures_fc, ["BldgName"], where_clause) as rows:
        for row in rows:
            if row[0] == Selected_Name:
                found = True
                break

    if not found:
        print(f"error: No structure found with BldgName = {Selected_Name}")
        # Small assist: show a few sample names to help me pick the exact text.
        try:
            seen = set()
            with arcpy.da.SearchCursor(structures_fc, ["BldgName"]) as rows:
                for i, (nm,) in enumerate(rows):
                    if nm not in seen:
                        print("hint:", nm)
                        seen.add(nm)
                    if len(seen) >= 10:  # don't spam the console
                        break
        except Exception:
            pass
        sys.exit(3)

    # --- 4) Select → Buffer → Clip ---
    sel_fc  = os.path.join(GDB_Full, "structure_selected")
    buff_fc = os.path.join(GDB_Full, "structure_buffer")
    clip_fc = os.path.join(GDB_Full, f"clip_{Selected_Name.replace(' ', '_')}")

    # Select the chosen building/garage
    arcpy.analysis.Select(in_features=structures_fc, out_feature_class=sel_fc, where_clause=where_clause)

    # Simple buffer using the unit string I provided (e.g., '150 Meters')
    arcpy.analysis.Buffer(in_features=sel_fc, out_feature_class=buff_fc,
                          buffer_distance_or_field=Buffer_Radius, dissolve_option="ALL")

    # Clip all Structures to the buffer so I can see what's inside
    arcpy.analysis.Clip(in_features=structures_fc, clip_features=buff_fc, out_feature_class=clip_fc)

    print("success")
    print("Outputs GDB:", GDB_Full)

if __name__ == "__main__":
    main()
