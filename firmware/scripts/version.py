Import("env")
import pathlib

# Read version from VERSION file
version_file = pathlib.Path(env["PROJECT_DIR"]).parent / "VERSION"
try:
    v = version_file.read_text().strip()
except Exception:
    v = "dev"

# Inject FW_VERSION as a C string define
env.Append(CPPDEFINES=[("FW_VERSION", env.StringifyMacro(v))])
