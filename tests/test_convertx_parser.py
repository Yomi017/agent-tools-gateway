from __future__ import annotations

from toolhub.backends.convertx import parse_progress, parse_targets


def test_parse_button_targets() -> None:
    html = """
    <button data-value="jpg,imagemagick" data-target="jpg" data-converter="imagemagick">jpg</button>
    <button data-value="webp,vips" data-target="webp" data-converter="vips">webp</button>
    """

    targets = parse_targets(html)

    assert [target.model_dump() for target in targets] == [
        {"target": "jpg", "converter": "imagemagick", "value": "jpg,imagemagick"},
        {"target": "webp", "converter": "vips", "value": "webp,vips"},
    ]


def test_parse_option_targets() -> None:
    html = """
    <select>
      <optgroup label="pandoc">
        <option value="pdf,pandoc">pdf</option>
      </optgroup>
    </select>
    """

    targets = parse_targets(html)

    assert len(targets) == 1
    assert targets[0].target == "pdf"
    assert targets[0].converter == "pandoc"


def test_parse_progress_done_and_pending() -> None:
    assert parse_progress('<progress max="2" value="2"></progress>').done is True
    assert parse_progress('<progress max="2"></progress>').done is False
