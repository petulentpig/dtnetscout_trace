from pathlib import Path

from setuptools import find_packages, setup


def find_version() -> str:
    version = "0.0.1"
    extension_yaml_path = Path(__file__).parent / "extension" / "extension.yaml"
    try:
        with open(extension_yaml_path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("version"):
                    version = line.split(" ")[-1].strip('"')
                    break
    except Exception:
        pass
    return version


setup(
    name="dynatracedev",
    version=find_version(),
    description="Dynatracedev python EF2 extension",
    author="Dynatrace",
    license="MIT",
    packages=find_packages(),
    python_requires=">=3.10",
    include_package_data=True,
    install_requires=[
        "dt-extensions-sdk",
        "requests>=2.31",
        "opentelemetry-api>=1.24",
        "opentelemetry-sdk>=1.24",
        "opentelemetry-exporter-otlp-proto-http>=1.24",
    ],
    extras_require={"dev": ["dt-extensions-sdk[cli]", "pytest>=7"]},
)
