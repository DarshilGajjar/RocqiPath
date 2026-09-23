# Building blocks

The workflows are built from these. Use them when you need finer control
than a workflow gives.

## Tissue masks (`rocqipath.tissue`)

::: rocqipath.tissue.masks
    options:
      members: [tissue_mask, tissue_fraction, is_tissue]

## Extraction (`rocqipath.extraction`)

::: rocqipath.extraction.regions.extract_tissue_regions

::: rocqipath.extraction.reversible.ReversiblePatchExtractor

## Alignment (`rocqipath.alignment`)

::: rocqipath.alignment.registrar.WSIRegistrar
    options:
      members: [__init__, register_slides, save_aligned_wsi, generate_grid_map, close]

## Stain normalization (`rocqipath.stain`)

::: rocqipath.stain.normalizers.get_normalizer

::: rocqipath.stain.normalizers.ReinhardNormalizer

::: rocqipath.stain.normalizers.MacenkoNormalizer

::: rocqipath.stain.normalizers.VahadaneNormalizer

## Cell counting (`rocqipath.counting`)

::: rocqipath.counting.counter.PositiveCellCounter
    options:
      members: [count_slide, count_slide_pair, count_batch]

## Figures (`rocqipath.viz`)

::: rocqipath.viz.grids.plot_selector_map

::: rocqipath.viz.pairs.view_pairs

::: rocqipath.viz.thumbnails.export_wsi_thumbnails
