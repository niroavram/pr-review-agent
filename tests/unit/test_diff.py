import pytest

from pr_agent.ingest.diff import is_reviewable, parse_diff

DIFF = """\
diff --git a/src/a.py b/src/a.py
index 1111111..2222222 100644
--- a/src/a.py
+++ b/src/a.py
@@ -1,3 +1,4 @@
 x = 1
-y = 2
+y = 3
+z = 4
 w = 5
diff --git a/new.py b/new.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+print("hi")
+print("bye")
diff --git a/gone.py b/gone.py
deleted file mode 100644
index 4444444..0000000
--- a/gone.py
+++ /dev/null
@@ -1 +0,0 @@
-old = True
diff --git a/old_name.py b/new_name.py
similarity index 90%
rename from old_name.py
rename to new_name.py
index 5555555..6666666 100644
--- a/old_name.py
+++ b/new_name.py
@@ -1,2 +1,2 @@
 keep = 1
-v = 1
+v = 2
"""


def test_parse_diff_statuses_and_lines() -> None:
    files = {f.path: f for f in parse_diff(DIFF)}
    assert set(files) == {"src/a.py", "new.py", "gone.py", "new_name.py"}
    assert files["src/a.py"].status == "modified" and files["src/a.py"].added_lines == [2, 3]
    assert files["new.py"].status == "added" and files["new.py"].added_lines == [1, 2]
    assert files["gone.py"].status == "deleted" and files["gone.py"].added_lines == []
    renamed = files["new_name.py"]
    assert renamed.status == "renamed" and renamed.old_path == "old_name.py"
    assert files["src/a.py"].patch.startswith("diff --git a/src/a.py")
    assert "new.py" not in files["src/a.py"].patch


def test_parse_empty_diff() -> None:
    assert parse_diff("") == []


@pytest.mark.parametrize(
    "path",
    [
        "uv.lock",
        "poetry.lock",
        "web/package-lock.json",
        "Cargo.lock",
        "img/logo.PNG",
        "static/app.min.js",
        "vendor/lib/x.py",
        "a/third_party/y.py",
        "node_modules/z/index.js",
        "proto/user_pb2.py",
        "api.generated.ts",
    ],
)
def test_not_reviewable(path: str) -> None:
    assert not is_reviewable(path)


@pytest.mark.parametrize("path", ["src/store/orders.py", "README.md", "vendor.py", "lockout.py"])
def test_reviewable(path: str) -> None:
    assert is_reviewable(path)
