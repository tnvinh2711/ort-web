from __future__ import annotations

import csv
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import yaml


def _safe_load(path: Path) -> Any:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in {".yml", ".yaml"}:
        return yaml.safe_load(text)
    return None


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _parse_package_id(package_id: str) -> tuple[str, str]:
    """Parse ORT package ID into (name, version).

    ORT format:  Type:namespace:name:version  (e.g. Maven:com.example:log4j-core:2.14.1)
    NPM format:  NPM::lodash:4.17.21  or  @scope/pkg@1.2.3
    """
    raw = str(package_id or "").strip()
    if not raw:
        return "", ""

    # ORT colon-separated format: Type:namespace:name:version
    parts = raw.split(":")
    if len(parts) >= 4:
        # parts[0]=Type, parts[1]=namespace, parts[2]=name, parts[3]=version
        namespace = parts[1].strip()
        name = parts[2].strip()
        version = parts[3].strip()
        if name:
            # NPM scoped packages: @scope/name (e.g. NPM:@babel:core → @babel/core)
            if namespace.startswith("@"):
                return f"{namespace}/{name}", version
            return name, version

    # NPM @scope/pkg@version or plain pkg@version
    if "@" in raw:
        base, version = raw.rsplit("@", 1)
        if "?" in version:
            version = version.split("?", 1)[0]
        name = base.rsplit("/", 1)[-1] if "/" in base else base
        return name.strip(), version.strip()

    # Fallback: last path segment
    if "/" in raw:
        return raw.rsplit("/", 1)[-1].strip(), ""

    # 3-part colon format: Type:namespace:name
    if len(parts) == 3:
        return parts[2].strip(), ""

    return raw, ""


def _extract_license(pkg: dict[str, Any]) -> str:
    declared_processed = pkg.get("declared_licenses_processed")
    if isinstance(declared_processed, dict):
        spdx = declared_processed.get("spdx_expression")
        if spdx:
            return str(spdx)

    for key in ("concluded_license", "concludedLicense"):
        if pkg.get(key):
            return str(pkg.get(key))

    for key in ("declared_licenses", "declaredLicenses"):
        value = pkg.get(key)
        if isinstance(value, list) and value:
            return ", ".join(str(item) for item in value if item)

    return ""


def _extract_homepage(pkg: dict[str, Any]) -> str:
    for key in ("homepage_url", "homepageUrl", "homepage", "url"):
        value = pkg.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_packages(analyzer_data: Any) -> dict[tuple[str, str], dict[str, str]]:
    packages: dict[tuple[str, str], dict[str, str]] = {}

    for node in _walk(analyzer_data):
        package_id = node.get("id")
        if not package_id:
            continue

        if not any(k in node for k in ("declared_licenses", "declared_licenses_processed", "homepage_url", "homepageUrl")):
            continue

        component, version = _parse_package_id(str(package_id))
        if not component:
            continue

        key = (component, version)
        existing = packages.get(key)
        license_text = _extract_license(node)
        homepage = _extract_homepage(node)

        if not existing:
            packages[key] = {
                "Component": component,
                "Version": version,
                "License": license_text,
                "Home Page": homepage,
                "Usage": "",
            }
            continue

        if not existing["License"] and license_text:
            existing["License"] = license_text
        if not existing["Home Page"] and homepage:
            existing["Home Page"] = homepage

    return packages


def _tag_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower()


def _extract_packages_from_xml(output_dir: Path) -> dict[tuple[str, str], dict[str, str]]:
    packages: dict[tuple[str, str], dict[str, str]] = {}

    for xml_path in sorted(output_dir.glob("*.xml")):
        try:
            root = ET.fromstring(xml_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue

        # CycloneDX-like extraction: /bom/components/component
        for node in root.iter():
            if _tag_name(node) != "component":
                continue

            name = ""
            version = ""
            homepage = ""
            license_text = ""

            for child in node:
                child_name = _tag_name(child)
                text = (child.text or "").strip()
                if child_name == "name" and text:
                    name = text
                elif child_name == "version" and text:
                    version = text
                elif child_name == "licenses":
                    values: list[str] = []
                    for license_node in child.iter():
                        tname = _tag_name(license_node)
                        tval = (license_node.text or "").strip()
                        if tname in {"id", "name", "expression"} and tval:
                            values.append(tval)
                    if values:
                        license_text = ", ".join(dict.fromkeys(values))
                elif child_name == "externalreferences":
                    for ref in child:
                        if _tag_name(ref) != "reference":
                            continue
                        ref_type = (ref.attrib.get("type") or "").lower()
                        url = ""
                        for ref_child in ref:
                            if _tag_name(ref_child) == "url":
                                url = (ref_child.text or "").strip()
                                break
                        if url and (not homepage or ref_type in {"website", "distribution", "vcs"}):
                            homepage = url

            if not name:
                continue

            key = (name, version)
            existing = packages.get(key)
            if not existing:
                packages[key] = {
                    "Component": name,
                    "Version": version,
                    "License": license_text,
                    "Home Page": homepage,
                    "Usage": "",
                }
                continue

            if not existing["License"] and license_text:
                existing["License"] = license_text
            if not existing["Home Page"] and homepage:
                existing["Home Page"] = homepage

    return packages


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in value.items()))
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _extract_scan_enrichment(scan_data: Any) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return (usage_map, license_map) keyed by component name from ORT scan-result.yml."""
    usage_map: dict[str, list[str]] = {}
    license_map: dict[str, list[str]] = {}

    scanner = scan_data.get("scanner") if isinstance(scan_data, dict) else None
    if not isinstance(scanner, dict):
        return usage_map, license_map

    provenance_to_components: dict[Any, list[str]] = {}
    for prov_entry in scanner.get("provenances") or []:
        if not isinstance(prov_entry, dict):
            continue
        package_id = prov_entry.get("id")
        package_provenance = prov_entry.get("package_provenance")
        if not package_id or not isinstance(package_provenance, dict):
            continue

        component, _ = _parse_package_id(str(package_id))
        if not component:
            continue

        key = _freeze(package_provenance)
        bucket = provenance_to_components.setdefault(key, [])
        if component not in bucket:
            bucket.append(component)

    for scan_entry in scanner.get("scan_results") or []:
        if not isinstance(scan_entry, dict):
            continue

        provenance = scan_entry.get("provenance")
        summary = scan_entry.get("summary")
        if not isinstance(provenance, dict) or not isinstance(summary, dict):
            continue

        components = provenance_to_components.get(_freeze(provenance), [])
        if not components:
            continue

        license_rows = summary.get("licenses") or []
        if not isinstance(license_rows, list):
            continue

        for item in license_rows:
            if not isinstance(item, dict):
                continue

            license_text = str(item.get("license") or "").strip()
            location = item.get("location")
            file_path = ""
            if isinstance(location, dict):
                file_path = str(location.get("path") or "").strip()

            for component in components:
                if license_text:
                    license_bucket = license_map.setdefault(component, [])
                    if license_text not in license_bucket:
                        license_bucket.append(license_text)

                if file_path:
                    usage_bucket = usage_map.setdefault(component, [])
                    if file_path not in usage_bucket:
                        usage_bucket.append(file_path)

    return usage_map, license_map


def generate_component_inventory_csv(output_dir: Path) -> Path | None:
    """Generate OSS component inventory CSV from ORT results in output_dir."""
    analyzer_path = output_dir / "analyzer-result.yml"
    scan_path = output_dir / "scan-result.yml"

    analyzer_data = _safe_load(analyzer_path)
    packages: dict[tuple[str, str], dict[str, str]] = {}
    if analyzer_data:
        packages = _extract_packages(analyzer_data)

    # Fallback/augmentation from generated XML artifacts (e.g. CycloneDX).
    xml_packages = _extract_packages_from_xml(output_dir)
    for key, row in xml_packages.items():
        existing = packages.get(key)
        if not existing:
            packages[key] = row
            continue
        if not existing["License"] and row["License"]:
            existing["License"] = row["License"]
        if not existing["Home Page"] and row["Home Page"]:
            existing["Home Page"] = row["Home Page"]

    if not packages:
        return None

    usage_map: dict[str, list[str]] = {}
    license_map: dict[str, list[str]] = {}
    scan_data = _safe_load(scan_path)
    if scan_data:
        usage_map, license_map = _extract_scan_enrichment(scan_data)

    for row in packages.values():
        usage_entries = usage_map.get(row["Component"], [])
        if usage_entries:
            row["Usage"] = " | ".join(f"file={path}" for path in usage_entries[:5])
        detected_licenses = license_map.get(row["Component"], [])
        if detected_licenses:
            detected_text = ", ".join(detected_licenses[:5])
            if row["License"]:
                if detected_text not in row["License"]:
                    row["License"] = f"{row['License']} | detected: {detected_text}"
            else:
                row["License"] = f"detected: {detected_text}"

    csv_path = output_dir / "component-inventory.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["Component", "Version", "License", "Home Page", "Usage"],
        )
        writer.writeheader()
        for key in sorted(packages.keys(), key=lambda item: (item[0].lower(), item[1])):
            writer.writerow(packages[key])

    return csv_path
