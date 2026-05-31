"""Quick validation script -- compile check + encoding check + stub check."""
import py_compile, pathlib, sys

base = pathlib.Path(__file__).parent
errors = []
files = [
    f for f in base.rglob("*.py")
    if not any(p in str(f) for p in ["__pycache__", ".git", "validate.py"])
]

for f in files:
    try:
        py_compile.compile(str(f), doraise=True)
    except py_compile.PyCompileError as e:
        errors.append(f"COMPILE: {e}")
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
        if "\xc3\xa2" in text or "â€" in text:
            errors.append(f"ENCODING: {f}")
        for i, line in enumerate(text.splitlines(), 1):
            if "raise NotImplementedError" in line:
                errors.append(f"STUB: {f}:{i}")
    except Exception as ex:
        errors.append(f"READ ERROR: {f} -- {ex}")

print(f"Scanned {len(files)} files")
if errors:
    for e in errors:
        print(f"  {e}")
    sys.exit(1)
else:
    print("ALL PASS -- zero compile errors, zero encoding artifacts, zero stubs")
