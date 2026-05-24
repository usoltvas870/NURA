"""Copy 0517 as template — clear tracks/materials, clean timelines."""
import json
import shutil
from pathlib import Path

SRC = Path.home() / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft/0517"
DST = Path(__file__).resolve().parent.parent / "videos/template"

def clean():
    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST)

    for f in DST.rglob("*.bak"):
        f.unlink()
    for f in DST.rglob("*.tmp"):
        f.unlink()

    content_path = DST / "draft_content.json"
    content = json.loads(content_path.read_text("utf-8"))
    content_id = content.get("id", "")
    content["tracks"] = []
    for k in content.get("materials", {}):
        content["materials"][k] = []
    content["duration"] = 0
    content["name"] = ""
    content_path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")

    tl_dir = DST / "Timelines"
    if tl_dir.exists():
        for sub in list(tl_dir.iterdir()):
            if sub.is_dir() and sub.name != content_id:
                shutil.rmtree(sub)
        pj_path = tl_dir / "project.json"
        if pj_path.exists():
            pj = json.loads(pj_path.read_text("utf-8"))
            if pj.get("main_timeline_id") != content_id:
                pj["main_timeline_id"] = content_id
                pj_path.write_text(json.dumps(pj, ensure_ascii=False), encoding="utf-8")

    print(f"Template created from 0517: {DST}")
    print(f"Files: {sum(1 for _ in DST.rglob('*') if _.is_file())}")

if __name__ == "__main__":
    clean()
