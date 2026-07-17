# -*- coding: utf-8 -*-
"""
roqcipath.visualization.visualization
=======================================
Lightweight grid-map and patch-pair visualisation helpers, used by the
interactive CLI and :mod:`roqcipath.api` for quick visual QC — as opposed
to :mod:`roqcipath.visualization.wsi_compare`, which produces
publication-quality figures.

Both functions in this module display interactively via
:func:`matplotlib.pyplot.show` (in addition to, for
:func:`plot_selector_map`, optionally saving a copy to disk) and are
intended for exploratory/notebook use rather than headless batch
pipelines.
"""

import os
import json
import random
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
import matplotlib.patches as patches

def plot_selector_map(thumb_img, valid_ids, rows, cols, output_path=None):
    """Overlay a coloured grid on a slide thumbnail, highlighting tissue-containing cells.

    Draws a ``rows`` x ``cols`` grid across ``thumb_img`` and highlights,
    with a translucent green rectangle and its flat index number, every
    grid cell whose index appears in ``valid_ids`` (e.g. cells identified
    as containing tissue by an upstream detection step).

    Parameters
    ----------
    thumb_img : PIL.Image.Image
        The slide thumbnail to overlay the grid on. Must expose a
        ``.size`` attribute (``(width, height)``), as any
        :class:`PIL.Image.Image` does.
    valid_ids : Container of int
        Flat grid-cell indices (row-major: ``index = row * cols + col``)
        to highlight. Typically the set of grid cells found to contain
        tissue.
    rows : int
        Number of grid rows.
    cols : int
        Number of grid columns.
    output_path : str, optional
        If given, the figure is also saved to this path via
        :func:`matplotlib.pyplot.savefig` before being shown.

    Returns
    -------
    None
        Displays the figure via :func:`matplotlib.pyplot.show` (non-blocking,
        with a 1-second pause so the window has time to render before
        the function returns) and, if ``output_path`` is given, saves it
        to disk as a side effect. Nothing is returned.

    Notes
    -----
    Each grid cell's pixel span is computed as
    ``thumb_width / cols`` x ``thumb_height / rows`` — cells are assumed
    uniform in size, so this expects ``rows``/``cols`` to evenly (or
    near-evenly) divide the thumbnail's dimensions, matching whatever
    grid convention was used to generate ``valid_ids`` in the first
    place.
    """
    fig, ax = plt.subplots(figsize=(10, 10), dpi=150)
    ax.imshow(thumb_img)
    ax.set_title("Grid Map - Green boxes have tissue content")
    
    t_w, t_h = thumb_img.size
    sx = t_w / cols
    sy = t_h / rows
    
    count = 0
    for r in range(rows):
        for c in range(cols):
            if count in valid_ids:
                tx, ty = c * sx, r * sy
                rect = patches.Rectangle((tx, ty), sx, sy, lw=1, edgecolor='#00FF00', facecolor='green', alpha=0.2)
                ax.add_patch(rect)
                ax.text(tx+5, ty+20, f"#{count}", color='red', fontsize=8, weight='bold')
            count += 1
            
    plt.axis('off')
    if output_path:
        plt.savefig(output_path)
        print(f"[INFO] Map saved to {output_path}")
    
    plt.show(block=False)
    plt.pause(1)

def view_pairs(grid_folder, num_to_show='all'):
    """Display H&E and IHC patch pairs side by side for visual QC.

    Supports the flat RocqiPath case layout through its metadata JSON or
    ``*_reference.png``/``*_moving.png`` names. Legacy ``HnE/`` and ``IHC/``
    subfolders remain readable for backward compatibility.

    Parameters
    ----------
    grid_folder : str
        Flat per-case output directory (or a legacy paired-patch directory).
    num_to_show : int or 'all', optional
        How many pairs to display. When ``'all'`` (the default), every
        pair found is shown, in filename-sorted order. When an integer,
        that many pairs are chosen via random sampling (without
        replacement) from all available pairs, then displayed in
        ascending index order; if fewer pairs exist than requested, all
        available pairs are shown instead.

    Returns
    -------
    None
        Opens one matplotlib figure per pair (each a 1x2 subplot: H&E on
        the left, IHC on the right), blocking on
        :func:`matplotlib.pyplot.show` for each in turn. Returns
        immediately (printing a warning, no figures shown) if no pairs exist.

    Notes
    -----
    Individual pairs that fail to load (e.g. a corrupt or missing IHC
    counterpart) are caught per-pair — the exception is printed and the
    loop continues to the next pair rather than aborting the whole
    viewing session.
    """
    root = os.path.abspath(grid_folder)
    pairs = []

    # New flat layout: prefer explicit metadata, which supports arbitrary
    # reference/target channel names.
    manifests = sorted(
        os.path.join(root, name) for name in os.listdir(root)
        if name.endswith("_metadata.json")
    ) if os.path.isdir(root) else []
    for manifest in manifests:
        try:
            with open(manifest, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            for patch in payload.get("patches", []):
                paths = [value for key, value in patch.items() if key.endswith("_path")]
                if len(paths) >= 2:
                    pairs.append((paths[0], paths[1], str(patch.get("id", ""))))
        except (OSError, ValueError, TypeError):
            continue

    if not pairs and os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            if name.endswith("_reference.png"):
                moving = name.removesuffix("_reference.png") + "_moving.png"
                moving_path = os.path.join(root, moving)
                if os.path.isfile(moving_path):
                    pairs.append((os.path.join(root, name), moving_path, name))

    # Backward-compatible legacy HnE/IHC subfolders.
    if not pairs:
        dir_hne = os.path.join(root, "HnE")
        dir_ihc = os.path.join(root, "IHC")
        if os.path.isdir(dir_hne):
            for name in sorted(f for f in os.listdir(dir_hne) if f.endswith(".png")):
                moving = os.path.join(dir_ihc, name)
                if os.path.isfile(moving):
                    pairs.append((os.path.join(dir_hne, name), moving, name))

    total = len(pairs)
    
    if total == 0:
        print("[WARN] No images found to visualize.")
        return

    if num_to_show == 'all':
        indices = range(total)
    else:
        # Ensure we don't sample more than available
        indices = sorted(random.sample(range(total), min(int(num_to_show), total)))
        
    print(f"[VISUALIZING] Showing {len(indices)} pairs from {os.path.basename(grid_folder)}...")

    for idx in indices:
        path_a, path_b, f_name = pairs[idx]

        try:
            img_a = mpimg.imread(path_a)
            img_b = mpimg.imread(path_b)
            
            fig, axes = plt.subplots(1, 2, figsize=(12, 6))
            axes[0].imshow(img_a)
            axes[0].set_title(f"H&E (Ref): {f_name}")
            axes[0].axis('off')
            
            axes[1].imshow(img_b)
            axes[1].set_title(f"IHC (Target): {f_name}")
            axes[1].axis('off')
            
            plt.tight_layout()
            plt.show()
        except Exception as e:
            print(f"Error showing pair {f_name}: {e}")
