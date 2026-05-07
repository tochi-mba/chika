"""``/api/skills/ui`` and ``/api/skills/<name>/asset/<path>`` —
expose every skill's UI manifest + serve the static assets it
references.

Why this exists
---------------

Skills declare their settings-tab UI via ``SKILL_UI`` in
``__init__.py``. The frontend SettingsModal fetches
``/api/skills/ui`` to learn which dynamic tabs to render, then
fetches each tab's static assets via the asset endpoint. The
extension popup does the same for its skill sections.

The asset endpoint is sandboxed: a request can only resolve files
inside the skill's own folder, only with paths declared in
``SKILL_UI`` (no traversal). That keeps the surface narrow and
prevents a malicious manifest entry from serving arbitrary repo
files.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from api.auth import require_auth
from chika.skills import iter_skill_ui_manifests, skill_folder

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/api/skills/ui")
async def list_skill_ui() -> dict:
    """Return every shipped skill's UI manifest, sorted by tab order.

    Shape::

        {
          "tabs": [
            {
              "skill":   "spotify",
              "label":   "Spotify",
              "order":   50,
              "frontend": {
                "component": "ui/SettingsCard.vue",
                "asset_url": "/api/skills/spotify/asset/ui/SettingsCard.vue",
              },
              "extension": {
                "html": "ui/section.html",
                "js":   "ui/section.js",
                "html_url": "/api/skills/spotify/asset/ui/section.html",
                "js_url":   "/api/skills/spotify/asset/ui/section.js",
              },
            },
            ...
          ]
        }

    The ``asset_url`` / ``html_url`` / ``js_url`` fields save the
    client from having to assemble the URL itself.
    """
    tabs: list[dict] = []
    for skill_name, manifest in iter_skill_ui_manifests():
        tab = manifest.get("settings_tab")
        if not isinstance(tab, dict):
            continue

        entry: dict = {
            "skill": skill_name,
            "label": str(tab.get("label", skill_name)),
            "order": int(tab.get("order", 100)),
        }

        frontend = tab.get("frontend") or {}
        if isinstance(frontend, dict) and frontend.get("component"):
            comp = str(frontend["component"])
            entry["frontend"] = {
                "component": comp,
                "asset_url": f"/api/skills/{skill_name}/asset/{comp}",
            }

        extension = tab.get("extension") or {}
        if isinstance(extension, dict):
            ext_out: dict = {}
            for key in ("html", "js"):
                rel = extension.get(key)
                if rel:
                    rel = str(rel)
                    ext_out[key] = rel
                    ext_out[f"{key}_url"] = f"/api/skills/{skill_name}/asset/{rel}"
            if ext_out:
                entry["extension"] = ext_out

        tabs.append(entry)

    tabs.sort(key=lambda t: (t["order"], t["skill"]))
    return {"tabs": tabs}


@router.get("/api/skills/{skill_name}/asset/{relative_path:path}")
async def get_skill_asset(skill_name: str, relative_path: str) -> FileResponse:
    """Serve a file from inside the named skill's folder.

    Path-traversal protection: the resolved absolute path must stay
    inside the skill folder. Symlinks pointing outside fail the same
    check. Only files referenced by the skill's ``SKILL_UI`` manifest
    are served — anything else returns 404 even if the file exists.
    """
    folder = skill_folder(skill_name)
    if folder is None:
        raise HTTPException(status_code=404, detail="skill_not_found")

    target = (folder / relative_path).resolve()
    folder_resolved = folder.resolve()
    try:
        target.relative_to(folder_resolved)
    except ValueError:
        raise HTTPException(status_code=400, detail="path_traversal")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="asset_not_found")

    # Check that the asset is actually declared in the skill's manifest
    # — anything else stays inaccessible even if it's in the folder.
    declared: set[str] = set()
    for name, manifest in iter_skill_ui_manifests():
        if name != skill_name:
            continue
        tab = manifest.get("settings_tab") or {}
        for surface in ("frontend", "extension"):
            block = tab.get(surface) or {}
            if isinstance(block, dict):
                for key in ("component", "html", "js"):
                    rel = block.get(key)
                    if isinstance(rel, str) and rel.strip():
                        declared.add(rel.strip())
    if relative_path not in declared:
        raise HTTPException(status_code=404, detail="asset_not_declared")

    return FileResponse(str(target))
