"""CI: 관리자 PC 프로그램(pc/tvrelay)으로 직원 앱 zip 을 구워 풀어 둔다 — python make_toolapp.py <runtime.zip> <out폴더>"""
import io
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pc"))
from tvrelay import config, grants, toolapp  # noqa: E402

rt, out = Path(sys.argv[1]), Path(sys.argv[2])
root = Path(tempfile.mkdtemp())
cfg = config.setup("", "", "osan1", root, mode="bt")
g = grants.new_grant("원가"); g["status"] = "active"
name, data = toolapp.build(root, cfg, g, "pw1234", "tskey-auth-test", "100.64.0.9:8080", "", runtime=rt)
out.mkdir(parents=True, exist_ok=True)
zipfile.ZipFile(io.BytesIO(data)).extractall(out)
print("직원 앱:", name, "%.1f MB" % (len(data) / 1048576))
