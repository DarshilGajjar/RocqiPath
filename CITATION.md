# Citing RocqiPath

## RocqiPath itself

Cite the specific release you used, including its version number and the
repository URL:

> Gajjar, D. RocqiPath: whole-slide image processing for computational
> pathology (version X.Y.Z) [Computer software].
> https://github.com/DarshilGajjar/RocqiPath

GitHub's "Cite this repository" button reads [CITATION.cff](CITATION.cff) and
produces BibTeX and APA forms of the same entry.

Reproducibility improves considerably if you also report the recipe hash and
the selection name behind each result. For example:

> Patches were extracted at 20x under RocqiPath recipe `4f2a9c1e77b0` and
> restricted to selection `strict` (`tissue_fraction >= 0.6`).

## Underlying components

Cite the components that were **materially used** in the analysis you report.
You do not need to cite every utility dependency of every project.

### VALIS — for WSI registration or alignment

> Gatenbee, C. D., Baker, A.-M., Prabhakaran, S., Robertson-Tessi, M.,
> Graham, T. A., & Anderson, A. R. A. (2023). Virtual alignment of pathology
> image series for multi-gigapixel whole slide images. *Nature Communications*,
> 14, 4062. https://doi.org/10.1038/s41467-023-40218-9

### TIAToolbox — for TIAToolbox-based stain normalization or tissue-image analysis

> Pocock, J., Graham, S., Vu, Q. D., et al. (2022). TIAToolbox as an end-to-end
> library for advanced tissue image analytics. *Communications Medicine*, 2,
> 120. https://doi.org/10.1038/s43856-022-00186-5

### NumPy — when numerical array processing is substantive to the analysis

> Harris, C. R., Millman, K. J., van der Walt, S. J., et al. (2020). Array
> programming with NumPy. *Nature*, 585, 357–362.
> https://doi.org/10.1038/s41586-020-2649-2

### libvips / pyvips — for libvips-backed image I/O, resizing, or pyramidal TIFF generation

> Cupitt, J., Martinez, K., Fuller, L., & Wolthuizen, K. A. (2025). The libvips
> image processing library. *Proceedings of Electronic Imaging 2025*,
> Burlingame.

See the
[official libvips citation guidance](https://github.com/libvips/libvips/blob/master/doc/cite.md)
for the current preferred form.

### OpenSlide — for reading vendor whole-slide formats

> Goode, A., Gilbert, B., Harkes, J., Jukic, D., & Satyanarayanan, M. (2013).
> OpenSlide: A vendor-neutral software foundation for digital pathology.
> *Journal of Pathology Informatics*, 4, 27.
> https://doi.org/10.4103/2153-3539.119005

## Which of these applies to me?

| If your analysis used… | Cite |
| --- | --- |
| Any RocqiPath output | RocqiPath |
| `alignment_method = "valis"` | VALIS |
| `alignment_method = "orb"` | RocqiPath only (ORB is implemented in RocqiPath over OpenCV) |
| Stain normalisation | TIAToolbox |
| Aligned-WSI export or pyramidal TIFF output | libvips |
| Any vendor slide format (`.svs`, `.ndpi`, `.mrxs`, …) | OpenSlide |
| Substantive numerical analysis of extracted arrays | NumPy |
