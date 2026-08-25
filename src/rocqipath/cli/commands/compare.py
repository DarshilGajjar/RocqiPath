"""Publication-quality WSI comparison command."""

from __future__ import annotations

import argparse
import os
from typing import List, Optional

from rocqipath.core.logging import configure_logging, logger
from rocqipath.utils.manifest import load_manifest as _load_manifest

VALID_REGIONS = ("center", "top_left", "top_right", "bottom_left", "bottom_right")


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Add publication-comparison arguments to a command parser."""
    parser.add_argument(
        "--manifest",
        help="Case manifest JSON written by the reconstruction workflow.",
    )
    parser.add_argument("--he", dest="he_path", help="Path to the H&E TIFF.")
    parser.add_argument("--gt-ihc", "--gt_ihc", dest="gt_ihc_path")
    parser.add_argument("--pred-ihc", "--pred_ihc", dest="pred_ihc_path")
    parser.add_argument("--output")
    parser.add_argument("--title-he", "--title_he", dest="title_he", default="H&E")
    parser.add_argument(
        "--title-gt",
        "--title_gt",
        dest="title_gt",
        default="Ground Truth IHC",
    )
    parser.add_argument(
        "--title-pred",
        "--title_pred",
        dest="title_pred",
        default="Predicted IHC",
    )
    parser.add_argument("--dpi", type=int, default=600)
    parser.add_argument(
        "--regions",
        nargs="+",
        default=list(VALID_REGIONS),
        choices=list(VALID_REGIONS),
    )
    parser.add_argument(
        "--zooms",
        nargs="+",
        default=["40x", "20x", "10x", "5x"],
        choices=["40x", "20x", "10x", "5x"],
    )
    parser.add_argument("--random-rois", "--random_rois", dest="random_rois", type=int, default=0)
    parser.add_argument("--roi-seed", "--roi_seed", dest="roi_seed", type=int, default=42)
    parser.add_argument("--scale-bars", "--scale_bars", dest="scale_bars", action="store_true")
    parser.add_argument(
        "--no-scale-bars",
        "--no_scale_bars",
        dest="scale_bars",
        action="store_false",
    )
    parser.add_argument("--mpp", type=float)
    parser.set_defaults(scale_bars=False)


def _resolve_inputs(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> tuple[str, str, str, str, str]:
    """Resolve manifest or explicit paths and the default output location."""
    if args.manifest:
        manifest = _load_manifest(args.manifest)
        case_id = manifest["case_id"]
        wsi_dir = manifest["wsi_dir"]
        he_path = manifest["stains"]["gt_he"]
        gt_ihc_path = manifest["stains"]["gt_ihc"]
        pred_ihc_path = manifest["stains"]["prediction_ihc"]
        save_path = args.output or os.path.join(wsi_dir, f"{case_id}_wsi_comparison.png")
        return he_path, gt_ihc_path, pred_ihc_path, save_path, wsi_dir

    missing = [
        option
        for option, value in (
            ("--he", args.he_path),
            ("--gt-ihc", args.gt_ihc_path),
            ("--pred-ihc", args.pred_ihc_path),
        )
        if not value
    ]
    if missing:
        parser.error(
            "When --manifest is not provided, these arguments are required: " + ", ".join(missing)
        )
    wsi_dir = os.path.dirname(os.path.abspath(args.he_path))
    save_path = args.output or os.path.join(wsi_dir, "wsi_comparison.png")
    return args.he_path, args.gt_ihc_path, args.pred_ihc_path, save_path, wsi_dir


def run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Generate all requested WSI comparison figures."""
    from rocqipath.visualization.comparison import _build_banner
    from rocqipath.visualization.comparison_workflow import visualize_side_by_side

    if args.random_rois < 0:
        parser.error("--random-rois must be >= 0.")
    if args.random_rois > 10:
        parser.error("--random-rois must be <= 10.")
    he_path, gt_path, pred_path, save_path, wsi_dir = _resolve_inputs(args, parser)
    zoom_map = {"40x": 512, "20x": 1000, "10x": 2000, "5x": 4000}
    zoom_sizes = [
        (zoom, zoom_map[zoom]) for zoom in ("40x", "20x", "10x", "5x") if zoom in args.zooms
    ]
    regions = [region for region in VALID_REGIONS if region in args.regions]
    configure_logging(
        save_dir=wsi_dir,
        file_level="DEBUG",
        log_filename="execution_log.log",
    )
    print(_build_banner("RocqiPath — Publication-Quality Visualizer", "WSI Visualization Module"))
    logger.info(f"Regions: {regions}")
    logger.info(f"Zoom levels: {[zoom[0] for zoom in zoom_sizes]}")
    logger.info(f"Output base: {save_path}")
    visualize_side_by_side(
        he_path=he_path,
        gt_ihc_path=gt_path,
        pred_ihc_path=pred_path,
        save_path=save_path,
        dpi=args.dpi,
        title_he=args.title_he,
        title_gt=args.title_gt,
        title_pred=args.title_pred,
        regions=regions,
        zoom_sizes=zoom_sizes,
        n_random_rois=args.random_rois,
        roi_seed=args.roi_seed,
        add_scale_bars=args.scale_bars,
        mpp=args.mpp,
    )
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Run the standalone comparison command used by the legacy module shim."""
    parser = argparse.ArgumentParser(
        prog="rocqipath compare",
        description="Publication-quality H&E / GT IHC / predicted-IHC comparison.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    configure_parser(parser)
    return run(parser.parse_args(argv), parser)
