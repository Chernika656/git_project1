"""Совместимость со старой командой запуска; реализация в facet.bpmn.checker."""
from facet.bpmn.checker import main

if __name__ == "__main__":
    raise SystemExit(main())
