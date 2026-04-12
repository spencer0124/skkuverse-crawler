from __future__ import annotations

from skkuverse_crawler.notices.backfill_attachment_referer import (
    _build_detail_url,
    _patch_attachments,
)


GNUBOARD_DEPT = {
    "id": "pharm",
    "strategy": "gnuboard",
    "baseUrl": "https://pharm.skku.edu/bbs/board.php",
    "boardParam": "bo_table",
    "boardName": "notice",
}

GNUBOARD_CUSTOM_DEPT = {
    "id": "nano",
    "strategy": "gnuboard-custom",
    "baseUrl": "https://nano.skku.edu/bbs/board.php",
    "boardParam": "tbl",
    "boardName": "bbs42",
    "detailMode": "VIEW",
}


class TestBuildDetailUrl:
    def test_gnuboard_from_query_detailpath(self):
        doc = {"articleNo": 100, "detailPath": "?bo_table=notice&wr_id=100"}
        assert _build_detail_url(doc, GNUBOARD_DEPT) == (
            "https://pharm.skku.edu/bbs/board.php?bo_table=notice&wr_id=100"
        )

    def test_gnuboard_fallback_from_config(self):
        doc = {"articleNo": 200, "detailPath": ""}
        assert _build_detail_url(doc, GNUBOARD_DEPT) == (
            "https://pharm.skku.edu/bbs/board.php?bo_table=notice&wr_id=200"
        )

    def test_gnuboard_custom_from_query_detailpath(self):
        doc = {"articleNo": 416, "detailPath": "?tbl=bbs42&mode=VIEW&num=416"}
        assert _build_detail_url(doc, GNUBOARD_CUSTOM_DEPT) == (
            "https://nano.skku.edu/bbs/board.php?tbl=bbs42&mode=VIEW&num=416"
        )

    def test_gnuboard_custom_fallback_from_config(self):
        doc = {"articleNo": 500, "detailPath": ""}
        assert _build_detail_url(doc, GNUBOARD_CUSTOM_DEPT) == (
            "https://nano.skku.edu/bbs/board.php?tbl=bbs42&mode=VIEW&num=500"
        )

    def test_absolute_url_detailpath(self):
        doc = {"articleNo": 1, "detailPath": "https://pharm.skku.edu/bbs/board.php?bo_table=notice&wr_id=1"}
        assert _build_detail_url(doc, GNUBOARD_DEPT) == doc["detailPath"]

    def test_bio_http_preserved(self):
        dept = {**GNUBOARD_DEPT, "baseUrl": "http://bio.skku.edu/bbs/board.php", "boardName": "N4"}
        doc = {"articleNo": 367, "detailPath": "?bo_table=N4&wr_id=367"}
        result = _build_detail_url(doc, dept)
        assert result.startswith("http://")
        assert "bio.skku.edu" in result


class TestPatchAttachments:
    def test_adds_referer_to_all(self):
        attachments = [
            {"name": "a.pdf", "url": "https://example.com/download.php?no=1"},
            {"name": "b.hwp", "url": "https://example.com/download.php?no=2"},
        ]
        result = _patch_attachments(attachments, "https://example.com/board.php?wr_id=1")

        assert result is not None
        assert len(result) == 2
        for att in result:
            assert att["referer"] == "https://example.com/board.php?wr_id=1"
            assert "name" in att
            assert "url" in att

    def test_skips_if_all_already_have_referer(self):
        attachments = [
            {"name": "a.pdf", "url": "https://x.com/d.php?no=1", "referer": "https://x.com/board?id=1"},
        ]
        result = _patch_attachments(attachments, "https://x.com/board?id=1")
        assert result is None

    def test_patches_partial_missing_referer(self):
        attachments = [
            {"name": "a.pdf", "url": "https://x.com/d.php?no=1", "referer": "https://x.com/old"},
            {"name": "b.pdf", "url": "https://x.com/d.php?no=2"},
        ]
        result = _patch_attachments(attachments, "https://x.com/board?id=1")
        assert result is not None
        assert len(result) == 2
        # Both get the new referer (overwrites old)
        assert result[0]["referer"] == "https://x.com/board?id=1"
        assert result[1]["referer"] == "https://x.com/board?id=1"
