"""
Builds the release zips: one with every Maya version, and one per Maya version.

    python package.py 2.1

writes dist/DRPForMaya-2.1.zip and dist/DRPForMaya-2.1-Maya<version>.zip
"""
import argparse
import pathlib
import zipfile

PLUGIN_NAME = "DRPForMaya"
SKIPPED_DIRS = {"__pycache__"}
SKIPPED_SUFFIXES = {".pyc", ".old"}


def module_files(module_dir, version=None):
    """Files of the module folder, with only one version's plug-in when a version is given."""
    for path in sorted(module_dir.rglob("*")):
        relative = path.relative_to(module_dir)
        if not path.is_file() or SKIPPED_DIRS & set(relative.parts) or path.suffix in SKIPPED_SUFFIXES:
            continue
        if version and relative.parts[0] == "plug-ins" and relative.parts[1] != version:
            continue
        yield path


def build_zip(root, zip_path, version=None):
    files = [root / "installer.py", root / "README.md", *module_files(root / "module", version)]
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, path.relative_to(root).as_posix())
    with zipfile.ZipFile(zip_path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError(f"{zip_path.name} is damaged")
        plugins = sorted(name for name in archive.namelist() if name.endswith(f"{PLUGIN_NAME}.mll"))
    print(f"{zip_path.name}: {zip_path.stat().st_size / 1_000_000:.1f} MB, {', '.join(plugins)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("release", help="release number used in the zip names, like 2.1")
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent,
                        help="project folder holding installer.py, README.md and module")
    parser.add_argument("--output", type=pathlib.Path, help="where the zips are written (default: <root>/dist)")
    args = parser.parse_args()

    output = args.output or args.root / "dist"
    output.mkdir(parents=True, exist_ok=True)
    versions = sorted(path.parent.name for path in (args.root / "module" / "plug-ins").glob(f"*/{PLUGIN_NAME}.mll"))
    if not versions:
        raise SystemExit("No built plug-in in module/plug-ins: run build.bat first")

    build_zip(args.root, output / f"{PLUGIN_NAME}-{args.release}.zip")
    for version in versions:
        build_zip(args.root, output / f"{PLUGIN_NAME}-{args.release}-Maya{version}.zip", version)


if __name__ == "__main__":
    main()
