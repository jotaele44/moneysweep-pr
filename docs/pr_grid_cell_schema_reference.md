# PR Grid Cell Schema Reference

Required fields:

```text
Cell_ID
Row_Index
Column_Index
Pixel_X_Min
Pixel_Y_Min
Pixel_X_Max
Pixel_Y_Max
Centroid_X
Centroid_Y
Dark_Pixel_Count
Total_Pixel_Count
Land_Pixel_Ratio
Classification
```

Expected ranges:

- Row_Index: 0-255
- Column_Index: 0-383
- Classification: Water_or_Empty, Gridline_Dominant, Coastline_or_Land
