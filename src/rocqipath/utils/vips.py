"""libvips helpers with intentionally function-local heavy imports.

NumPy and pyvips stay inside the functions so importing ``rocqipath.utils``
never pulls an optional imaging backend into a lightweight installation.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def vips_to_numpy_rgb(image: Any) -> Any:
    """Convert a pyvips image into an owned three-channel RGB uint8 array."""
    import numpy as np

    if image.hasalpha():
        image = image.flatten()
    if image.bands > 3:
        image = image[:3]
    return np.ndarray(
        buffer=image.write_to_memory(),
        dtype=np.uint8,
        shape=[image.height, image.width, image.bands],
    )[:, :, :3]


def vips_properties(image: Any) -> dict[str, Any]:
    """Return readable libvips metadata without failing on lazy fields."""
    properties: dict[str, Any] = {}
    for key in image.get_fields():
        try:
            properties[key] = image.get(key)
        except Exception:
            continue
    return properties


def open_vips_pyramid_level(path: Path, level: int) -> Any:
    """Open a pyramid level using the first syntax supported by the slide."""
    import pyvips

    last_error: Exception | None = None
    for parameter in (f"[level={level}]", f"[page={level}]"):
        try:
            return pyvips.Image.new_from_file(
                f"{path}{parameter}",
                access=pyvips.enums.Access.SEQUENTIAL,
            )
        except pyvips.Error as exc:
            last_error = exc
    if level == 0:
        return pyvips.Image.new_from_file(str(path), access="sequential")
    raise last_error or RuntimeError(f"Pyramid level {level} is unavailable")


def resample_region(
    region: Any,
    *,
    source_magnification: float,
    target_magnification: float,
) -> Any:
    """Resample a level-0 region to an exact physical magnification."""
    if target_magnification > source_magnification:
        raise ValueError(
            f"target_magnification ({target_magnification:g}x) exceeds "
            f"source_magnification ({source_magnification:g}x)"
        )
    scale = target_magnification / source_magnification
    return region if math.isclose(scale, 1.0, rel_tol=1e-6) else region.resize(scale)


def rgb_ome_xml(
    width: int,
    height: int,
    name: str,
    mpp_x: float | None,
    mpp_y: float | None,
) -> str:
    """Build minimal valid OME-XML for one interleaved RGB image."""
    namespace = "http://www.openmicroscopy.org/Schemas/OME/2016-06"
    ET.register_namespace("", namespace)
    ome = ET.Element(f"{{{namespace}}}OME")
    image = ET.SubElement(ome, f"{{{namespace}}}Image", ID="Image:0", Name=name)
    attributes = {
        "ID": "Pixels:0",
        "DimensionOrder": "XYCZT",
        "Type": "uint8",
        "SizeX": str(width),
        "SizeY": str(height),
        "SizeC": "3",
        "SizeZ": "1",
        "SizeT": "1",
        "Interleaved": "true",
    }
    if mpp_x and mpp_x > 0:
        attributes.update(PhysicalSizeX=str(mpp_x), PhysicalSizeXUnit="µm")
    if mpp_y and mpp_y > 0:
        attributes.update(PhysicalSizeY=str(mpp_y), PhysicalSizeYUnit="µm")
    pixels = ET.SubElement(image, f"{{{namespace}}}Pixels", attributes)
    ET.SubElement(
        pixels,
        f"{{{namespace}}}Channel",
        ID="Channel:0:0",
        Name="RGB",
        SamplesPerPixel="3",
    )
    ET.SubElement(pixels, f"{{{namespace}}}TiffData")
    return ET.tostring(ome, encoding="unicode", xml_declaration=True)


__all__ = [
    "open_vips_pyramid_level",
    "resample_region",
    "rgb_ome_xml",
    "vips_properties",
    "vips_to_numpy_rgb",
]
