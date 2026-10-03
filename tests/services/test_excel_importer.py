"""Tests for Excel scene import parsing and validation."""

from __future__ import annotations

import io

from openpyxl import Workbook

from vidx.services.excel.importer import parse_scene_workbook


def make_workbook(rows, headers=("Image Prompt", "Scene Prompt", "Audio Prompt")) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(list(headers))
    for row in rows:
        sheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_derives_scene_numbers_from_row_order() -> None:
    data = make_workbook(
        [
            ("a cat", "the cat walks", "meow"),
            ("a dog", "the dog runs", "woof"),
        ],
    )
    result = parse_scene_workbook(data)
    assert result.errors == []
    assert [row.scene_number for row in result.rows] == [1, 2]
    assert result.rows[0].image_prompt == "a cat"
    assert result.rows[0].scene_prompt == "the cat walks"
    assert result.rows[0].audio_prompt == "meow"


def test_respects_explicit_scene_numbers() -> None:
    data = make_workbook(
        [("img", "prompt", "", 7), ("img2", "prompt2", "", 3)],
        headers=("Image Prompt", "Scene Prompt", "Audio Prompt", "Scene Number"),
    )
    result = parse_scene_workbook(data)
    assert result.errors == []
    assert [row.scene_number for row in result.rows] == [7, 3]


def test_duplicate_scene_numbers_rejected() -> None:
    data = make_workbook(
        [("a", "", "", 1), ("b", "", "", 1)],
        headers=("Image Prompt", "Scene Prompt", "Audio Prompt", "Scene Number"),
    )
    result = parse_scene_workbook(data)
    assert any("duplicate scene number" in error for error in result.errors)
    # The first occurrence is still parsed; the whole import is rejected by
    # the API when any row error is present.
    assert len(result.rows) == 1


def test_row_without_prompts_rejected() -> None:
    data = make_workbook(
        [("", "", "", 2)],
        headers=("Image Prompt", "Scene Prompt", "Audio Prompt", "Scene Number"),
    )
    result = parse_scene_workbook(data)
    assert any("at least one prompt" in error for error in result.errors)
    assert result.rows == []


def test_unknown_headers_rejected() -> None:
    data = make_workbook([("a", "b")], headers=("Foo", "Bar"))
    result = parse_scene_workbook(data)
    assert result.rows == []
    assert any("No recognizable prompt columns" in error for error in result.errors)


def test_invalid_scene_number_rejected() -> None:
    data = make_workbook(
        [("a", "", "", "abc")],
        headers=("Image Prompt", "Scene Prompt", "Audio Prompt", "Scene Number"),
    )
    result = parse_scene_workbook(data)
    assert result.rows == []
    assert any("positive integer" in error for error in result.errors)


def test_non_excel_bytes_rejected() -> None:
    result = parse_scene_workbook(b"this is not a workbook")
    assert result.rows == []
    assert any("Could not read the Excel file" in error for error in result.errors)


def test_blank_rows_are_skipped() -> None:
    data = make_workbook([("", "", ""), ("scene one", "", ""), (None, None, None)])
    result = parse_scene_workbook(data)
    assert result.errors == []
    assert len(result.rows) == 1
    assert result.rows[0].scene_number == 1
