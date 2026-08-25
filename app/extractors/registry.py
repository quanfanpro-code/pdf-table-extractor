import importlib
import pkgutil
from pathlib import Path
from typing import Callable

from app.models import StatementExtraction


Extractor = Callable[[Path], StatementExtraction | None]
SKIPPED_MODULES = {"ai_vision", "registry"}


def iter_local_extractors() -> list[tuple[str, Extractor]]:
    discovered: list[tuple[str, str, Extractor]] = []
    package_name = __package__
    package = importlib.import_module(package_name)

    for module_info in pkgutil.iter_modules(package.__path__):
        module_name = module_info.name
        if module_name.startswith("_") or module_name in SKIPPED_MODULES:
            continue
        module = importlib.import_module(f"{package_name}.{module_name}")
        extractor = getattr(module, f"extract_{module_name}", None)
        if not callable(extractor):
            continue
        label = str(getattr(module, "EXTRACTOR_LABEL", module_name))
        discovered.append((module_name, label, extractor))

    discovered.sort(key=lambda item: (item[0] == "generic_table", item[1].casefold()))
    return [(label, extractor) for _module_name, label, extractor in discovered]
