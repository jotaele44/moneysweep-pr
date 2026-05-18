"""Tests for scripts/download_ofac.py — namespace-robust XML parsing."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.download_ofac import _parse_sdn_xml


class _NullLogger:
    def info(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def error(self, *a, **kw): pass
    def debug(self, *a, **kw): pass


# ---------------------------------------------------------------------------
# _parse_sdn_xml — namespace detection
# ---------------------------------------------------------------------------

class TestParseSdnXml:
    def test_no_namespace(self):
        xml = b"""<?xml version="1.0"?>
<sdnList>
  <sdnEntry>
    <uid>100</uid>
    <lastName>SMUGGLER</lastName>
    <firstName>JOHN</firstName>
    <sdnType>Individual</sdnType>
    <programList>
      <program>SDGT</program>
    </programList>
  </sdnEntry>
</sdnList>"""
        df = _parse_sdn_xml(xml, _NullLogger())
        assert len(df) == 1
        assert df.iloc[0]["uid"] == "100"
        assert df.iloc[0]["name"] == "SMUGGLER, JOHN"
        assert df.iloc[0]["sdn_type"] == "Individual"

    def test_legacy_namespace(self):
        xml = b"""<?xml version="1.0"?>
<sdnList xmlns="http://tempuri.org/sdnList.xsd">
  <sdnEntry>
    <uid>200</uid>
    <lastName>ACME CARTEL</lastName>
    <sdnType>Entity</sdnType>
  </sdnEntry>
</sdnList>"""
        df = _parse_sdn_xml(xml, _NullLogger())
        assert len(df) == 1
        assert df.iloc[0]["uid"] == "200"
        assert df.iloc[0]["name"] == "ACME CARTEL"

    def test_alternate_namespace_detected_from_root(self):
        """Robustness: if OFAC changes the namespace URI, we should still parse."""
        xml = b"""<?xml version="1.0"?>
<sdnList xmlns="http://www.treasury.gov/ofac/sdnList/2.0">
  <sdnEntry>
    <uid>300</uid>
    <lastName>BAD ACTOR</lastName>
    <sdnType>Individual</sdnType>
  </sdnEntry>
</sdnList>"""
        df = _parse_sdn_xml(xml, _NullLogger())
        assert len(df) == 1
        assert df.iloc[0]["uid"] == "300"
        assert df.iloc[0]["name"] == "BAD ACTOR"

    def test_empty_xml_returns_empty_df(self):
        xml = b"""<?xml version="1.0"?><sdnList></sdnList>"""
        df = _parse_sdn_xml(xml, _NullLogger())
        assert len(df) == 0

    def test_invalid_xml_returns_empty_df(self):
        df = _parse_sdn_xml(b"not xml at all", _NullLogger())
        assert len(df) == 0

    def test_handles_first_only_name(self):
        xml = b"""<?xml version="1.0"?>
<sdnList>
  <sdnEntry>
    <uid>400</uid>
    <lastName>SOLO ENTITY</lastName>
    <sdnType>Entity</sdnType>
  </sdnEntry>
</sdnList>"""
        df = _parse_sdn_xml(xml, _NullLogger())
        assert df.iloc[0]["name"] == "SOLO ENTITY"
