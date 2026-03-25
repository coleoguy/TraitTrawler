#!/usr/bin/env python3
# PURPOSE: Execute this script. Do not read it into context.
# USAGE: python3 export_dwc.py --project-root /path/to/project --output-dir /path/to/output [--zip]
# OUTPUT: DwC-compliant files (occurrence.txt, meta.xml, eml.xml) in the output directory
"""
Darwin Core Archive Export Utility for TraitTrawler

Converts TraitTrawler's results.csv into a Darwin Core Archive (DwCA) for upload
to GBIF, iDigBio, and other biodiversity data infrastructure.

Darwin Core is the standard for biodiversity data exchange. This utility:
1. Reads results.csv and collector_config.yaml from a TraitTrawler project
2. Maps TraitTrawler fields to Darwin Core vocabulary terms
3. Generates DwC-compliant output files (occurrence.txt, meta.xml, eml.xml)
4. Optionally compresses into a .dwca archive file

Usage:
    python export_dwc.py --project-root /path/to/project --output-dir /path/to/output [--zip]
"""

import argparse
import csv
import json
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import quote

try:
    import yaml
except ImportError:
    yaml = None


class DarwinCoreExporter:
    """Export TraitTrawler results to Darwin Core Archive format."""

    # Darwin Core required columns for occurrence.txt
    DWC_COLUMNS = [
        'occurrenceID',
        'basisOfRecord',
        'catalogNumber',
        'scientificName',
        'genus',
        'family',
        'subfamily',
        'country',
        'locality',
        'decimalLatitude',
        'decimalLongitude',
        'year',
        'eventDate',
        'references',
        'bibliographicCitation',
        'informationWithheld',
        'dynamicProperties'
    ]

    # Mapping from TraitTrawler field names to DwC terms
    FIELD_MAPPING = {
        'species': 'scientificName',
        'genus': 'genus',
        'family': 'family',
        'subfamily': 'subfamily',
        'country': 'country',
        'collection_locality': 'locality',
        'latitude': 'decimalLatitude',
        'longitude': 'decimalLongitude',
        'collection_year': 'year',
        'paper_year': 'paper_year',  # Used for bibliographic citation
        'doi': 'references',
        'first_author': 'first_author',
        'paper_title': 'paper_title',
        'extraction_confidence': 'extraction_confidence',
        'source_type': 'source_type',
        'voucher_info': 'catalogNumber'
    }

    def __init__(self, project_root: Path, output_dir: Path):
        """
        Initialize the exporter.

        Args:
            project_root: Path to TraitTrawler project directory
            output_dir: Path to write output files
        """
        self.project_root = Path(project_root)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.results_csv = self.project_root / 'results.csv'
        self.config_yaml = self.project_root / 'collector_config.yaml'

        self.project_name = None
        self.trait_description = None
        self.records = []
        self.skipped_count = 0
        self.skip_reasons = {}

    def load_config(self) -> Dict[str, Any]:
        """Load configuration from collector_config.yaml."""
        if not self.config_yaml.exists():
            return {}

        try:
            if yaml:
                with open(self.config_yaml, 'r') as f:
                    config = yaml.safe_load(f) or {}
            else:
                # Fallback: basic YAML parsing without pyyaml
                config = self._parse_yaml_fallback(self.config_yaml)

            self.project_name = config.get('project_name', 'TraitTrawler Export')
            self.trait_description = config.get('trait_description',
                                               'Trait data extracted from literature')
            return config
        except Exception as e:
            print(f"Warning: Could not parse collector_config.yaml: {e}", file=sys.stderr)
            return {}

    def _parse_yaml_fallback(self, path: Path) -> Dict[str, Any]:
        """Basic YAML parser fallback (without pyyaml)."""
        config = {}
        try:
            with open(path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if ':' in line and not line.startswith('#'):
                        key, value = line.split(':', 1)
                        key = key.strip()
                        value = value.strip().strip("'\"")
                        config[key] = value
        except Exception:
            pass
        return config

    def load_results(self) -> List[Dict[str, str]]:
        """Load results from results.csv."""
        if not self.results_csv.exists():
            raise FileNotFoundError(f"results.csv not found at {self.results_csv}")

        records = []
        try:
            with open(self.results_csv, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                records = list(reader)
        except Exception as e:
            print(f"Error reading results.csv: {e}", file=sys.stderr)
            raise

        return records

    def extract_trait_fields(self, record: Dict[str, str]) -> Dict[str, Any]:
        """
        Extract trait-specific fields (all non-standard fields) into a dict.

        Args:
            record: A row from results.csv

        Returns:
            Dictionary of trait fields not in the standard mapping
        """
        trait_fields = {}
        standard_keys = set(self.FIELD_MAPPING.keys())

        for key, value in record.items():
            if key not in standard_keys and value:
                trait_fields[key] = value

        return trait_fields

    def map_record_to_dwc(self, record: Dict[str, str], record_id: int) -> Optional[Dict[str, str]]:
        """
        Map a single TraitTrawler record to Darwin Core format.

        Args:
            record: A row from results.csv
            record_id: Index/ID for this record

        Returns:
            Dictionary with DwC field names as keys, or None if skipped
        """
        dwc_record = {}

        # Generate occurrenceID
        dwc_record['occurrenceID'] = f"traitrawler_{record_id}"

        # Basis of Record - citation of material specimen
        dwc_record['basisOfRecord'] = 'MaterialCitation'

        # Catalog Number
        dwc_record['catalogNumber'] = record.get('voucher_info', '')

        # Taxonomic fields
        dwc_record['scientificName'] = record.get('species', '')
        dwc_record['genus'] = record.get('genus', '')
        dwc_record['family'] = record.get('family', '')
        dwc_record['subfamily'] = record.get('subfamily', '')

        # Geographic fields
        dwc_record['country'] = record.get('country', '')
        dwc_record['locality'] = record.get('collection_locality', '')

        # Attempt to parse latitude/longitude
        try:
            lat = float(record.get('latitude', ''))
            lon = float(record.get('longitude', ''))
            dwc_record['decimalLatitude'] = str(lat)
            dwc_record['decimalLongitude'] = str(lon)
        except (ValueError, TypeError):
            dwc_record['decimalLatitude'] = ''
            dwc_record['decimalLongitude'] = ''

        # Temporal fields
        year_str = record.get('collection_year', '')
        dwc_record['year'] = year_str
        dwc_record['eventDate'] = self._format_event_date(year_str, record)

        # References
        doi = record.get('doi', '')
        dwc_record['references'] = f"https://doi.org/{doi}" if doi else ''

        # Bibliographic Citation
        dwc_record['bibliographicCitation'] = self._build_citation(record)

        # Information Withheld (if confidence < 0.75)
        try:
            confidence = float(record.get('extraction_confidence', 1.0))
            if confidence < 0.75:
                dwc_record['informationWithheld'] = f"Low confidence ({confidence:.2f})"
            else:
                dwc_record['informationWithheld'] = ''
        except (ValueError, TypeError):
            dwc_record['informationWithheld'] = ''

        # Dynamic Properties (trait-specific fields as JSON)
        trait_fields = self.extract_trait_fields(record)
        if trait_fields:
            dwc_record['dynamicProperties'] = json.dumps(trait_fields)
        else:
            dwc_record['dynamicProperties'] = ''

        return dwc_record

    def _format_event_date(self, year_str: str, record: Dict[str, str]) -> str:
        """
        Format eventDate in ISO 8601 format (YYYY-MM-DD).

        Falls back to just YYYY if month/day not available.
        """
        if not year_str:
            return ''

        try:
            year = int(year_str)
            month = record.get('collection_month', '')
            day = record.get('collection_day', '')

            if month and day:
                month_int = int(month)
                day_int = int(day)
                return f"{year:04d}-{month_int:02d}-{day_int:02d}"
            elif month:
                month_int = int(month)
                return f"{year:04d}-{month_int:02d}"
            else:
                return f"{year:04d}"
        except (ValueError, TypeError):
            return year_str

    def _build_citation(self, record: Dict[str, str]) -> str:
        """Build a bibliographic citation from record fields."""
        parts = []

        first_author = record.get('first_author', '').strip()
        if first_author:
            parts.append(first_author)

        year = record.get('paper_year', '').strip()
        if year:
            parts.append(f"({year})")

        title = record.get('paper_title', '').strip()
        if title:
            parts.append(f'"{title}"')

        doi = record.get('doi', '').strip()
        if doi:
            parts.append(f"https://doi.org/{doi}")

        return ' '.join(parts) if parts else ''

    def export_occurrence(self) -> Tuple[int, int]:
        """
        Export records to occurrence.txt (tab-delimited DwC format).

        Returns:
            Tuple of (exported_count, skipped_count)
        """
        self.load_config()
        raw_records = self.load_results()

        exported_count = 0

        occurrence_file = self.output_dir / 'occurrence.txt'

        try:
            with open(occurrence_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=self.DWC_COLUMNS,
                    delimiter='\t',
                    extrasaction='ignore'
                )
                writer.writeheader()

                for idx, raw_record in enumerate(raw_records, 1):
                    dwc_record = self.map_record_to_dwc(raw_record, idx)

                    if dwc_record:
                        # Write with nulls for missing fields
                        clean_record = {col: dwc_record.get(col, '') for col in self.DWC_COLUMNS}
                        writer.writerow(clean_record)
                        exported_count += 1
                    else:
                        self.skipped_count += 1
                        self.skip_reasons['validation_failed'] = \
                            self.skip_reasons.get('validation_failed', 0) + 1

        except Exception as e:
            print(f"Error writing occurrence.txt: {e}", file=sys.stderr)
            raise

        self.records = raw_records
        return exported_count, self.skipped_count

    def export_meta_xml(self) -> Path:
        """
        Generate meta.xml (Darwin Core Archive descriptor).

        Defines field mappings and index key for the occurrence.txt file.
        """
        meta_file = self.output_dir / 'meta.xml'

        meta_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<archive xmlns="http://rs.tdwg.org/dwc/text/" metadata="eml.xml">
  <core encoding="UTF-8" linesTerminatedBy="\\n" fieldsTerminatedBy="\\t"
         fieldsEnclosedBy="" ignoreHeaderLines="1" rowType="http://rs.tdwg.org/dwc/terms/Occurrence">
    <files>
      <location>occurrence.txt</location>
    </files>
    <id index="0" />
    <field index="0" term="http://rs.tdwg.org/dwc/terms/occurrenceID" />
    <field index="1" term="http://rs.tdwg.org/dwc/terms/basisOfRecord" />
    <field index="2" term="http://rs.tdwg.org/dwc/terms/catalogNumber" />
    <field index="3" term="http://rs.tdwg.org/dwc/terms/scientificName" />
    <field index="4" term="http://rs.tdwg.org/dwc/terms/genus" />
    <field index="5" term="http://rs.tdwg.org/dwc/terms/family" />
    <field index="6" term="http://rs.tdwg.org/dwc/terms/subfamily" />
    <field index="7" term="http://rs.tdwg.org/dwc/terms/country" />
    <field index="8" term="http://rs.tdwg.org/dwc/terms/locality" />
    <field index="9" term="http://rs.tdwg.org/dwc/terms/decimalLatitude" />
    <field index="10" term="http://rs.tdwg.org/dwc/terms/decimalLongitude" />
    <field index="11" term="http://rs.tdwg.org/dwc/terms/year" />
    <field index="12" term="http://rs.tdwg.org/dwc/terms/eventDate" />
    <field index="13" term="http://rs.tdwg.org/dwc/terms/references" />
    <field index="14" term="http://rs.tdwg.org/dwc/terms/bibliographicCitation" />
    <field index="15" term="http://rs.tdwg.org/dwc/terms/informationWithheld" />
    <field index="16" term="http://rs.tdwg.org/dwc/terms/dynamicProperties" />
  </core>
</archive>
'''

        try:
            with open(meta_file, 'w', encoding='utf-8') as f:
                f.write(meta_xml)
        except Exception as e:
            print(f"Error writing meta.xml: {e}", file=sys.stderr)
            raise

        return meta_file

    def export_eml_xml(self) -> Path:
        """
        Generate eml.xml (Ecological Metadata Language dataset description).

        Includes project name, description, and timestamp.
        """
        eml_file = self.output_dir / 'eml.xml'

        timestamp = datetime.utcnow().isoformat() + 'Z'

        eml_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<eml:eml xmlns:eml="https://eml.ecoinformatics.org/eml-2.2.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="https://eml.ecoinformatics.org/eml-2.2.0 https://eml.ecoinformatics.org/eml-2.2.0/eml.xsd"
         packageId="traitrawler-{timestamp}" system="TraitTrawler">
  <dataset>
    <title>{self._escape_xml(self.project_name or 'TraitTrawler Dataset')}</title>
    <abstract>
      <para>{self._escape_xml(self.trait_description or 'Trait data extracted from scientific literature using TraitTrawler.')}</para>
    </abstract>
    <pubDate>{timestamp}</pubDate>
    <language>en</language>
    <contact>
      <references>creator</references>
    </contact>
    <creator id="creator">
      <individualName>
        <surName>TraitTrawler</surName>
      </individualName>
      <organizationName>TraitTrawler</organizationName>
    </creator>
  </dataset>
</eml:eml>
'''

        try:
            with open(eml_file, 'w', encoding='utf-8') as f:
                f.write(eml_xml)
        except Exception as e:
            print(f"Error writing eml.xml: {e}", file=sys.stderr)
            raise

        return eml_file

    def _escape_xml(self, text: str) -> str:
        """Escape special XML characters."""
        if not text:
            return ''
        return (text.replace('&', '&amp;')
                    .replace('<', '&lt;')
                    .replace('>', '&gt;')
                    .replace('"', '&quot;')
                    .replace("'", '&apos;'))

    def create_archive(self, zip_path: Optional[Path] = None) -> Optional[Path]:
        """
        Create a .dwca (zipped) archive from the generated files.

        Args:
            zip_path: Path for the output .dwca file. If None, uses output_dir/archive.dwca

        Returns:
            Path to the created archive, or None if not requested
        """
        if not zip_path:
            return None

        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.write(self.output_dir / 'occurrence.txt', 'occurrence.txt')
                zf.write(self.output_dir / 'meta.xml', 'meta.xml')
                zf.write(self.output_dir / 'eml.xml', 'eml.xml')
        except Exception as e:
            print(f"Error creating archive: {e}", file=sys.stderr)
            raise

        return zip_path

    def export(self, create_zip: bool = False) -> None:
        """
        Perform full export: occurrence.txt, meta.xml, eml.xml, and optional .dwca.

        Args:
            create_zip: If True, also create a .dwca archive file
        """
        exported_count, skipped_count = self.export_occurrence()
        self.export_meta_xml()
        self.export_eml_xml()

        zip_path = None
        if create_zip:
            zip_path = self.output_dir / 'archive.dwca'
            zip_path = self.create_archive(zip_path)

        # Print summary
        print(f"\n{'='*60}")
        print(f"Darwin Core Archive Export Summary")
        print(f"{'='*60}")
        print(f"Records exported: {exported_count}")
        print(f"Records skipped: {skipped_count}")
        if self.skip_reasons:
            for reason, count in self.skip_reasons.items():
                print(f"  - {reason}: {count}")
        print(f"Output directory: {self.output_dir}")
        print(f"  - occurrence.txt (DwC records)")
        print(f"  - meta.xml (Archive descriptor)")
        print(f"  - eml.xml (Dataset metadata)")
        if zip_path:
            print(f"  - {zip_path.name} (Compressed archive)")
        print(f"{'='*60}\n")


def main():
    """Parse arguments and run the exporter."""
    parser = argparse.ArgumentParser(
        description='Convert TraitTrawler results to Darwin Core Archive format'
    )
    parser.add_argument(
        '--project-root',
        type=str,
        required=True,
        help='Path to TraitTrawler project directory (containing results.csv)'
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        required=True,
        help='Directory to write DwC Archive files'
    )
    parser.add_argument(
        '--zip',
        action='store_true',
        help='Create a .dwca (zipped) archive file'
    )

    args = parser.parse_args()

    try:
        exporter = DarwinCoreExporter(
            project_root=args.project_root,
            output_dir=args.output_dir
        )
        exporter.export(create_zip=args.zip)
        sys.exit(0)
    except Exception as e:
        print(f"Export failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
