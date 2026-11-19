"""Create the Lambda bundle using the same intake adapters as Django."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
target = root / "infra" / "aws" / "package"
target.mkdir(exist_ok=True)
for source in (root / "infra" / "aws" / "lambda").glob("*.py"):
    shutil.copyfile(source, target / source.name)
shutil.copyfile(root / "backend" / "shared" / "adapters.py", target / "adapters.py")
print("Prepared infra/aws/package for Terraform archive_file.")
