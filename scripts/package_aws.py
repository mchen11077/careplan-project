"""Create the Lambda bundle using the same intake adapters as Django."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
target = root / "aws" / "package"
target.mkdir(exist_ok=True)
for source in (root / "aws" / "lambda").glob("*.py"):
    shutil.copyfile(source, target / source.name)
shutil.copyfile(root / "shared" / "adapters.py", target / "adapters.py")
print("Prepared aws/package for Terraform archive_file.")
