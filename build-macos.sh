#!/usr/bin/env bash
set -euo pipefail

force_build=false
create_dmg=false
create_zip=false

while (($#)); do
  case "$1" in
    --force|-f)
      force_build=true
      ;;
    --dmg)
      create_dmg=true
      ;;
    --zip)
      create_zip=true
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: ./build-macos.sh [--force] [--dmg] [--zip]" >&2
      exit 2
      ;;
  esac
  shift
done

if ! command -v pyside6-deploy >/dev/null 2>&1; then
  echo "pyside6-deploy was not found on PATH. Activate your project environment first." >&2
  exit 1
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

spec_path="$script_dir/pysidedeploy.spec"
spec_text="$(cat "$spec_path")"
build_dir="$script_dir/build"
generated_spec="$build_dir/pysidedeploy.generated.spec"
mkdir -p "$build_dir"
cp "$spec_path" "$generated_spec"

restore_spec() {
  printf "%s" "$spec_text" > "$spec_path"
}
trap restore_spec EXIT

deploy_args=(qtTeslaCam.py --config-file "$generated_spec")
if [[ "$force_build" == true ]]; then
  deploy_args+=(--force)
fi

echo "Running pyside6-deploy for TeslaCamViewer..."
pyside6-deploy "${deploy_args[@]}"

app_path="$(find "$script_dir/dist" "$script_dir/deployment" -name "*.app" -type d -print -quit 2>/dev/null || true)"
if [[ -z "$app_path" ]]; then
  echo "pyside6-deploy finished, but no .app bundle was found under dist/ or deployment/." >&2
  exit 1
fi

resources_dir="$app_path/Contents/Resources"
notices_dir="$resources_dir/notices"
mkdir -p "$notices_dir"
cp LICENSE THIRD_PARTY_NOTICES.md "$resources_dir/"
cp docs/PYSIDE6-LICENSING.md "$notices_dir/"
cp licenses/* "$notices_dir/"

version="$(python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
machine_arch="$(uname -m)"
case "$machine_arch" in
  arm64|aarch64)
    package_arch="arm64"
    ;;
  x86_64|amd64)
    package_arch="x64"
    ;;
  *)
    package_arch="$machine_arch"
    ;;
esac
installer_dir="$script_dir/dist/installer"
mkdir -p "$installer_dir"

echo "Build complete. App bundle: $app_path"

if [[ "$create_dmg" == true ]]; then
  if ! command -v hdiutil >/dev/null 2>&1; then
    echo "hdiutil was not found; creating a zip package instead." >&2
    create_zip=true
  else
    dmg_root="$build_dir/dmg-root"
    dmg_path="$installer_dir/TeslaCamViewer-$version-macos-$package_arch.dmg"
    rm -rf "$dmg_root" "$dmg_path"
    mkdir -p "$dmg_root"
    cp -R "$app_path" "$dmg_root/"
    hdiutil create -volname "TeslaCamViewer" -srcfolder "$dmg_root" -ov -format UDZO "$dmg_path"
    echo "DMG complete. Package file: $dmg_path"
  fi
fi

if [[ "$create_zip" == true ]]; then
  zip_path="$installer_dir/TeslaCamViewer-$version-macos-$package_arch.zip"
  rm -f "$zip_path"
  ditto -c -k --sequesterRsrc --keepParent "$app_path" "$zip_path"
  echo "Zip complete. Package file: $zip_path"
fi
