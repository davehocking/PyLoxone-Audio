"""
Synthetic shape of independently observed Library-root count discrepancy.

On the tested device, root offset 0 returned 21 rows but totalitems=20;
offset 16 returned five rows and offset 20 returned the final row. These
fixtures contain no household identifiers and do not explain firmware internals.
"""
# ruff: noqa: S101, INP001, ANN001, D103, PLR2004, SLF001

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.loxone.audio_catalogue import AudioCatalogue, CatalogueTarget


def row(index):
    return {"type": 2, "id": f"library:local:track:synthetic-{index}", "name": f"Track {index}"}


def catalogue():
    return AudioCatalogue(SimpleNamespace(async_media_folder=AsyncMock()), 7)


@pytest.mark.asyncio
async def test_library_root_accepts_observed_one_row_count_underrun():
    owner = catalogue()
    root = owner._item(CatalogueTarget("folder", "Local Library", "library", "0"))
    owner.commands.async_media_folder.return_value = [
        {"start": 0, "totalitems": 20, "items": [row(i) for i in range(21)]}
    ]
    page = await owner.async_browse(root.media_content_id)
    assert len(page.children) == 21
    assert all(item.can_play and not item.can_expand for item in page.children)
    owner.commands.async_media_folder.assert_awaited_once_with("library", "nouser", "0", 0)


@pytest.mark.asyncio
async def test_full_root_page_probes_boundary_instead_of_losing_final_row():
    owner = catalogue()
    root = owner._item(CatalogueTarget("folder", "Local Library", "library", "0"))
    owner.commands.async_media_folder.side_effect = [
        [{"start": 0, "totalitems": 50, "items": [row(i) for i in range(50)]}],
        [{"start": 50, "totalitems": 50, "items": [row(50)]}],
    ]
    first = await owner.async_browse(root.media_content_id)
    assert len(first.children) == 51
    more = first.children[-1]
    assert more.can_expand
    assert not more.can_play
    second = await owner.async_browse(more.media_content_id)
    assert [item.title for item in second.children] == ["Track 50"]
    assert [call.args[-1] for call in owner.commands.async_media_folder.await_args_list] == [0, 50]


@pytest.mark.asyncio
async def test_exact_full_root_page_can_finish_with_empty_boundary_page():
    owner = catalogue()
    root = owner._item(CatalogueTarget("folder", "Local Library", "library", "0"))
    owner.commands.async_media_folder.side_effect = [
        [{"start": 0, "totalitems": 49, "items": [row(i) for i in range(50)]}],
        [{"start": 50, "totalitems": 49, "items": []}],
    ]
    first = await owner.async_browse(root.media_content_id)
    second = await owner.async_browse(first.children[-1].media_content_id)
    assert second.children == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("service", "folder", "total"),
    [("library", "library:local:folder:one", 20), ("spotify", "start", 20), ("library", "0", 19)],
)
async def test_count_exception_does_not_relax_other_providers_or_larger_mismatches(service, folder, total):
    owner = catalogue()
    item = owner._item(
        CatalogueTarget("folder", "Folder", service, folder, account="owner" if service == "spotify" else "nouser")
    )
    owner._accounts = AsyncMock(return_value=[{"id": "owner"}])
    owner.commands.async_media_folder.return_value = [
        {"start": 0, "totalitems": total, "items": [row(i) for i in range(21)]}
    ]
    with pytest.raises(ValueError, match="page changed"):
        await owner.async_browse(item.media_content_id)
